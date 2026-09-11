import { randomUUID } from "node:crypto";
import { lstatSync, realpathSync } from "node:fs";
import { isAbsolute } from "node:path";
import type { DeviceJob } from "./device-coordinator";
import { DeviceClient, type DeviceLeaseAuthority } from "./device-client";
import { digest, identifier, object, requireThat } from "./value";
import { ProcessSupervisor, type ProcessSpec, type ProcessOutcome } from "./process-supervisor";

export interface DeviceAdapterContext {
  job: DeviceJob;
  workspace: string;
  authority: DeviceLeaseAuthority;
  assertCurrent: () => void;
  runProcess: (spec: Omit<ProcessSpec, "cwd">) => Promise<ProcessOutcome>;
}
export interface DeviceAdapter {
  /** Must verify its native result; returning only an exit code is not semantic acceptance. */
  execute(context: DeviceAdapterContext): Promise<{ observation: Record<string, unknown>; result: Record<string, unknown> }>;
}
export interface DeviceWorkerOptions {
  workspaces: Readonly<Record<string, string>>;
  adapters: Readonly<Record<string, DeviceAdapter>>;
}

/** No shell strings or paths from the coordinator select executable code. Both maps are local configuration. */
export class DeviceWorker {
  private readonly workspaces = new Map<string, { path: string; dev: number; ino: number }>();
  private readonly adapters: Readonly<Record<string, DeviceAdapter>>;

  constructor(private readonly client: DeviceClient, options: DeviceWorkerOptions) {
    this.adapters = { ...options.adapters };
    for (const [id, path] of Object.entries(options.workspaces)) {
      identifier(id);
      requireThat(isAbsolute(path) && realpathSync(path) === path, "workspace_must_be_canonical");
      const stat = lstatSync(path);
      requireThat(stat.isDirectory(), "invalid_worker_workspace");
      this.workspaces.set(id, { path, dev: stat.dev, ino: stat.ino });
    }
  }

  async run(taskId: string, ttlMs = 10_000): Promise<{ status: "done" | "unknown"; result?: Record<string, unknown> }> {
    const job = await this.client.inspect(taskId);
    const workspace = this.workspaces.get(job.workspace_id);
    const adapter = Object.hasOwn(this.adapters, job.capability) ? this.adapters[job.capability] : undefined;
    requireThat(workspace && adapter && typeof adapter.execute === "function", "local_capability_unavailable");
    const assertWorkspace = () => {
      const stat = lstatSync(workspace.path);
      requireThat(stat.isDirectory() && !stat.isSymbolicLink() && realpathSync(workspace.path) === workspace.path && stat.dev === workspace.dev && stat.ino === workspace.ino, "worker_workspace_changed");
    };
    assertWorkspace();
    const authority = await this.client.claim(taskId, job.revision, job.assignment_digest, ttlMs);
    const assertCurrent = () => { authority.assertCurrent(); assertWorkspace(); };
    const effect = randomUUID();
    let dispatched = false;
    let renewal: Promise<void> | undefined;
    let closed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const arm = () => {
      if (closed) return;
      timer = setTimeout(() => {
        renewal = authority.renew().catch(() => { closed = true; authority.stop(); }).finally(() => { renewal = undefined; arm(); });
      }, Math.max(100, Math.floor(ttlMs / 4)));
    };
    try {
      await authority.start();
      arm();
      assertCurrent();
      const permit = await this.client.command("dispatch", { lease: authority.lease, effect_id: effect, intent: { capability: job.capability, workspace_id: job.workspace_id, input_digest: digest(job.input) } });
      requireThat(object(permit) && permit.effect_id === effect && permit.dispatch_permitted === true, "effect_dispatch_not_permitted");
      dispatched = true;
      assertCurrent();
      const output = await adapter.execute({ job, workspace: workspace.path, authority, assertCurrent,
        runProcess: spec => new ProcessSupervisor().run({ ...spec, cwd: workspace.path }, { assertCurrent, remainingMs: authority.remainingMs, signal: authority.signal }) });
      assertCurrent();
      await this.client.command("observe", { lease: authority.lease, effect_id: effect, observation: output.observation });
      // Drain renewal before terminal commit; a successful completion must not race a late renewal error.
      closed = true;
      if (timer) clearTimeout(timer);
      await renewal;
      assertCurrent();
      const completion = await this.client.command("complete", { lease: authority.lease, effect_id: effect, result: output.result });
      requireThat(object(completion) && completion.task_id === taskId && completion.status === "done", "completion_unproven");
      return { status: "done", result: output.result };
    } catch {
      // A lost dispatch or completion response is uncertain too. Never repeat a native operation here.
      try { await this.client.command("unknown", { lease: authority.lease, reason: dispatched ? "worker_outcome_unproven" : "worker_admission_unproven" }); } catch { /* coordinator expiry recovery retains the unknown result */ }
      return { status: "unknown" };
    } finally {
      closed = true;
      if (timer) clearTimeout(timer);
      authority.stop();
      await renewal;
    }
  }
}
