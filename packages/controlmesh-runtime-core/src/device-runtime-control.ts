import type { DeviceClient } from "./device-client";
import type { DeviceCoordinator, DeviceRegistration } from "./device-coordinator";
import type { DeviceWorker } from "./device-worker";
import type { RuntimeDatabase } from "./database";
import type { RuntimeKernel, Principal } from "./kernel";
import { TaskIngress } from "./task-ingress";
import { command, commandReceipt, reserveCommand } from "./commands";
import { digest, identifier, object, requireThat, RuntimeConflict, type LegacyTask } from "./value";

export interface RuntimeControl { handle(request: unknown): Promise<Record<string, unknown>> }

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
  constructor(private readonly kernel: RuntimeKernel, private readonly actor: Principal,
    private readonly coordinator: DeviceCoordinator, private readonly devices: readonly DeviceRegistration[],
    private readonly assertCurrent: () => void, private readonly port = 0) {
    this.ingress = new TaskIngress(kernel, { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: "cm-device" }, assertCurrent);
  }
  async stop(): Promise<void> { this.stopped = true; await this.server?.stop(true); this.server = undefined; }
  async handle(input: unknown): Promise<Record<string, unknown>> {
    let id: unknown = null;
    try {
      this.assertCurrent(); requireThat(!this.stopped, "device_runtime_stopped");
      const value = request(input, {
        status: [], start: [], submit: ["task"], inspect_task: ["task_id"],
        assign: ["task_id", "expected_revision", "workspace_id", "capability", "device_ids", "peer_tasks", "parent_task"],
        cancel: ["task_id", "expected_revision"], resume: ["task_id", "expected_revision", "prompt"],
        revoke: ["device_id"], recover_expired: [],
        request_reconciliation: ["task_id", "expected_revision", "device_id", "effect_id"],
      });
      id = value.id;
      let result: unknown;
      const key = `device-control-${digest(id)}`;
      switch (value.op) {
        case "start":
          // The coordinator checks configuration at both authentication boundaries and during Agent calls.
          this.server ??= this.coordinator.listen(this.port);
          result = { endpoint: this.server.url.origin }; break;
        case "status": result = { role: "coordinator", endpoint: this.server?.url.origin ?? null,
          devices: this.devices.map(({ device_id, capabilities, workspace_ids }) => ({ device_id, capabilities, workspace_ids })) }; break;
        case "submit": {
          requireThat(object(value.task) && typeof value.task.chat_id === "string", "invalid_device_task");
          result = this.ingress.submit(this.actor, key, value.task as LegacyTask, { chat_id: value.task.chat_id }); break;
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
  constructor(private readonly db: RuntimeDatabase, private readonly actor: Principal, private readonly client: DeviceClient,
    private readonly worker: DeviceWorker, private readonly assertCurrent: () => void,
    private readonly interrupt: () => void, private readonly maxParallel = 4) {
    requireThat(Number.isSafeInteger(maxParallel) && maxParallel >= 1 && maxParallel <= 8, "invalid_device_concurrency");
  }
  async stop(): Promise<void> {
    this.stopped = true; this.interrupt(); await Promise.allSettled(this.pending.values());
  }
  private async once(id: string, operation: string, body: Record<string, unknown>, run: () => Promise<unknown>): Promise<unknown> {
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
      requireThat(!reserved || operation === "reconcile", "device_run_outcome_unknown");
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
        run: ["task_id", "expected_revision", "assignment_digest"], reconcile: ["challenge_id"] });
      id = value.id;
      let result: unknown;
      switch (value.op) {
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
          const taskId = value.task_id, body = { task_id: taskId, revision: value.expected_revision, assignment_digest: value.assignment_digest };
          result = await this.once(id as string, "run", body, async () => {
            requireThat(!this.stopped && !this.runningTasks.has(taskId), "device_task_already_running");
            this.runningTasks.add(taskId);
            try { this.assertCurrent(); return await this.worker.run(taskId, 10_000, { revision: body.revision as number, assignment_digest: body.assignment_digest as string }); }
            finally { this.runningTasks.delete(taskId); }
          }); break;
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
