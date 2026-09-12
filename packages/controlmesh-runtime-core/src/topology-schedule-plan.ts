import { DirectorPolicy, type DirectorLimits } from "./team-director";
import { canonical, identifier, object, requireThat } from "./value";

export interface ScheduleRole { role: string; task_id: string; resume_prompt: string; aggregate: boolean }
export interface ScheduleNode {
  task_id: string; topology: "pipeline" | "fanout_merge" | "director_worker" | "debate_judge";
  roles: ScheduleRole[]; worker_roles: string[]; controller_role: string;
  max_repair_cycles: number; max_parent_interruptions: number; round_limit: number;
  director_limits?: DirectorLimits;
}
export interface TopologySchedulePlan {
  schema_version: "controlmesh.topology_schedule.v1"; root_task_id: string; nodes: ScheduleNode[];
}
function fields(value: unknown, allowed: string[]): asserts value is Record<string, unknown> {
  requireThat(object(value) && Object.keys(value).every(key => allowed.includes(key)), "invalid_topology_schedule_plan");
}
function role(value: unknown): asserts value is string {
  requireThat(typeof value === "string" && value.length > 0 && value === value.trim() && value.length <= 128, "invalid_topology_schedule_role");
}
function bound(value: unknown, fallback: number, min = 0, max = 100): number {
  const result = value === undefined ? fallback : value;
  requireThat(Number.isSafeInteger(result) && Number(result) >= min && Number(result) <= max, "invalid_topology_schedule_limit");
  return Number(result);
}
/** Closed finite graph of already-submitted tasks. Model decisions cannot add identities or grants. */
export function decodeTopologySchedulePlan(value: unknown, parallelism: number): TopologySchedulePlan {
  fields(value, ["schema_version", "root_task_id", "nodes"]);
  requireThat(value.schema_version === "controlmesh.topology_schedule.v1", "unsupported_topology_schedule_plan"); identifier(value.root_task_id);
  requireThat(Array.isArray(value.nodes) && value.nodes.length >= 1 && value.nodes.length <= 32 && Buffer.byteLength(canonical(value)) <= 60000, "invalid_topology_schedule_plan");
  const nodes: ScheduleNode[] = value.nodes.map(raw => {
    fields(raw, ["task_id", "topology", "roles", "worker_roles", "controller_role", "max_repair_cycles", "max_parent_interruptions", "round_limit", "director_limits"]);
    identifier(raw.task_id); role(raw.controller_role);
    requireThat(["pipeline", "fanout_merge", "director_worker", "debate_judge"].includes(String(raw.topology)), "invalid_topology_schedule_kind");
    requireThat(Array.isArray(raw.roles) && raw.roles.length >= 2 && raw.roles.length <= 16, "invalid_topology_schedule_roles");
    const roles: ScheduleRole[] = raw.roles.map(item => {
      fields(item, ["role", "task_id", "resume_prompt", "aggregate"]); identifier(item.task_id); role(item.role);
      requireThat(typeof item.resume_prompt === "string" && item.resume_prompt.trim().length > 0 && Buffer.byteLength(item.resume_prompt) <= 16000, "invalid_resume_prompt");
      requireThat(item.aggregate === undefined || typeof item.aggregate === "boolean", "invalid_topology_schedule_role");
      return { task_id: item.task_id, role: item.role, resume_prompt: item.resume_prompt, aggregate: item.aggregate === true };
    });
    requireThat(new Set(roles.map(item => item.role)).size === roles.length && new Set(roles.map(item => item.task_id)).size === roles.length, "duplicate_topology_schedule_role");
    requireThat(Array.isArray(raw.worker_roles) && raw.worker_roles.length > 0 && raw.worker_roles.length < roles.length, "invalid_topology_schedule_workers");
    raw.worker_roles.forEach(role); const workers = raw.worker_roles as string[];
    requireThat(new Set(workers).size === workers.length && !workers.includes(raw.controller_role)
      && roles.length === workers.length + 1 && workers.every(name => roles.some(item => item.role === name))
      && roles.some(item => item.role === raw.controller_role && !item.aggregate), "invalid_topology_schedule_workers");
    if (raw.topology === "pipeline") requireThat(workers.length === 1, "pipeline_worker_count");
    if (raw.topology === "debate_judge") requireThat(workers.length === 2 && parallelism >= 2, "judge_two_candidates_required");
    if (raw.topology !== "director_worker") requireThat(workers.length <= parallelism, "topology_schedule_parallel_limit");
    const repairs = bound(raw.max_repair_cycles, 1), interruptions = bound(raw.max_parent_interruptions, 1), rounds = bound(raw.round_limit, 3, 1);
    let limits: DirectorLimits | undefined;
    if (raw.topology === "director_worker") {
      const supplied = raw.director_limits ?? {};
      fields(supplied, ["max_rounds", "max_parent_interruptions", "max_repair_cycles_per_run", "max_parallel_workers_per_round", "max_total_worker_dispatches"]);
      limits = { ...new DirectorPolicy(parallelism, {
        max_rounds: bound(supplied.max_rounds, rounds, 1), max_parent_interruptions: bound(supplied.max_parent_interruptions, interruptions),
        max_repair_cycles_per_run: bound(supplied.max_repair_cycles_per_run, repairs),
        max_parallel_workers_per_round: bound(supplied.max_parallel_workers_per_round, Math.min(workers.length, parallelism), 1, parallelism),
        max_total_worker_dispatches: bound(supplied.max_total_worker_dispatches, rounds * Math.min(workers.length, parallelism), 1, 1600),
      }).limits };
    } else requireThat(raw.director_limits === undefined, "unexpected_director_limits");
    return { task_id: raw.task_id, topology: raw.topology as ScheduleNode["topology"], roles, worker_roles: workers, controller_role: raw.controller_role,
      max_repair_cycles: repairs, max_parent_interruptions: interruptions, round_limit: rounds, ...(limits ? { director_limits: limits } : {}) };
  });
  const byId = new Map(nodes.map(node => [node.task_id, node]));
  requireThat(byId.size === nodes.length && byId.has(value.root_task_id), "invalid_topology_schedule_root");
  const incoming = new Map<string, number>(), native = new Set<string>();
  for (const node of nodes) for (const item of node.roles) {
    if (item.aggregate) {
      requireThat(byId.has(item.task_id), "aggregate_schedule_node_missing");
      incoming.set(item.task_id, (incoming.get(item.task_id) ?? 0) + 1);
    } else {
      requireThat(!byId.has(item.task_id) && !native.has(item.task_id), "topology_schedule_task_reused"); native.add(item.task_id);
    }
  }
  requireThat(nodes.length + native.size <= 128 && !incoming.has(value.root_task_id)
    && nodes.every(node => node.task_id === value.root_task_id || incoming.get(node.task_id) === 1), "invalid_topology_schedule_tree");
  const ordered: ScheduleNode[] = [], visited = new Set<string>();
  const visit = (id: string, depth: number) => {
    requireThat(depth < 31 && !visited.has(id), "topology_cycle_or_depth_limit"); visited.add(id);
    const node = byId.get(id)!; ordered.push(node);
    for (const item of node.roles) if (item.aggregate) visit(item.task_id, depth + 1);
  };
  visit(value.root_task_id, 0); requireThat(visited.size === nodes.length, "unreachable_topology_schedule_node");
  return { schema_version: "controlmesh.topology_schedule.v1", root_task_id: value.root_task_id, nodes: ordered };
}
