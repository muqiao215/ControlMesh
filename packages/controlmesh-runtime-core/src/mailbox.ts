import { randomUUID } from "node:crypto";
import { assertProtocolSchema, type AgentMailboxMessage } from "@controlmesh/protocol";
import { command, requireScope } from "./commands";
import { RuntimeKernel, type Lease, type Principal } from "./kernel";
import { canonical, identifier, requireThat, terminal } from "./value";

export interface SendMessage {
  recipient_task: string;
  sender_lease: Lease | null;
  kind: "tell" | "ask_parent" | "answer" | "handoff";
  payload: Record<string, unknown>;
  causation_id: string | null;
  ttl_ms: number;
}
export type AgentMessage = AgentMailboxMessage;
interface MessageRow extends Omit<AgentMessage, "payload" | "schema_version"> {
  payload: string; receipt_episode: string | null; receipt_fence: number | null;
}

/** Durable exchange; receipt and application are distinct states, neither means task success. */
export class AgentMailbox {
  constructor(private readonly kernel: RuntimeKernel) {}
  private get db() { return this.kernel.db; }

  private view(row: MessageRow): AgentMessage {
    const { receipt_episode: _episode, receipt_fence: _fence, ...message } = row;
    // Explicit selection below prevents internal columns being published after schema changes.
    const output: AgentMessage = { schema_version: "controlmesh.agent_mailbox_message.v1", message_id: message.message_id, recipient_task: message.recipient_task, sender_task: message.sender_task,
      sender_principal: message.sender_principal, sequence: message.sequence, correlation_id: message.correlation_id,
      causation_id: message.causation_id, origin: message.origin, kind: message.kind, remaining_hops: message.remaining_hops,
      created_at: message.created_at, expires_at: message.expires_at, payload: JSON.parse(message.payload), status: message.status };
    assertProtocolSchema<AgentMessage>("agent-mailbox-message.schema.json", output);
    return output;
  }

  private expire(taskId: string) {
    this.db.sql.query("UPDATE messages SET status='expired' WHERE recipient_task=? AND expires_at<=? AND status IN ('pending','received') AND NOT EXISTS (SELECT 1 FROM native_mailbox_deliveries d WHERE d.message_id=messages.message_id)").run(taskId, this.db.now());
  }

  inspect(actor: Principal, taskId: string, messageId: string): AgentMessage {
    requireScope(actor, "message:read"); identifier(messageId); this.kernel.inspect(actor, taskId);
    return this.db.transaction(() => {
      this.expire(taskId);
      const row = this.db.sql.query("SELECT * FROM messages WHERE recipient_task=? AND message_id=?").get(taskId, messageId) as MessageRow | null;
      requireThat(row, "message_unavailable"); return this.view(row);
    });
  }

  pendingCount(actor: Principal, taskId: string): number {
    requireScope(actor, "message:read"); this.kernel.inspect(actor, taskId);
    return this.db.transaction(() => {
      this.expire(taskId);
      return (this.db.sql.query("SELECT COUNT(*) AS n FROM messages WHERE recipient_task=? AND status IN ('pending','received')").get(taskId) as { n: number }).n;
    });
  }

