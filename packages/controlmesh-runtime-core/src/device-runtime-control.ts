import { topologyControl, topologyControlFields } from "./topology-control";
import type { TopologyScheduler } from "./topology-scheduler";
import type { DeviceTopologyRuntime } from "./device-topology-runtime";
import { adoptSpecMeshCompletion, unchangedSpecMeshCompletion } from "./specmesh-completion";
import type { SpecMeshPort } from "./specmesh-port";
import type { DeviceClient } from "./device-client";
import type { DeviceCoordinator, DeviceRegistration } from "./device-coordinator";
import type { DeviceWorker, DeviceRunAdmission, DeviceRunOutcome } from "./device-worker";
import type { DeviceScheduler } from "./device-scheduler";
import type { RuntimeDatabase } from "./database";
import type { RuntimeKernel, Principal } from "./kernel";
import { TaskIngress } from "./task-ingress";
import { command, commandReceipt, reserveCommand, requireScope } from "./commands";
import { digest, identifier, object, requireThat, RuntimeConflict, type LegacyTask } from "./value";
import { assertProtocolSchema } from "@controlmesh/protocol";
import type { DeviceNativeAdoptions } from "./providers/device-native-adoption";

export interface RuntimeControl { handle(request: unknown): Promise<Record<string, unknown>> }
export type DeviceHistoryControl = Pick<DeviceNativeAdoptions<"opencode" | "claude">, "search" | "refresh" | "prepare" | "stop">;

function request(input: unknown, fields: Record<string, readonly string[]>): Record<string, unknown> {
  requireThat(object(input), "invalid_device_control_request"); identifier(input.id);
  requireThat(typeof input.op === "string" && Object.hasOwn(fields, input.op), "unknown_device_control_operation");
  requireThat(Object.keys(input).every(key => ["id", "op", ...fields[input.op as string]].includes(key)), "unexpected_device_control_field");
  return input;
}
function failure(id: unknown, error: unknown): Record<string, unknown> {
  return { id: typeof id === "string" ? id : null, ok: false, error: error instanceof RuntimeConflict ? error.code : "device_control_error" };
}

