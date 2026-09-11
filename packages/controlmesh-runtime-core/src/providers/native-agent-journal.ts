import { AgentMailbox, type AgentMessage } from "../mailbox";
import type { RuntimeKernel, Principal, Lease, ReconciliationEvidence } from "../kernel";
import { requireScope } from "../commands";
import { canonical, digest, identifier, object, requireThat, RuntimeConflict } from "../value";
import { nativeMessage } from "./native-mailbox-input";
import { nativeAgentProof } from "./native-agent-proof";
import { assertProtocolSchema } from "@controlmesh/protocol";

export const nativeAgentTools = ["controlmesh_send", "controlmesh_ask_parent", "controlmesh_receive", "controlmesh_answer"] as const;
export interface NativeAgentScope extends Record<string, unknown> {
  schema_version: "controlmesh.native_agent_scope.v1";
  task_id: string;
  episode_id: string;
  fence: number;
  peer_tasks: string[];
  parent_task: string | null;
  client_digest: string;
}
export interface NativeAgentToolResult { tool: string; input: Record<string, unknown>; output: string }
interface CallRow { call_id: string; effect_id: string; request_id: string; tool: string; input: string; scope_digest: string; state: "pending" | "done"; response: string | null }

export function decodeNativeAgentScope(value: unknown): NativeAgentScope {
  requireThat(object(value) && value.schema_version === "controlmesh.native_agent_scope.v1", "invalid_native_agent_scope");
  requireThat(Object.keys(value).every(key => ["schema_version", "task_id", "episode_id", "fence", "peer_tasks", "parent_task", "client_digest"].includes(key)), "invalid_native_agent_scope");
  identifier(value.task_id); identifier(value.episode_id);
  requireThat(Number.isSafeInteger(value.fence) && Number(value.fence) > 0 && Array.isArray(value.peer_tasks) && value.peer_tasks.length <= 16,
    "invalid_native_agent_scope");
  for (const peer of value.peer_tasks) { identifier(peer); requireThat(peer !== value.task_id, "native_agent_self_peer"); }
  requireThat(new Set(value.peer_tasks).size === value.peer_tasks.length, "invalid_native_agent_scope");
  if (value.parent_task !== null) { identifier(value.parent_task); requireThat(value.peer_tasks.includes(value.parent_task), "native_parent_not_authorized"); }
  requireThat(typeof value.client_digest === "string" && /^[a-f0-9]{64}$/.test(value.client_digest), "invalid_native_agent_scope");
  return value as NativeAgentScope;
}

/** Durable native tool calls; the authenticated broker supplies a fixed task/episode scope. */
export class NativeAgentJournal {
  private readonly mailbox: AgentMailbox;
  constructor(private readonly kernel: RuntimeKernel) { this.mailbox = new AgentMailbox(kernel); }
  private actor(actor: Principal): Principal { return { ...actor, origin: "agent_message" }; }

  assertExecution(actor: Principal, lease: Lease, effectId: string, scope: NativeAgentScope): void {
    this.kernel.withLease(actor, lease, () => {
      requireThat(scope.task_id === lease.task_id && scope.episode_id === lease.episode_id && scope.fence === lease.fence, "native_agent_scope_changed");
      this.assertManifest(effectId, scope, "dispatched");
    });
  }
  private assertManifest(effectId: string, scope: NativeAgentScope, state: "dispatched" | "unknown"): void {
    decodeNativeAgentScope(scope);
    const row = this.kernel.db.sql.query("SELECT e.state,m.payload,m.digest FROM effects e JOIN execution_manifests m ON m.effect_id=e.effect_id WHERE e.effect_id=? AND e.task_id=? AND e.episode_id=? AND e.fence=?")
      .get(effectId, scope.task_id, scope.episode_id, scope.fence) as { state: string; payload: string; digest: string } | null;
    requireThat(row && row.state === state, "native_agent_effect_unavailable");
    const manifest = JSON.parse(row.payload);
    requireThat(digest(manifest) === row.digest && digest(manifest.communication) === digest(scope), "native_agent_manifest_changed");
  }

