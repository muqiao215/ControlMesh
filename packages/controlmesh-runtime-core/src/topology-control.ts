import type { TopologyScheduler } from "./topology-scheduler";
import { identifier, requireThat } from "./value";
export const topologyControlFields: Record<string, readonly string[]> = {
        register_schedule: ["plan"], inspect_schedule: ["root_task_id"],
        activate_schedule: ["root_task_id", "expected_revision"], pause_schedule: ["root_task_id", "expected_revision"],
        reopen_schedule: ["root_task_id", "expected_revision", "task_revision", "topology_revision", "prompt"],
        inspect_schedule_run: ["root_task_id", "execution_id"],
        start_scheduler: [], scheduler_status: [], drain_schedules: [],
        retry_schedule_child: ["root_task_id", "expected_revision", "node_id", "parent_revision", "topology_revision", "child_id", "child_revision", "prompt"],
        answer_schedule: ["root_task_id", "expected_revision", "node_id", "parent_revision", "topology_revision", "input"],
};
/** Shared private operator controls; the caller validates the exact outer request fields. */
export async function topologyControl(scheduler: TopologyScheduler | undefined, request: Record<string, unknown>, id: string): Promise<unknown> {
  requireThat(scheduler, "topology_scheduler_not_configured");
  let result: unknown;
  switch (request.op) {
        case "register_schedule": result = scheduler.register(id, request.plan); break;
        case "inspect_schedule": identifier(request.root_task_id); result = scheduler.inspect(request.root_task_id); break;
        case "activate_schedule": case "pause_schedule": identifier(request.root_task_id);
          result = scheduler.setMode(id, request.root_task_id, request.expected_revision as number, request.op === "activate_schedule" ? "active" : "paused"); break;
        case "reopen_schedule": identifier(request.root_task_id);
          result = scheduler.reopen(id, request.root_task_id, request.expected_revision as number, request.task_revision as number,
            request.topology_revision as number, request.prompt as string); break;
        case "inspect_schedule_run": identifier(request.root_task_id); identifier(request.execution_id);
          result = scheduler.inspectRun(request.root_task_id, request.execution_id); break;
        case "start_scheduler": result = scheduler.start(); break;
        case "scheduler_status": result = scheduler.status(); break;
        case "drain_schedules": await scheduler.drain(); result = scheduler.status(); break;
        case "retry_schedule_child": identifier(request.root_task_id); identifier(request.node_id); identifier(request.child_id);
          result = scheduler.retry(id, request.root_task_id, request.expected_revision as number, request.node_id, request.parent_revision as number,
            request.topology_revision as number, request.child_id, request.child_revision as number, request.prompt as string | undefined); break;
        case "answer_schedule": identifier(request.root_task_id); identifier(request.node_id);
          result = scheduler.answer(id, request.root_task_id, request.expected_revision as number, request.node_id, request.parent_revision as number,
            request.topology_revision as number, request.input as string); break;
    default: requireThat(false, "unknown_topology_control_operation");
  }
  return result;
}