/** Private trusted stdin control; workers cannot use this surface to grant or assign themselves. */
export class DeviceCoordinatorControl implements RuntimeControl {
  private readonly ingress: TaskIngress;
  private server?: Bun.Server<undefined>;
  private stopped = false;
  private maintenance?: ReturnType<typeof setInterval>;
  private topology?: { scheduler: TopologyScheduler; runtime: DeviceTopologyRuntime; auto_start: boolean };
  attachTopology(scheduler: TopologyScheduler, runtime: DeviceTopologyRuntime, autoStart: boolean) {
    requireThat(!this.topology, "topology_scheduler_already_configured"); this.topology = { scheduler, runtime, auto_start: autoStart };
  }
  constructor(private readonly kernel: RuntimeKernel, private readonly actor: Principal,
    private readonly coordinator: DeviceCoordinator, private readonly devices: readonly DeviceRegistration[],
    private readonly assertCurrent: () => void, private readonly port = 0, private readonly specmesh?: SpecMeshPort) {
    this.ingress = new TaskIngress(kernel, { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: "cm-device" }, assertCurrent);
  }
  async stop(): Promise<void> { this.stopped = true; if (this.maintenance) clearInterval(this.maintenance); await Promise.all([this.topology?.scheduler.stop(), this.topology?.runtime.stop(), this.server?.stop(true), this.specmesh?.stop()]); this.server = undefined; }
  startDaemon(): void {
    this.assertCurrent(); requireThat(!this.stopped, "device_runtime_stopped");
    this.server ??= this.coordinator.listen(this.port);
    if (this.topology?.auto_start) this.topology.scheduler.start();
    const recover = () => { this.assertCurrent(); this.kernel.recoverExpired({ ...this.actor, origin: "recovery" }); };
    recover(); this.maintenance ??= setInterval(() => { try { recover(); } catch { void this.stop(); } }, 2000);
  }
  async handle(input: unknown): Promise<Record<string, unknown>> {
    let id: unknown = null;
    try {
      this.assertCurrent(); requireThat(!this.stopped, "device_runtime_stopped");
      const value = request(input, {
        ...topologyControlFields,
        status: [], start: [], submit: ["task", "specmesh_requirements_sha256"], inspect_task: ["task_id"],
        assign: ["task_id", "expected_revision", "workspace_id", "capability", "device_ids", "peer_tasks", "parent_task"],
        cancel: ["task_id", "expected_revision"], resume: ["task_id", "expected_revision", "prompt"],
        revoke: ["device_id"], recover_expired: [],
        request_reconciliation: ["task_id", "expected_revision", "device_id", "effect_id"],
      });
      id = value.id;
      let result: unknown;
      const key = `device-control-${digest(id)}`;
      if (typeof value.op === "string" && Object.hasOwn(topologyControlFields, value.op)) result = await topologyControl(this.topology?.scheduler, value, key);
      switch (value.op) {
        case "start":
          // The coordinator checks configuration at both authentication boundaries and during Agent calls.
          this.server ??= this.coordinator.listen(this.port);
          result = { endpoint: this.server.url.origin }; break;
        case "status": result = { role: "coordinator", endpoint: this.server?.url.origin ?? null,
          devices: this.devices.map(({ device_id, capabilities, workspace_ids }) => ({ device_id, capabilities, workspace_ids })) }; break;
        case "submit": {
          requireThat(object(value.task) && typeof value.task.chat_id === "string", "invalid_device_task");
          if (value.task.native_session) assertProtocolSchema(object(value.task.native_session) && value.task.native_session.schema_version === "controlmesh.device_native_adoption.v1"
            ? "device-native-adoption.schema.json" : "device-native-session.schema.json", value.task.native_session);
          const adopted = value.specmesh_requirements_sha256 === undefined
            ? unchangedSpecMeshCompletion(value.task as LegacyTask)
            : await adoptSpecMeshCompletion(value.task as LegacyTask, value.specmesh_requirements_sha256, this.specmesh);
          this.assertCurrent(); requireThat(!this.stopped, "device_runtime_stopped"); adopted.assertCurrent();
          result = this.ingress.submit(this.actor, key, adopted.task, { chat_id: value.task.chat_id }); break;
        }
        case "inspect_task": {
          identifier(value.task_id); const snapshot = this.kernel.inspect(this.actor, value.task_id);
          const effects = this.kernel.db.sql.query("SELECT effect_id,episode_id,fence,state FROM effects WHERE task_id=? ORDER BY rowid DESC LIMIT 32").all(value.task_id);
          const last = this.kernel.db.sql.query("SELECT result FROM episodes WHERE task_id=? ORDER BY fence DESC LIMIT 1").get(value.task_id) as { result: string | null } | null;
          result = { ...snapshot, effects, result: last?.result ? JSON.parse(last.result) : null }; break;
        }
        case "assign": {
          identifier(value.task_id); identifier(value.workspace_id); identifier(value.capability);
          requireThat(Array.isArray(value.device_ids) && value.device_ids.every(item => typeof item === "string"), "invalid_assignment_devices");
          requireThat(value.peer_tasks === undefined || Array.isArray(value.peer_tasks), "invalid_assignment_peers");
          this.coordinator.assign(this.actor, key, value.task_id, value.expected_revision as number, {
            workspace_id: value.workspace_id, capability: value.capability, device_ids: value.device_ids as string[], input: {},
            ...(value.peer_tasks === undefined ? {} : { peer_tasks: value.peer_tasks as string[] }),
            ...(value.parent_task === undefined ? {} : { parent_task: value.parent_task as string | null }),
          }); result = { assigned: true }; break;
        }
        case "cancel": identifier(value.task_id); result = this.kernel.cancel(this.actor, key, value.task_id, value.expected_revision as number); break;
        case "resume": identifier(value.task_id); result = this.kernel.resume(this.actor, key, value.task_id, value.expected_revision as number, value.prompt as string); break;
        case "revoke": identifier(value.device_id); result = command(this.kernel.db, this.actor, key, "device.control.revoke", { device_id: value.device_id },
          () => { this.coordinator.revoke(this.actor, value.device_id as string); return { revoked: true }; }); break;
        case "recover_expired": result = command(this.kernel.db, this.actor, key, "device.control.recover_expired", {},
          () => ({ recovered: this.kernel.recoverExpired(this.actor) })); break;
        case "request_reconciliation":
          identifier(value.task_id); identifier(value.device_id); identifier(value.effect_id);
          result = this.coordinator.reconciliation.request({ ...this.actor, device_id: value.device_id }, key,
            value.task_id, value.expected_revision as number, value.effect_id); break;
      }
      return { id, ok: true, result };
    } catch (error) { return failure(id, error); }
  }
}

