import { command, requireScope } from "./commands";
import type { Principal, RuntimeKernel, Lease, TaskSnapshot } from "./kernel";
import type { DeviceAssignment, DeviceCoordinator } from "./device-coordinator";
import type { LocalRun } from "./local-task-runtime";
import type { TopologyRuntime } from "./topology-runtime";
import { registerDeviceTopologyOwner, type TopologyExecution } from "./topology-execution";
import { assertTopologyNativeInput } from "./topology-native-input";
import { canonical, digest, identifier, object, requireThat, RuntimeConflict } from "./value";
export type DeviceTopologyRoute = Omit<DeviceAssignment, "input">;
interface Row {
  run_id: string; task_id: string; principal: string; coordinator_device: string; origin: string;
  expected_revision: number; assignment_digest: string; execution_digest: string; profile_digest: string;
  specification: string; lease: string | null;
}
/** Coordinator-side topology execution. Remote workers use their existing authenticated queue and native lifecycle. */
export class DeviceTopologyRuntime implements TopologyRuntime {
  readonly topologySource = "device" as const;
  private readonly routes: Readonly<Record<string, DeviceTopologyRoute>>;
  private readonly binding: string;
  private stopped = false;
  constructor(readonly kernel: RuntimeKernel, private readonly actor: Principal, private readonly coordinator: DeviceCoordinator,
    routes: Readonly<Record<string, DeviceTopologyRoute>>, private readonly authorize: () => void,
    private readonly parallelism = 2, private readonly maxPending = 128) {
    requireThat(coordinator.kernel === kernel && Number.isSafeInteger(parallelism) && parallelism >= 1 && parallelism <= 16
      && Number.isSafeInteger(maxPending) && maxPending >= 1 && maxPending <= 1024, "invalid_device_topology_limits");
    identifier(actor.device_id); this.assertPrincipal(actor); requireScope(actor, "device:assign");
    requireThat(object(routes) && Object.keys(routes).length >= 1 && Object.keys(routes).length <= 128, "invalid_device_topology_routes");
    for (const [id, route] of Object.entries(routes)) {
      identifier(id); requireThat(object(route) && Object.keys(route).every(key => ["workspace_id", "capability", "device_ids", "peer_tasks", "parent_task"].includes(key)), "invalid_device_topology_route");
      identifier(route.workspace_id); identifier(route.capability);
      requireThat(Array.isArray(route.device_ids) && route.device_ids.length > 0 && route.device_ids.length <= 128
        && new Set(route.device_ids).size === route.device_ids.length, "invalid_assignment_devices"); route.device_ids.forEach(identifier);
      requireThat(route.peer_tasks === undefined || (Array.isArray(route.peer_tasks) && route.peer_tasks.length <= 128
        && new Set(route.peer_tasks).size === route.peer_tasks.length && !route.peer_tasks.includes(id)), "invalid_assignment_peers"); route.peer_tasks?.forEach(identifier);
      if (route.parent_task !== undefined && route.parent_task !== null) {
        identifier(route.parent_task); requireThat(route.peer_tasks?.includes(route.parent_task), "native_parent_not_authorized");
      }
    }
    this.routes = structuredClone(routes);
    this.binding = digest({ actor, routes: this.routes, parallelism, maxPending });
    const policyKey = `device-topology:${digest([actor.id, actor.device_id])}`;
    kernel.db.transaction(() => {
      const previous = kernel.db.sql.query("SELECT value FROM meta WHERE key=?").get(policyKey) as { value: string } | null;
      requireThat(!previous || previous.value === this.binding, "device_topology_policy_changed");
      if (!previous) kernel.db.sql.query("INSERT INTO meta VALUES (?,?)").run(policyKey, this.binding);
    });
    registerDeviceTopologyOwner(kernel, { binding: this.binding, read: (actor, id) => this.execution(actor, id), claim: (actor, id, lease) => this.claim(actor, id, lease) });
  }
  private current() {
    requireThat(!this.stopped, "device_topology_stopped"); const result: unknown = this.authorize();
    if (result !== undefined) { void Promise.resolve(result).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
  }
  assertPrincipal(actor: Principal) {
    this.current(); requireThat(actor.id === this.actor.id && actor.device_id === this.actor.device_id && actor.origin === this.actor.origin, "device_topology_principal_mismatch");
    for (const scope of ["task:read", "task:execute", "task:resume", "team:write"]) requireScope(actor, scope);
  }
  private row(id: string): Row {
    identifier(id); const row = this.kernel.db.sql.query("SELECT * FROM topology_device_runs WHERE run_id=? AND principal=? AND coordinator_device=? AND origin=?")
      .get(id, this.actor.id, this.actor.device_id!, this.actor.origin) as Row | null;
    requireThat(row && row.profile_digest === this.binding, "device_topology_run_unavailable"); return row;
  }
  private specification(task: TaskSnapshot): DeviceAssignment {
    const route = Object.hasOwn(this.routes, task.task.task_id) ? this.routes[task.task.task_id] : undefined;
    requireThat(route, "device_topology_route_missing");
    const native = task.task.native_session;
    if (native !== undefined && native !== null) {
      requireThat(object(native) && typeof native.device_id === "string" && route.device_ids.includes(native.device_id), "native_session_device_bound");
      return { ...route, device_ids: [native.device_id], input: {} };
    }
    return { ...route, input: {} };
  }
  enqueue(requestId: string, taskId: string, revision: number): LocalRun {
    this.assertPrincipal(this.actor); const runId = digest([this.actor.id, this.actor.device_id, requestId]);
    command(this.kernel.db, this.actor, requestId, "device.topology.enqueue", { taskId, revision }, () => {
      const task = this.kernel.inspect(this.actor, taskId);
      requireThat(task.revision === revision && task.task.status === "waiting" && !task.active_episode && !task.needs_reconciliation, "task_not_admitted");
      this.kernel.assertNativeTask(this.actor, taskId);
      requireThat(!this.kernel.db.sql.query("SELECT 1 FROM local_runs WHERE task_id=? AND state IN ('queued','running')").get(taskId), "task_already_queued");
      const count = this.queueStatus(); requireThat(count.queued < this.maxPending, "device_topology_queue_full");
      for (const row of this.kernel.db.sql.query("SELECT run_id FROM topology_device_runs WHERE task_id=?").all(taskId) as { run_id: string }[]) {
        const run = this.inspect(row.run_id); requireThat(!["queued", "running"].includes(run.state), "task_already_queued");
      }
      const specification = this.specification(task);
      this.coordinator.assign(this.actor, `topology-device-assign-${digest(requestId)}`, taskId, revision, specification);
      const assigned = this.coordinator.inspectIssued(this.actor, taskId);
      this.kernel.db.sql.query("INSERT INTO topology_device_runs VALUES (?,?,?,?,?,?,?,?,?,?,NULL)")
        .run(runId, taskId, this.actor.id, this.actor.device_id!, this.actor.origin, revision, assigned.assignment_digest,
          assigned.execution_digest, this.binding, canonical(specification));
      return { queued: true };
    });
    return this.inspect(runId);
  }
  resume(requestId: string, taskId: string, revision: number, prompt: string) { this.assertPrincipal(this.actor); return this.kernel.resume(this.actor, requestId, taskId, revision, prompt); }
  parallelLimit() { this.current(); return this.parallelism; }
  queueStatus(): { queued: number; running: number } {
    this.current(); const counts = { queued: 0, running: 0 };
    const rows = this.kernel.db.sql.query("SELECT run_id FROM topology_device_runs WHERE principal=? AND coordinator_device=? AND origin=?")
      .all(this.actor.id, this.actor.device_id!, this.actor.origin) as { run_id: string }[];
    for (const row of rows) { const run = this.inspect(row.run_id); if (run.state === "queued" || run.state === "running") counts[run.state]++; }
    return counts;
  }
  inspect(runId: string): LocalRun { const { lease: _lease, ...view } = this.execution(this.actor, runId); return view; }
  private execution(actor: Principal, runId: string): TopologyExecution {
    this.assertPrincipal(actor); const row = this.row(runId), task = this.kernel.inspect(actor, row.task_id);
    const lease: Lease | null = row.lease ? JSON.parse(row.lease) : null;
    const result = (state: LocalRun["state"], reason: string | null): TopologyExecution => ({ run_id: runId, task_id: row.task_id, state, lease,
      outcome: reason === null ? null : { reason, retry_after: null } });
    if (task.task.status === "cancelled") return result("cancelled", "task_cancelled");
    try {
      const currentRun = this.kernel.db.sql.query("SELECT run_id FROM topology_tasks WHERE child_id=?").get(row.task_id) as { run_id: string } | null;
      if (currentRun?.run_id === runId) assertTopologyNativeInput(this.kernel, row.task_id);
      const current = this.coordinator.inspectIssued(actor, row.task_id, lease?.device_id);
      requireThat(current.assignment_digest === row.assignment_digest && current.execution_digest === row.execution_digest
        && canonical(current.specification) === row.specification, "device_topology_assignment_changed");
    } catch (error) {
      if (!(error instanceof RuntimeConflict)) throw error;
      return result("interrupted", error.code);
    }
    if (task.needs_reconciliation) return result("interrupted", "device_topology_reconciliation_required");
    if (!lease) {
      if (task.revision !== row.expected_revision || task.active_episode || task.task.status !== "waiting") return result("interrupted", "device_topology_execution_changed");
      return result("queued", null);
    }
    const episode = this.kernel.db.sql.query("SELECT state FROM episodes WHERE episode_id=? AND task_id=? AND device_id=? AND fence=?")
      .get(lease.episode_id, row.task_id, lease.device_id, lease.fence) as { state: string } | null;
    requireThat(episode, "device_topology_episode_missing");
    if (["done", "failed"].includes(episode.state) && !task.active_episode && task.task.status === episode.state) return result("completed", episode.state);
    if (["released", "expired"].includes(episode.state) && task.task.status === "waiting") {
      const event = this.kernel.db.sql.query("SELECT payload FROM events WHERE task_id=? AND kind='episode.admission_released' AND json_extract(payload,'$.episode_id')=? ORDER BY seq DESC LIMIT 1")
        .get(row.task_id, lease.episode_id) as { payload: string } | null;
      return result("blocked", event ? (JSON.parse(event.payload) as { reason: string }).reason : "device_topology_admission_expired");
    }
    if (task.active_episode === lease.episode_id && ["leased", "running"].includes(episode.state)) return result("running", null);
    return result("interrupted", "device_topology_execution_changed");
  }
  private claim(actor: Principal, runId: string, lease?: Lease) {
    this.current(); const row = this.row(runId);
    requireThat(this.queueStatus().running < this.parallelism, "device_topology_parallel_limit");
    requireThat(actor.id === this.actor.id && actor.origin === "agent_message" && typeof actor.device_id === "string", "device_topology_worker_required");
    const assigned = this.coordinator.inspectIssued(this.actor, row.task_id, actor.device_id), task = this.kernel.inspect(this.actor, row.task_id);
    requireThat(!row.lease && task.revision === row.expected_revision && assigned.assignment_digest === row.assignment_digest
      && assigned.execution_digest === row.execution_digest, "device_topology_claim_changed");
    if (lease) {
      requireThat(lease.task_id === row.task_id && lease.device_id === actor.device_id, "device_topology_claim_changed");
      this.kernel.db.sql.query("UPDATE topology_device_runs SET lease=? WHERE run_id=? AND lease IS NULL").run(canonical(lease), runId);
    }
  }
  /** Work is performed by independently owned device workers, not by a second local provider loop. */
  async drain() { this.current(); }
  async stop() { this.stopped = true; }
}
