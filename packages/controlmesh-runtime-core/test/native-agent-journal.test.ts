import { afterEach, expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { AgentMailbox, RuntimeDatabase, RuntimeKernel, type AgentMessage, type Lease, type Principal } from "../src";
import { NativeAgentJournal, type NativeAgentScope, type NativeAgentToolResult } from "../src/providers/native-agent-journal";
import { canonical } from "../src/value";

const databases = new Set<RuntimeDatabase>();
const directories: string[] = [];
const actor: Principal = { id: "owner", device_id: "local", origin: "human_request", scopes: [
  "task:create", "task:read", "task:execute", "task:cancel", "message:send", "message:read", "message:ack",
] };
afterEach(() => {
  for (const db of databases) db.close(); databases.clear();
  for (const directory of directories.splice(0)) rmSync(directory, { recursive: true, force: true });
});

function fixture(persistent = false) {
  let time = 1000;
  const root = persistent ? mkdtempSync(join(tmpdir(), "cm-native-tools-")) : null;
  if (root) directories.push(root);
  const path = root ? join(root, "runtime.sqlite") : ":memory:";
  const db = new RuntimeDatabase(path, () => time); databases.add(db);
  const kernel = new RuntimeKernel(db), mailbox = new AgentMailbox(kernel), journal = new NativeAgentJournal(kernel);
  const scopes: Record<string, NativeAgentScope> = {}, leases: Record<string, Lease> = {};
  for (const task of ["parent", "child", "unrelated"]) {
    kernel.submit(actor, `create-${task}`, { task_id: task, chat_id: "test", status: "waiting" });
    const lease = kernel.claim(actor, `claim-${task}`, task, 1, 30_000); leases[task] = lease;
    kernel.start(actor, `start-${task}`, lease);
    const scope: NativeAgentScope = { schema_version: "controlmesh.native_agent_scope.v1", task_id: task,
      episode_id: lease.episode_id, fence: lease.fence, peer_tasks: task === "parent" ? ["child"] : ["parent"],
      parent_task: task === "child" ? "parent" : null, client_digest: "a".repeat(64) };
    scopes[task] = scope;
    kernel.dispatchEffect(actor, `dispatch-${task}`, lease, `${task}-effect`, {}, { communication: scope });
  }
  const proofs: Record<string, NativeAgentToolResult[]> = { parent: [], child: [], unrelated: [] };
  function call(task: string, suffix: string, input: Record<string, unknown>) {
    const tool = `controlmesh_${suffix}`;
    const begun = journal.begin(actor, leases[task], `${task}-effect`, scopes[task], tool, input);
    const response = begun.response ?? journal.finish(actor, leases[task], `${task}-effect`, scopes[task], begun.call_id);
    proofs[task].push({ tool, input, output: canonical(response) });
    return response;
  }
  return { db, kernel, mailbox, journal, leases, scopes, call, proofs, path, clock: () => time, advance: (ms: number) => { time += ms; } };
}

test("native send is task-scoped, records Agent provenance and reuses an identical request", () => {
  const f = fixture(), input = { request_id: "send", recipient_task: "child", text: "Review current PROJECT.md" };
  const first = f.call("parent", "send", input);
  expect(first.ok).toBe(true);
  expect(f.call("parent", "send", input)).toEqual(first);
  const messages = f.mailbox.pending(actor, f.leases.child);
  expect(messages).toHaveLength(1);
  expect(messages[0]).toMatchObject({ origin: "agent_message", sender_task: "parent", recipient_task: "child", sender_principal: "owner" });
  expect(() => f.call("parent", "send", { ...input, text: "Changed retry" })).toThrow("idempotency_conflict");
  expect(f.call("parent", "send", { ...input, request_id: "other", recipient_task: "unrelated" })).toMatchObject({ ok: false, error: "peer_not_authorized" });
  expect(f.mailbox.pending(actor, f.leases.unrelated)).toEqual([]);
  expect(f.call("parent", "send", { ...input, request_id: "impersonate", origin: "human_request" })).toMatchObject({ ok: false, error: "unexpected_native_agent_argument" });
  expect(() => f.journal.verify("parent-effect", f.scopes.parent, f.proofs.parent)).not.toThrow();
});

test("ask and answer preserve causation; receipt requires matching native tool evidence before consumption", () => {
  const f = fixture();
  const question = f.call("child", "ask_parent", { request_id: "question", text: "Which acceptance gate?" }).message as AgentMessage;
  expect(question.kind).toBe("ask_parent");
  expect(f.call("parent", "answer", { request_id: "too-early", question_id: question.message_id, text: "Gate A" }))
    .toMatchObject({ ok: false, error: "native_question_not_received" });
  const received = f.call("parent", "receive", { request_id: "receive", wait_ms: 0 }).messages as AgentMessage[];
  expect(received.map(message => message.message_id)).toEqual([question.message_id]);
  expect(f.journal.available(actor, f.leases.parent)).toBe(false);
  expect(() => f.mailbox.acknowledge(actor, "bypass", f.leases.parent, question.message_id, "consumed", "claimed"))
    .toThrow("native_delivery_requires_verification");
  const answer = f.call("parent", "answer", { request_id: "answer", question_id: question.message_id, text: "Gate A" }).message as AgentMessage;
  expect(answer).toMatchObject({ kind: "answer", origin: "agent_message", recipient_task: "child", causation_id: question.message_id,
    correlation_id: question.correlation_id, remaining_hops: question.remaining_hops - 1 });
  f.call("child", "receive", { request_id: "reply", wait_ms: 0 });
  expect(() => f.db.transaction(() => f.journal.consume(actor, f.leases.parent, "parent-effect", f.scopes.parent, [])))
    .toThrow("native_agent_call_unobserved");
  expect(f.mailbox.inspect(actor, "parent", question.message_id).status).toBe("received");
  const altered = f.proofs.parent.map(proof => ({ ...proof, output: "fabricated receipt" }));
  expect(() => f.db.transaction(() => f.journal.consume(actor, f.leases.parent, "parent-effect", f.scopes.parent, altered)))
    .toThrow("native_agent_call_unproven");
  for (const task of ["parent", "child"]) {
    f.db.transaction(() => f.journal.consume(actor, f.leases[task], `${task}-effect`, f.scopes[task], f.proofs[task]));
    expect(f.mailbox.pendingCount(actor, task)).toBe(0);
  }
  expect(f.mailbox.inspect(actor, "child", answer.message_id).status).toBe("consumed");
});

test("completed receipts still require current permissions, scope and a live task lease", () => {
  const f = fixture(), input = { request_id: "receive" };
  const response = f.call("parent", "receive", input), id = response.call_id as string;
  const restricted = { ...actor, scopes: actor.scopes.filter(scope => scope !== "message:ack") };
  expect(() => f.journal.finish(restricted, f.leases.parent, "parent-effect", f.scopes.parent, id)).toThrow("scope_denied");
  expect(() => f.journal.begin(actor, f.leases.parent, "parent-effect", { ...f.scopes.parent, peer_tasks: ["unrelated"] }, "controlmesh_receive", input))
    .toThrow("native_agent_manifest_changed");
  expect(() => f.journal.begin(actor, f.leases.parent, "parent-effect", { ...f.scopes.parent, origin: "human_request" }, "controlmesh_receive", input))
    .toThrow("invalid_native_agent_scope");
  const snapshot = f.kernel.inspect(actor, "parent");
  f.kernel.cancel(actor, "cancel", "parent", snapshot.revision);
  expect(() => f.journal.finish(actor, f.leases.parent, "parent-effect", f.scopes.parent, id)).toThrow();
  expect(f.mailbox.pendingCount(actor, "child")).toBe(0);
});

test("lost in-flight call stays unresolved after database reopen; completed call is not sent again", () => {
  const f = fixture(true);
  const sent = f.call("parent", "send", { request_id: "sent", recipient_task: "child", text: "One message" });
  const pending = { request_id: "lost", recipient_task: "child", text: "Not yet applied" };
  f.journal.begin(actor, f.leases.parent, "parent-effect", f.scopes.parent, "controlmesh_send", pending);
  f.db.close(); databases.delete(f.db);
  const db = new RuntimeDatabase(f.path, f.clock); databases.add(db);
  const kernel = new RuntimeKernel(db), journal = new NativeAgentJournal(kernel);
  expect(() => journal.begin(actor, f.leases.parent, "parent-effect", f.scopes.parent, "controlmesh_send", pending))
    .toThrow("native_agent_call_unresolved");
  expect(journal.begin(actor, f.leases.parent, "parent-effect", f.scopes.parent, "controlmesh_send",
    { request_id: "sent", recipient_task: "child", text: "One message" }).response).toEqual(sent);
  expect(new AgentMailbox(kernel).pending(actor, f.leases.child)).toHaveLength(1);
  expect(() => journal.verify("parent-effect", f.scopes.parent, f.proofs.parent)).toThrow("native_agent_calls_unresolved");
});

test("receive is bounded, rolls back an oversized first item and retains an uncertain receipt past TTL", () => {
  const f = fixture();
  const sent = f.mailbox.send(actor, "large", { sender_lease: null, recipient_task: "child", kind: "tell",
    payload: { text: "x".repeat(20_000) }, causation_id: null, ttl_ms: 100 });
  expect(f.call("child", "receive", { request_id: "large" })).toMatchObject({ ok: false, error: "native_agent_message_too_large" });
  expect(f.mailbox.inspect(actor, "child", sent.message_id).status).toBe("pending");
  f.advance(101);
  const small = f.mailbox.send(actor, "small", { sender_lease: null, recipient_task: "child", kind: "tell",
    payload: { text: "Small" }, causation_id: null, ttl_ms: 100 });
  f.call("child", "receive", { request_id: "small" });
  f.advance(101);
  expect(f.mailbox.inspect(actor, "child", small.message_id).status).toBe("received");
  expect(f.journal.available(actor, f.leases.child)).toBe(false);
  f.db.transaction(() => f.journal.consume(actor, f.leases.child, "child-effect", f.scopes.child, f.proofs.child));
  expect(f.mailbox.inspect(actor, "child", small.message_id).status).toBe("consumed");
  for (let index = 0; index < 30; index++) f.call("parent", "receive", { request_id: `poll-${index}` });
  f.call("parent", "receive", { request_id: "poll-30" });
  f.call("parent", "receive", { request_id: "poll-31" });
  expect(() => f.call("parent", "receive", { request_id: "poll-32" })).toThrow("native_agent_call_budget_exhausted");
});

test("schema nine upgrade preserves existing mailbox reservations and their dispatch evidence", () => {
  const f = fixture(true);
  const sent = f.mailbox.send(actor, "queued", { sender_lease: null, recipient_task: "child", kind: "tell", payload: { text: "Reserved" }, causation_id: null, ttl_ms: 100 });
  f.mailbox.acknowledge(actor, "receive", f.leases.child, sent.message_id, "received", null);
  f.db.sql.query("INSERT INTO native_mailbox_deliveries VALUES (?,?,?,?)").run(sent.message_id, "child-effect", "original-message-digest", "original-batch-digest");
  const before = f.db.sql.query("SELECT * FROM execution_manifests ORDER BY effect_id").all();
  f.db.sql.exec("DROP TABLE transport_receipts; DROP TABLE delivery_outbox; DROP TABLE delivery_routes; DROP TABLE native_agent_deliveries; DROP TABLE native_agent_calls; PRAGMA user_version=9");
  f.db.close(); databases.delete(f.db); f.advance(101);
  const db = new RuntimeDatabase(f.path, f.clock); databases.add(db);
  expect(db.sql.query("PRAGMA user_version").get()).toEqual({ user_version: 11 });
  expect(db.sql.query("SELECT * FROM execution_manifests ORDER BY effect_id").all()).toEqual(before);
  expect(db.sql.query("SELECT message_id,delivery_digest FROM native_mailbox_deliveries").all())
    .toEqual([{ message_id: sent.message_id, delivery_digest: "original-batch-digest" }]);
  const mailbox = new AgentMailbox(new RuntimeKernel(db));
  expect(mailbox.inspect(actor, "child", sent.message_id).status).toBe("received");
  expect(mailbox.availableForNativeTool(actor, f.leases.child)).toEqual([]);
});