/** Durable request identity prevents a repeated run command from executing a later task revision. */
export class DeviceWorkerControl implements RuntimeControl {
  private readonly pending = new Map<string, Promise<unknown>>();
  private readonly runningTasks = new Set<string>();
  private stopped = false;
  private scheduler?: DeviceScheduler;
  constructor(private readonly db: RuntimeDatabase, private readonly actor: Principal, private readonly client: DeviceClient,
    private readonly worker: DeviceWorker, private readonly assertCurrent: () => void,
    private readonly interrupt: () => void, private readonly maxParallel = 4, private readonly history?: DeviceHistoryControl) {
    requireThat(Number.isSafeInteger(maxParallel) && maxParallel >= 1 && maxParallel <= 8, "invalid_device_concurrency");
  }
  async stop(): Promise<void> {
    this.stopped = true; this.interrupt(); await Promise.allSettled([...this.pending.values(), this.history?.stop(), this.scheduler?.stop()]);
  }
  attachScheduler(scheduler: DeviceScheduler): void { requireThat(!this.scheduler, "device_scheduler_already_configured"); this.scheduler = scheduler; }
  capacity(): number { return Math.max(0, this.maxParallel - this.pending.size); }
  startDaemon(): void { requireThat(this.scheduler, "device_scheduler_not_configured"); this.scheduler.start(); }
  runScheduled(id: string, job: { task_id: string; revision: number; assignment_digest: string }, admission?: DeviceRunAdmission): Promise<DeviceRunOutcome> {
    const body = { task_id: job.task_id, revision: job.revision, assignment_digest: job.assignment_digest };
    return this.once(id, "run", body, async () => {
      requireThat(!this.stopped && !this.runningTasks.has(job.task_id), "device_task_already_running");
      this.runningTasks.add(job.task_id);
      try { this.assertCurrent(); return await this.worker.run(job.task_id, 10_000, { revision: job.revision, assignment_digest: job.assignment_digest }, admission); }
      finally { this.runningTasks.delete(job.task_id); }
    }, () => {
      if (admission) admission.assertCurrent();
      else if (this.scheduler) requireThat(!this.scheduler.status().lease_current, "device_scheduler_owns_execution");
    }) as Promise<DeviceRunOutcome>;
  }
  private async once(id: string, operation: string, body: Record<string, unknown>, run: () => Promise<unknown>, admit?: () => void): Promise<unknown> {
    const key = `device-control-${digest(id)}`, op = `device.control.${operation}`;
    const saved = commandReceipt(this.db, this.actor, key, op, body);
    if (saved) return saved.value;
    if (this.pending.has(key)) return this.pending.get(key)!;
    // A previous process may have crossed the native effect boundary. Never retry that run implicitly.
    requireThat(this.pending.size < this.maxParallel, "device_worker_backpressure");
    const acquired = this.db.transaction(() => {
      const settled = commandReceipt(this.db, this.actor, key, op, body);
      if (settled) return settled;
      const reserved = this.db.sql.query("SELECT 1 FROM command_reservations WHERE principal=? AND request_id=?").get(this.actor.id, key);
      requireThat(!reserved || operation === "reconcile" || operation === "prepare_adoption", "device_run_outcome_unknown");
      admit?.();
      reserveCommand(this.db, this.actor, key, op, body);
      return null;
    });
    if (acquired) return acquired.value;
    const pending = Promise.resolve().then(run).then(result => command(this.db, this.actor, key, op, body, () => result))
      .finally(() => this.pending.delete(key));
    this.pending.set(key, pending);
    return pending;
  }
  async handle(input: unknown): Promise<Record<string, unknown>> {
    let id: unknown = null;
    try {
      this.assertCurrent(); requireThat(!this.stopped, "device_runtime_stopped");
      const value = request(input, { status: [], assignments: [], inspect_task: ["task_id"], inspect_operation: ["operation_id"],
        run: ["task_id", "expected_revision", "assignment_digest"], reconcile: ["challenge_id"],
        scheduler_status: [], start_scheduler: [], pause_scheduler: [], inspect_scheduled: ["work_id"], retry_scheduled: ["work_id", "expected_attempt"],
        inspect_provider: ["task_id"], retry_provider: ["task_id", "expected_generation"],
        history_search: ["workspace_id", "query"], history_refresh: ["workspace_id"], prepare_adoption: ["task_id", "workspace_id", "capability", "session_id"] });
      id = value.id;
      let result: unknown;
      switch (value.op) {
        case "scheduler_status": requireThat(this.scheduler, "device_scheduler_not_configured"); result = this.scheduler.status(); break;
        case "start_scheduler": requireThat(this.scheduler, "device_scheduler_not_configured"); result = this.scheduler.start(id as string); break;
        case "pause_scheduler": requireThat(this.scheduler, "device_scheduler_not_configured"); result = await this.scheduler.pause(id as string); break;
        case "inspect_scheduled": requireThat(this.scheduler, "device_scheduler_not_configured"); result = this.scheduler.inspect(value.work_id as string); break;
        case "retry_scheduled": requireThat(this.scheduler, "device_scheduler_not_configured"); result = await this.scheduler.retry(id as string, value.work_id as string, value.expected_attempt as number); break;
        case "inspect_provider": identifier(value.task_id); result = await this.worker.readiness(value.task_id); break;
        case "retry_provider":
          requireScope(this.actor, "device:schedule"); identifier(value.task_id);
          requireThat(Number.isSafeInteger(value.expected_generation) && Number(value.expected_generation) >= 1, "invalid_provider_generation");
          result = await this.worker.readiness(value.task_id, { request_id: `device-provider-${digest(id)}`, expected_generation: value.expected_generation as number }); break;
        case "history_refresh": {
          requireScope(this.actor, "history:read");
          requireThat(this.history, "native_history_not_configured"); identifier(value.workspace_id);
          result = await this.history.refresh(value.workspace_id); break;
        }
        case "history_search": {
          requireScope(this.actor, "history:read");
          requireThat(this.history, "native_history_not_configured"); identifier(value.workspace_id);
          requireThat(typeof value.query === "string", "invalid_history_query");
          result = await this.history.search(value.workspace_id, value.query); break;
        }
        case "prepare_adoption": {
          requireScope(this.actor, "history:adopt");
          requireThat(this.history, "native_history_not_configured"); identifier(value.task_id); identifier(value.workspace_id); identifier(value.capability); identifier(value.session_id);
          const selection = { task_id: value.task_id, workspace_id: value.workspace_id, capability: value.capability, session_id: value.session_id };
          result = await this.once(id as string, "prepare_adoption", selection, () => this.history!.prepare(id as string, selection)); break;
        }
        case "status": result = { role: "worker", device_id: this.client.deviceId, active: this.pending.size, max_parallel: this.maxParallel }; break;
        case "assignments": {
          result = await this.client.command("queue", {});
          requireThat(Array.isArray(result) && result.length <= 32, "invalid_device_queue"); break;
        }
        case "inspect_task": identifier(value.task_id); result = await this.client.inspect(value.task_id); break;
        case "inspect_operation": {
          identifier(value.operation_id); const key = `device-control-${digest(value.operation_id)}`;
          const row = this.db.sql.query("SELECT response FROM receipts WHERE principal=? AND request_id=?").get(this.actor.id, key) as { response: string } | null;
          const reserved = this.db.sql.query("SELECT 1 FROM command_reservations WHERE principal=? AND request_id=?").get(this.actor.id, key);
          result = row ? { status: "settled", result: JSON.parse(row.response) } : { status: this.pending.has(key) ? "running" : reserved ? "unknown" : "absent" }; break;
        }
        case "run": {
          identifier(value.task_id);
          requireThat(Number.isSafeInteger(value.expected_revision) && Number(value.expected_revision) >= 0
            && typeof value.assignment_digest === "string" && /^[a-f0-9]{64}$/.test(value.assignment_digest), "invalid_device_run_binding");
          result = await this.runScheduled(id as string, { task_id: value.task_id, revision: value.expected_revision as number, assignment_digest: value.assignment_digest }); break;
        }
        case "reconcile": {
          identifier(value.challenge_id); const challengeId = value.challenge_id;
          result = await this.once(id as string, "reconcile", { challenge_id: challengeId }, () => this.worker.reconcile(challengeId)); break;
        }
      }
      return { id, ok: true, result };
    } catch (error) { return failure(id, error); }
  }
}