  begin(actor: Principal, lease: Lease, effectId: string, scope: NativeAgentScope, tool: string, input: Record<string, unknown>): { call_id: string; response: Record<string, unknown> | null } {
    requireScope(actor, "message:send"); requireScope(actor, "message:read"); requireScope(actor, "message:ack");
    const requestId = input.request_id;
    identifier(requestId);
    requireThat((nativeAgentTools as readonly string[]).includes(tool) && Buffer.byteLength(canonical(input)) <= 16384, "invalid_native_agent_call");
    return this.kernel.withLease(actor, lease, () => {
      this.assertExecution(actor, lease, effectId, scope);
      const callId = digest([effectId, requestId]);
      const prior = this.kernel.db.sql.query("SELECT * FROM native_agent_calls WHERE call_id=?").get(callId) as CallRow | null;
      if (prior) {
        requireThat(prior.tool === tool && prior.input === canonical(input) && prior.scope_digest === digest(scope), "idempotency_conflict");
        requireThat(prior.state === "done" && prior.response, "native_agent_call_unresolved");
        return { call_id: callId, response: JSON.parse(prior.response) };
      }
      const count = this.kernel.db.sql.query("SELECT COUNT(*) AS n FROM native_agent_calls WHERE effect_id=?").get(effectId) as { n: number };
      requireThat(count.n < 32, "native_agent_call_budget_exhausted");
      this.kernel.db.sql.query("INSERT INTO native_agent_calls (call_id,effect_id,request_id,tool,input,scope_digest,state) VALUES (?,?,?,?,?,?,'pending')")
        .run(callId, effectId, requestId, tool, canonical(input), digest(scope));
      return { call_id: callId, response: null };
    });
  }

  available(actor: Principal, lease: Lease): boolean { return this.mailbox.availableForNativeTool(actor, lease, 1).length > 0; }

  finish(actor: Principal, lease: Lease, effectId: string, scope: NativeAgentScope, callId: string): Record<string, unknown> {
    requireScope(actor, "message:send"); requireScope(actor, "message:read"); requireScope(actor, "message:ack");
    return this.kernel.withLease(actor, lease, () => {
      this.assertExecution(actor, lease, effectId, scope);
      const call = this.kernel.db.sql.query("SELECT * FROM native_agent_calls WHERE call_id=? AND effect_id=?").get(callId, effectId) as CallRow | null;
      requireThat(call && call.scope_digest === digest(scope), "native_agent_call_unavailable");
      if (call.state === "done") return JSON.parse(call.response!);
      let response: Record<string, unknown>;
      try {
        response = this.kernel.db.transaction(() => this.apply(this.actor(actor), lease, scope, call, JSON.parse(call.input)));
      } catch (error) {
        response = { ok: false, call_id: callId, error: error instanceof RuntimeConflict ? error.code : "native_agent_operation_failed" };
      }
      requireThat(Buffer.byteLength(canonical(response)) <= 16384, "native_agent_response_too_large");
      this.kernel.db.sql.query("UPDATE native_agent_calls SET state='done',response=? WHERE call_id=?").run(canonical(response), callId);
      return response;
    });
  }

