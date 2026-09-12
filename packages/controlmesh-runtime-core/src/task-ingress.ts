import { decodeTaskCompletion } from "./task-completion";
import { command, requireScope } from "./commands";
import { issueExecutionContext, withExecutionContext, type ExecutionOrigin, type SourceScope } from "./execution-context";
import { issueTaskGrantForSubmit } from "./execution-grants";
import type { Principal, RuntimeKernel, TaskSnapshot } from "./kernel";
import { canonical, digest, legacyTask, requireThat, type LegacyTask } from "./value";

export interface IngressSource {
  command_origin: Principal["origin"];
  origin: ExecutionOrigin;
  source_scope: SourceScope;
  transport: string;
}
export interface SubmissionIdentity {
  source_id?: string;
  chat_id: string;
  topic_id?: string;
  thread_id?: string;
}
export interface SubmissionRestrictions {
  tool_deny?: readonly string[];
  no_network?: boolean;
}

/** A configured ingress has one authenticated source; a message cannot select a stronger channel. */
function validateSource(source: IngressSource): void {
  const { command_origin: actor, origin, source_scope: scope } = source;
  const valid = ["local_foreground", "direct_message", "group_message"].includes(scope) ? actor === "human_request" && origin === "user"
    : scope === "bot_handoff" ? actor === "agent_message" && origin === "interagent"
    : scope === "api" ? actor === "internal" && origin === "api"
    : scope === "cron" ? actor === "schedule" && ["cron", "webhook_cron"].includes(origin)
    : scope === "webhook" ? ["internal", "schedule"].includes(actor) && ["webhook_wake", "webhook_cron"].includes(origin)
    : scope === "heartbeat" ? actor === "schedule" && origin === "heartbeat"
    : scope === "background_task" ? actor === "internal" && origin === "background"
    : scope === "task_result" ? ["internal", "agent_message"].includes(actor) && ["task_result", "task_question"].includes(origin)
    : false;
  requireThat(valid, "ingress_source_not_issued");
}

/** Trusted coordinator entrypoint, not a remote API. Never construct from the task body or conversation history. */
export class TaskIngress {
  private readonly source: Readonly<IngressSource>;
  constructor(private readonly kernel: RuntimeKernel, source: IngressSource, private readonly assertCurrent: () => void) {
    validateSource(source);
    const normalized = issueExecutionContext(source);
    this.source = Object.freeze({ ...source, transport: normalized.transport });
  }

  submit(actor: Principal, requestId: string, task: LegacyTask, identity: SubmissionIdentity, restrictions: SubmissionRestrictions = {}): TaskSnapshot {
    const authorize = () => {
      requireScope(actor, "task:create");
      requireThat(actor.origin === this.source.command_origin, "ingress_principal_origin_mismatch");
      const response: unknown = this.assertCurrent();
      if (response !== undefined) { void Promise.resolve(response).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    };
    authorize();
    legacyTask(task);
    if (decodeTaskCompletion(task.completion_requirements)) requireThat(["claude", "opencode"].includes(String(task.provider)), "completion_provider_unsupported");
    requireThat(!Object.hasOwn(task, "execution_context") && !Object.hasOwn(task, "tool_grant"), "task_body_cannot_issue_authority");
    requireThat(typeof identity.chat_id === "string" && String(task.chat_id) === identity.chat_id, "task_reply_identity_mismatch");
    const context = issueExecutionContext({ ...this.source, source_id: identity.source_id });
    const grant = issueTaskGrantForSubmit({ source_scope: context.source_scope, transport: context.transport,
      requested_tool_deny: restrictions.tool_deny, requested_no_network: restrictions.no_network,
      chat_id: identity.chat_id, topic_id: identity.topic_id, thread_id: identity.thread_id });
    // Bind retries to the authenticated source and requested restrictions, not a freshly generated trace or raw source ID.
    const { trace_id: _newTrace, ...sourceIdentity } = context;
    return command(this.kernel.db, actor, requestId, "ingress.submit", { task, source: sourceIdentity, grant }, () => {
      authorize();
      return withExecutionContext(context, () => {
        const result = this.kernel.submit(actor, `ingress-create-${digest(requestId)}`, { ...task, execution_context: context, tool_grant: grant });
        this.kernel.db.sql.query("INSERT INTO events (task_id,kind,revision,fence,principal,origin,at,payload) VALUES (?,'task.authorization_issued',?,?,?,?,?,?)")
          .run(task.task_id, result.revision, result.fence, actor.id, actor.origin, this.kernel.db.now(), canonical({ context, grant_digest: digest(grant) }));
        return result;
      });
    }, receipt => { authorize(); return receipt; });
  }
}
