import { identifier, object, requireThat, RuntimeConflict, type LegacyTask } from "./value";
import type { LocalTaskRuntime } from "./local-task-runtime";
import type { DeliveryOutbox } from "./delivery-outbox";
import type { TerminalDelivery } from "@controlmesh/protocol";
import type { SubmissionIdentity } from "./task-ingress";
import type { FeishuInboundRuntime } from "./feishu-inbound-runtime";
import type { SpecMeshPort } from "./specmesh-port";

/** Private local control protocol. It never accepts caller-supplied principals, source contexts or grants. */
export class LocalRuntimeControl {
  constructor(private readonly runtime: LocalTaskRuntime, private readonly deliveries?: DeliveryOutbox,
    private readonly submissionIdentity?: (task: LegacyTask) => SubmissionIdentity, private readonly inbound?: FeishuInboundRuntime,
    private readonly specmesh?: SpecMeshPort) {}

  async handle(request: unknown): Promise<Record<string, unknown>> {
    let id: string | null = null;
    try {
      requireThat(object(request), "invalid_local_request"); identifier(request.id); id = request.id;
      const fields: Record<string, readonly string[]> = {
        submit: ["task"], inspect_task: ["task_id"], enqueue: ["task_id", "expected_revision"], inspect_run: ["run_id"],
        resume: ["task_id", "expected_revision", "prompt"], cancel: ["task_id", "expected_revision"], tell: ["task_id", "text"], drain: [],
        inspect_message: ["task_id", "message_id"], mailbox_status: ["task_id"],
        bind_delivery: ["task_id", "expected_revision", "adapter_id", "output_policy"], deliveries: ["task_id"],
        drain_deliveries: [], retry_delivery: ["delivery_id"], reconcile_delivery: ["delivery_id", "remote_message_id"], revoke_delivery: ["task_id"],
        start_inbound: [], inbound_status: [], drain_inbound: [], retry_inbound: ["receipt_id"],
        prepare_handoff: ["task_id"], verify_specmesh: ["task_id"],
      };
      requireThat(typeof request.op === "string" && Object.hasOwn(fields, request.op), "unknown_local_operation");
      requireThat(Object.keys(request).every(key => ["id", "op", ...fields[request.op as string]].includes(key)), "unexpected_local_request_field");
      let result: unknown;
      if (["start_inbound", "inbound_status", "drain_inbound", "retry_inbound"].includes(request.op)) requireThat(this.inbound, "feishu_inbound_not_configured");
      if (["bind_delivery", "deliveries", "drain_deliveries", "retry_delivery", "reconcile_delivery", "revoke_delivery"].includes(request.op))
        requireThat(this.deliveries, "delivery_not_configured");
      switch (request.op) {
        case "prepare_handoff": case "verify_specmesh": {
          requireThat(this.specmesh, "specmesh_not_configured"); identifier(request.task_id);
          const taskId = request.task_id, task = this.runtime.inspectTask(taskId);
          this.specmesh.assertWorkspace(task.task.repo_root);
          const observation = await this.specmesh.inspect(request.op === "prepare_handoff" ? "prepare_handoff" : "verify_closeout", { assertCurrent: () => {
            const current = this.runtime.inspectTask(taskId);
            requireThat(current.revision === task.revision && current.fence === task.fence, "specmesh_task_changed");
          } });
          observation.assertCurrent();
          result = { task_id: taskId, task_revision: task.revision, gate_passed: observation.result.status === "pass",
            snapshot_digest: observation.snapshot_digest, result: observation.result }; break;
        }
        case "start_inbound": result = this.inbound!.start(); break;
        case "inbound_status": result = this.inbound!.status(); break;
        case "drain_inbound": await this.inbound!.drain(); result = this.inbound!.status(); break;
        case "retry_inbound": identifier(request.receipt_id); this.inbound!.retry(id, request.receipt_id); result = { retried: true }; break;
        case "submit": {
          requireThat(object(request.task) && typeof request.task.chat_id === "string", "invalid_local_task");
          const task = request.task as LegacyTask;
          const identity = this.submissionIdentity?.(task) ?? { chat_id: request.task.chat_id };
          requireThat(identity.thread_id === undefined || task.thread_id == null || String(task.thread_id) === identity.thread_id, "task_reply_identity_mismatch");
          result = this.runtime.submit(id, identity.thread_id ? { ...task, thread_id: identity.thread_id } : task, identity); break;
        }
        case "inspect_task": identifier(request.task_id); result = this.runtime.inspectTask(request.task_id); break;
        case "enqueue": identifier(request.task_id); result = this.runtime.enqueue(id, request.task_id, request.expected_revision as number); break;
        case "inspect_run": identifier(request.run_id); result = this.runtime.inspect(request.run_id); break;
        case "resume": identifier(request.task_id); result = this.runtime.resume(id, request.task_id, request.expected_revision as number, request.prompt as string); break;
        case "cancel": identifier(request.task_id); result = this.runtime.cancel(id, request.task_id, request.expected_revision as number); break;
        case "tell": identifier(request.task_id); result = this.runtime.tell(id, request.task_id, request.text as string); break;
        case "inspect_message": identifier(request.task_id); identifier(request.message_id); result = this.runtime.inspectMessage(request.task_id, request.message_id); break;
        case "mailbox_status": identifier(request.task_id); result = this.runtime.mailboxStatus(request.task_id); break;
        case "drain": { await this.runtime.drain(); await this.deliveries?.drain(); const queue = this.runtime.queueStatus();
          result = { drained: queue.queued === 0 && queue.running === 0, ...queue, ...(this.deliveries ? { deliveries: this.deliveries.status() } : {}) }; break; }
        case "bind_delivery": {
          identifier(request.task_id); identifier(request.adapter_id);
          this.deliveries!.bindTask(id, request.task_id, request.expected_revision as number, request.adapter_id,
            request.output_policy as TerminalDelivery["output_policy"] | undefined); result = { bound: true }; break;
        }
        case "deliveries": identifier(request.task_id); result = this.deliveries!.list(request.task_id); break;
        case "drain_deliveries": await this.deliveries!.drain(); result = this.deliveries!.status(); break;
        case "retry_delivery": identifier(request.delivery_id); result = this.deliveries!.retryBlocked(id, request.delivery_id); break;
        case "reconcile_delivery": identifier(request.delivery_id); identifier(request.remote_message_id);
          result = await this.deliveries!.reconcile(request.delivery_id, request.remote_message_id); break;
        case "revoke_delivery": identifier(request.task_id); this.deliveries!.revokeTask(id, request.task_id); result = { revoked: true }; break;
      }
      return { id, ok: true, result };
    } catch (error) {
      return { id, ok: false, error: error instanceof RuntimeConflict ? error.code : "local_runtime_error" };
    }
  }
}
