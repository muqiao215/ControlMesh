import { identifier, object, requireThat, RuntimeConflict, type LegacyTask } from "./value";
import type { LocalTaskRuntime } from "./local-task-runtime";

/** Private local control protocol. It never accepts caller-supplied principals, source contexts or grants. */
export class LocalRuntimeControl {
  constructor(private readonly runtime: LocalTaskRuntime) {}

  async handle(request: unknown): Promise<Record<string, unknown>> {
    let id: string | null = null;
    try {
      requireThat(object(request), "invalid_local_request"); identifier(request.id); id = request.id;
      const fields: Record<string, readonly string[]> = {
        submit: ["task"], inspect_task: ["task_id"], enqueue: ["task_id", "expected_revision"], inspect_run: ["run_id"],
        resume: ["task_id", "expected_revision", "prompt"], cancel: ["task_id", "expected_revision"], tell: ["task_id", "text"], drain: [],
        inspect_message: ["task_id", "message_id"], mailbox_status: ["task_id"],
      };
      requireThat(typeof request.op === "string" && Object.hasOwn(fields, request.op), "unknown_local_operation");
      requireThat(Object.keys(request).every(key => ["id", "op", ...fields[request.op as string]].includes(key)), "unexpected_local_request_field");
      let result: unknown;
      switch (request.op) {
        case "submit": {
          requireThat(object(request.task) && typeof request.task.chat_id === "string", "invalid_local_task");
          result = this.runtime.submit(id, request.task as LegacyTask, { chat_id: request.task.chat_id }); break;
        }
        case "inspect_task": identifier(request.task_id); result = this.runtime.inspectTask(request.task_id); break;
        case "enqueue": identifier(request.task_id); result = this.runtime.enqueue(id, request.task_id, request.expected_revision as number); break;
        case "inspect_run": identifier(request.run_id); result = this.runtime.inspect(request.run_id); break;
        case "resume": identifier(request.task_id); result = this.runtime.resume(id, request.task_id, request.expected_revision as number, request.prompt as string); break;
        case "cancel": identifier(request.task_id); result = this.runtime.cancel(id, request.task_id, request.expected_revision as number); break;
        case "tell": identifier(request.task_id); result = this.runtime.tell(id, request.task_id, request.text as string); break;
        case "inspect_message": identifier(request.task_id); identifier(request.message_id); result = this.runtime.inspectMessage(request.task_id, request.message_id); break;
        case "mailbox_status": identifier(request.task_id); result = this.runtime.mailboxStatus(request.task_id); break;
        case "drain": { await this.runtime.drain(); const queue = this.runtime.queueStatus(); result = { drained: queue.queued === 0 && queue.running === 0, ...queue }; break; }
      }
      return { id, ok: true, result };
    } catch (error) {
      return { id, ok: false, error: error instanceof RuntimeConflict ? error.code : "local_runtime_error" };
    }
  }
}