  send(actor: Principal, requestId: string, message: SendMessage): AgentMessage {
    requireScope(actor, "message:send");
    identifier(message.recipient_task);
    requireThat(["tell", "ask_parent", "answer", "handoff"].includes(message.kind), "invalid_message_kind");
    requireThat(Number.isSafeInteger(message.ttl_ms) && message.ttl_ms >= 100 && message.ttl_ms <= 3_600_000, "invalid_message_ttl");
    const payload = canonical(message.payload);
    requireThat(Buffer.byteLength(payload) <= 32_768, "message_too_large");
    const recipient = this.kernel.inspect(actor, message.recipient_task);
    requireThat(!terminal.has(recipient.task.status), "recipient_terminal");
    requireThat(actor.origin !== "agent_message" || message.sender_lease !== null, "agent_message_requires_lease");
    const execute = () => command(this.db, actor, requestId, "message.send", message, () => {
      // Recheck inside the transaction; cancellation can race with the outer authorization read.
      requireThat(!terminal.has(this.kernel.inspect(actor, message.recipient_task).task.status), "recipient_terminal");
      this.expire(message.recipient_task);
      const count = this.db.sql.query("SELECT COUNT(*) AS n FROM messages WHERE recipient_task=? AND status IN ('pending','received')").get(message.recipient_task) as { n: number };
      requireThat(count.n < 128, "mailbox_full");
      let correlation: string = randomUUID();
      let hops = 4;
      if (message.causation_id !== null) {
        identifier(message.causation_id);
        const cause = this.db.sql.query("SELECT * FROM messages WHERE message_id=?").get(message.causation_id) as MessageRow | null;
        requireThat(cause && message.sender_lease && cause.recipient_task === message.sender_lease.task_id, "invalid_message_causation");
        requireThat(cause.expires_at > this.db.now() && cause.status !== "expired", "causation_expired");
        requireThat(cause.remaining_hops > 0, "message_loop_budget_exhausted");
        correlation = cause.correlation_id;
        hops = cause.remaining_hops - 1;
        const fanout = this.db.sql.query("SELECT COUNT(*) AS n FROM messages WHERE causation_id=?").get(message.causation_id) as { n: number };
        const total = this.db.sql.query("SELECT COUNT(*) AS n FROM messages WHERE correlation_id=?").get(correlation) as { n: number };
        requireThat(fanout.n < 8 && total.n < 64, "message_fanout_exhausted");
      } else {
        if (message.sender_lease) {
          // A task may initiate a bounded number of exchanges. Changing episodes cannot reset this budget.
          correlation = `task:${message.sender_lease.task_id}`;
          const roots = this.db.sql.query("SELECT COUNT(*) AS n FROM messages WHERE correlation_id=? AND causation_id IS NULL").get(correlation) as { n: number };
          const total = this.db.sql.query("SELECT COUNT(*) AS n FROM messages WHERE correlation_id=?").get(correlation) as { n: number };
          requireThat(roots.n < 8, "message_initiation_budget_exhausted");
          requireThat(total.n < 64, "message_fanout_exhausted");
        }
      }
      const last = this.db.sql.query("SELECT COALESCE(MAX(sequence),0) AS n FROM messages WHERE recipient_task=?").get(message.recipient_task) as { n: number };
      const id = randomUUID();
      const now = this.db.now();
      this.db.sql.query("INSERT INTO messages (message_id,recipient_task,sender_task,sender_principal,sequence,correlation_id,causation_id,origin,kind,remaining_hops,created_at,expires_at,payload) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)")
        .run(id, message.recipient_task, message.sender_lease?.task_id ?? null, actor.id, last.n + 1, correlation, message.causation_id, actor.origin, message.kind, hops, now, now + message.ttl_ms, payload);
      return this.view(this.db.sql.query("SELECT * FROM messages WHERE message_id=?").get(id) as MessageRow);
    });
    return message.sender_lease ? this.kernel.withLease(actor, message.sender_lease, execute) : execute();
  }

  pending(actor: Principal, proof: Lease, limit = 32): AgentMessage[] {
    requireScope(actor, "message:read");
    requireThat(Number.isSafeInteger(limit) && limit > 0 && limit <= 128, "invalid_message_limit");
    return this.kernel.withLease(actor, proof, () => {
      this.expire(proof.task_id);
      // No client cursor can skip an unconsumed gap. Received items are redelivered after restart.
      const rows = this.db.sql.query("SELECT * FROM messages WHERE recipient_task=? AND status IN ('pending','received') ORDER BY sequence LIMIT ?").all(proof.task_id, limit) as MessageRow[];
      return rows.map(row => this.view(row));
    });
  }

  acknowledge(actor: Principal, requestId: string, proof: Lease, messageId: string, phase: "received" | "consumed", evidence: string | null): AgentMessage {
    requireScope(actor, "message:ack");
    identifier(messageId);
    requireThat(phase === "received" || phase === "consumed", "invalid_ack_phase");
    requireThat(phase !== "consumed" || (typeof evidence === "string" && evidence.trim().length > 0 && evidence.length <= 1024), "application_evidence_required");
    return this.kernel.withLease(actor, proof, () => {
      requireThat(!this.db.sql.query("SELECT 1 FROM native_mailbox_deliveries WHERE message_id=?").get(messageId), "native_delivery_requires_verification");
      return command(this.db, actor, requestId, "message.ack", { proof, messageId, phase, evidence }, () => {
      this.expire(proof.task_id);
      const row = this.db.sql.query("SELECT * FROM messages WHERE message_id=? AND recipient_task=?").get(messageId, proof.task_id) as MessageRow | null;
      requireThat(row && row.status !== "expired", "message_unavailable");
      if (phase === "consumed") {
        requireThat(row.status === "received" && row.receipt_episode === proof.episode_id && row.receipt_fence === proof.fence, "receipt_required_for_current_episode");
        const gap = this.db.sql.query("SELECT 1 FROM messages WHERE recipient_task=? AND sequence<? AND status IN ('pending','received') LIMIT 1").get(proof.task_id, row.sequence);
        requireThat(!gap, "message_sequence_gap");
      } else {
        requireThat(row.status === "pending" || row.status === "received", "message_already_consumed");
      }
      this.db.sql.query("UPDATE messages SET status=?,receipt_episode=?,receipt_fence=?,consumed_evidence=? WHERE message_id=?")
        .run(phase, proof.episode_id, proof.fence, phase === "consumed" ? evidence : null, messageId);
      return this.view(this.db.sql.query("SELECT * FROM messages WHERE message_id=?").get(messageId) as MessageRow);
      });
    });
  }
}