  private apply(actor: Principal, lease: Lease, scope: NativeAgentScope, call: CallRow, input: Record<string, unknown>): Record<string, unknown> {
    const suffix = call.tool.slice("controlmesh_".length);
    const fields: Record<string, string[]> = { send: ["recipient_task", "text", "causation_id"], ask_parent: ["text"], answer: ["question_id", "text"], receive: ["wait_ms"] };
    requireThat(Object.keys(input).every(key => key === "request_id" || fields[suffix].includes(key)), "unexpected_native_agent_argument");
    if (suffix === "receive") {
      requireThat(input.wait_ms === undefined || (Number.isSafeInteger(input.wait_ms) && Number(input.wait_ms) >= 0 && Number(input.wait_ms) <= 10000), "invalid_native_receive_wait");
      const messages: AgentMessage[] = [];
      for (const pending of this.mailbox.availableForNativeTool(actor, lease)) {
        const message = nativeMessage(pending);
        if (Buffer.byteLength(canonical({ ok: true, call_id: call.call_id, messages: [...messages, message] })) > 16384) {
          requireThat(messages.length > 0, "native_agent_message_too_large"); break;
        }
        this.mailbox.acknowledge(actor, `native-tool-receive-${digest([call.call_id, message.message_id])}`, lease, message.message_id, "received", null);
        this.kernel.db.sql.query("INSERT INTO native_agent_deliveries VALUES (?,?,?)").run(message.message_id, call.call_id, digest(message));
        messages.push(message);
      }
      return { ok: true, call_id: call.call_id, messages };
    }
    requireThat(typeof input.text === "string" && input.text.trim().length > 0 && Buffer.byteLength(input.text) <= 4096, "invalid_native_agent_text");
    let recipient = suffix === "ask_parent" ? scope.parent_task : input.recipient_task;
    let cause = input.causation_id ?? null;
    if (suffix === "answer") {
      identifier(input.question_id);
      const question = this.mailbox.inspect(actor, lease.task_id, input.question_id);
      requireThat(question.kind === "ask_parent" && question.sender_task && ["received", "consumed"].includes(question.status), "native_question_not_received");
      recipient = question.sender_task; cause = question.message_id;
    }
    identifier(recipient); requireThat(scope.peer_tasks.includes(recipient), "peer_not_authorized");
    const sent = this.mailbox.send(actor, `native-tool-send-${call.call_id}`, { recipient_task: recipient, sender_lease: lease,
      kind: suffix === "ask_parent" ? "ask_parent" : suffix === "answer" ? "answer" : "tell",
      payload: { text: input.text }, causation_id: cause as string | null, ttl_ms: 300000 });
    return { ok: true, call_id: call.call_id, message: sent };
  }

  verify(effectId: string, scope: NativeAgentScope, native: readonly NativeAgentToolResult[]): Record<string, unknown> {
    const calls = this.kernel.db.sql.query("SELECT * FROM native_agent_calls WHERE effect_id=? ORDER BY seq").all(effectId) as CallRow[];
    requireThat(calls.length <= 32 && calls.every(call => call.state === "done" && call.response && call.scope_digest === digest(scope)), "native_agent_calls_unresolved");
    const observed = native.filter(call => call.tool.startsWith("controlmesh_"));
    const seen = new Set<string>();
    for (const actual of observed) {
      const saved = calls.find(call => call.tool === actual.tool && call.input === canonical(actual.input));
      requireThat(saved && saved.response === actual.output, "native_agent_call_unproven"); seen.add(saved.call_id);
    }
    requireThat(calls.every(call => seen.has(call.call_id)), "native_agent_call_unobserved");
    return { calls_digest: digest(calls.map(call => ({ call_id: call.call_id, tool: call.tool, input: JSON.parse(call.input), response: JSON.parse(call.response!) }))), call_ids: calls.map(call => call.call_id) };
  }

  /** Receipts are derived from verified native parts on the authenticated executing device. */
  verifyDevice(effectId: string, scope: NativeAgentScope, proof: unknown): void {
    assertProtocolSchema("native-agent-proof.schema.json", proof);
    const calls = this.kernel.db.sql.query("SELECT * FROM native_agent_calls WHERE effect_id=? ORDER BY seq").all(effectId) as CallRow[];
    requireThat(calls.length <= 32 && calls.every(call => call.state === "done" && call.response && call.scope_digest === digest(scope)), "native_agent_calls_unresolved");
    const expected = nativeAgentProof(effectId, calls.map(call => ({ tool: call.tool, input: JSON.parse(call.input), output: call.response! })));
    requireThat(digest(proof) === digest(expected), "native_agent_device_calls_unproven");
  }

  consumeDevice(actor: Principal, lease: Lease, effectId: string, scope: NativeAgentScope, proof: unknown): void {
    requireThat(this.kernel.db.sql.inTransaction, "native_agent_transaction_required");
    this.kernel.withLease(actor, lease, () => {
      this.assertExecution(actor, lease, effectId, scope); this.verifyDevice(effectId, scope, proof);
      this.consumeVerifiedRows(actor, effectId, scope, proof);
    });
  }

  reconcileDevice(actor: Principal, original: ReconciliationEvidence, scope: NativeAgentScope, proof: unknown): void {
    requireThat(this.kernel.db.sql.inTransaction, "native_agent_transaction_required");
    const current = this.kernel.inspectReconciliation(actor, original.task.task.task_id, original.task.revision, original.effect_id);
    requireThat(current.manifest_digest === original.manifest_digest && current.observation_digest === original.observation_digest, "reconciliation_evidence_changed");
    this.assertManifest(current.effect_id, scope, "unknown"); this.verifyDevice(current.effect_id, scope, proof);
    this.consumeVerifiedRows(actor, current.effect_id, scope, proof);
  }

  consume(actor: Principal, lease: Lease, effectId: string, scope: NativeAgentScope, native: readonly NativeAgentToolResult[]): void {
    requireThat(this.kernel.db.sql.inTransaction, "native_agent_transaction_required");
    this.kernel.withLease(actor, lease, () => { this.assertExecution(actor, lease, effectId, scope); this.consumeRows(actor, effectId, scope, native); });
  }
  reconcile(actor: Principal, original: ReconciliationEvidence, scope: NativeAgentScope, native: readonly NativeAgentToolResult[]): void {
    requireThat(this.kernel.db.sql.inTransaction, "native_agent_transaction_required");
    const current = this.kernel.inspectReconciliation(actor, original.task.task.task_id, original.task.revision, original.effect_id);
    requireThat(current.manifest_digest === original.manifest_digest && current.observation_digest === original.observation_digest, "reconciliation_evidence_changed");
    this.assertManifest(current.effect_id, scope, "unknown"); this.consumeRows(actor, current.effect_id, scope, native);
  }
  private consumeRows(actor: Principal, effectId: string, scope: NativeAgentScope, native: readonly NativeAgentToolResult[]): void {
    const proof = this.verify(effectId, scope, native);
    this.consumeVerifiedRows(actor, effectId, scope, proof);
  }
  private consumeVerifiedRows(actor: Principal, effectId: string, scope: NativeAgentScope, proof: unknown): void {
    requireScope(actor, "message:ack");
    const rows = this.kernel.db.sql.query("SELECT d.*,m.receipt_episode,m.receipt_fence FROM native_agent_deliveries d JOIN native_agent_calls c ON c.call_id=d.call_id JOIN messages m ON m.message_id=d.message_id WHERE c.effect_id=? ORDER BY m.sequence")
      .all(effectId) as { message_id: string; message_digest: string; receipt_episode: string; receipt_fence: number }[];
    for (const row of rows) {
      const current = this.mailbox.inspect(actor, scope.task_id, row.message_id);
      requireThat(current.status === "received" && digest(nativeMessage(current)) === row.message_digest
        && row.receipt_episode === scope.episode_id && row.receipt_fence === scope.fence, "native_agent_message_changed");
      const gap = this.kernel.db.sql.query("SELECT 1 FROM messages WHERE recipient_task=? AND sequence<? AND status IN ('pending','received') LIMIT 1").get(scope.task_id, current.sequence);
      requireThat(!gap, "message_sequence_gap");
      this.kernel.db.sql.query("UPDATE messages SET status='consumed',consumed_evidence=? WHERE message_id=?")
        .run(`native-agent:${digest({ effectId, proof })}`, row.message_id);
    }
  }
}
