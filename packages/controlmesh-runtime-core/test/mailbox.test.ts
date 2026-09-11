import { afterEach, expect, test } from "bun:test";
import { AgentMailbox, RuntimeDatabase, RuntimeKernel, type Principal, type SendMessage } from "../src";

const databases: RuntimeDatabase[] = [];
const actor: Principal = { id: "owner", origin: "human_request", device_id: "local", scopes: ["task:create", "task:read", "task:execute", "task:cancel", "message:send", "message:read", "message:ack"] };
function fixture() {
  let time = 1_000;
  const db = new RuntimeDatabase(":memory:", () => time);
  databases.push(db);
  const kernel = new RuntimeKernel(db);
  for (const id of ["parent", "child"]) kernel.submit(actor, `create-${id}`, { task_id: id, chat_id: "test", status: "waiting" });
  const parent = kernel.claim(actor, "claim-parent", "parent", 1, 30_000);
  const child = kernel.claim(actor, "claim-child", "child", 1, 30_000);
  const mailbox = new AgentMailbox(kernel);
  const message: SendMessage = { recipient_task: "child", sender_lease: null, kind: "tell", payload: { instruction: "synthetic" }, causation_id: null, ttl_ms: 10_000 };
  return { db, kernel, mailbox, parent, child, message, advance(ms: number) { time += ms; } };
}
afterEach(() => { for (const db of databases.splice(0)) db.close(); });

test("duplicate sends have one sequence; received survives reconstruction and differs from consumed", () => {
  const { kernel, mailbox, child, message } = fixture();
  const sent = mailbox.send(actor, "send", message);
  expect(mailbox.send(actor, "send", message)).toEqual(sent);
  expect(mailbox.pending(actor, child)).toHaveLength(1);
  mailbox.acknowledge(actor, "receipt", child, sent.message_id, "received", null);
  const restarted = new AgentMailbox(kernel);
  expect(restarted.pending(actor, child)[0].status).toBe("received");
  expect(() => restarted.acknowledge(actor, "consume", child, sent.message_id, "consumed", null)).toThrow("application_evidence_required");
  restarted.acknowledge(actor, "consume", child, sent.message_id, "consumed", "native-message:synthetic");
  expect(restarted.pending(actor, child)).toEqual([]);
  expect(kernel.inspect(actor, "child").task.status).toBe("running");
});

test("out-of-order application cannot silently skip an unconsumed message", () => {
  const { mailbox, child, message } = fixture();
  const first = mailbox.send(actor, "send1", message);
  const second = mailbox.send(actor, "send2", { ...message, payload: { instruction: "second" } });
  mailbox.acknowledge(actor, "receipt2", child, second.message_id, "received", null);
  expect(() => mailbox.acknowledge(actor, "consume2", child, second.message_id, "consumed", "ref2")).toThrow("message_sequence_gap");
  mailbox.acknowledge(actor, "receipt1", child, first.message_id, "received", null);
  mailbox.acknowledge(actor, "consume1", child, first.message_id, "consumed", "ref1");
  mailbox.acknowledge(actor, "consume2", child, second.message_id, "consumed", "ref2");
  expect(mailbox.pending(actor, child)).toEqual([]);
});

test("provenance is assigned by ingress; loop budget derives from persisted causation", () => {
  const { mailbox, parent, child, message } = fixture();
  let latest = mailbox.send({ ...actor, origin: "schedule" }, "schedule", message);
  expect(latest.origin).toBe("schedule");
  const agent = { ...actor, origin: "agent_message" as const };
  for (let i = 0; i < 4; i++) {
    const sender = i % 2 === 0 ? child : parent;
    latest = mailbox.send(agent, `reply-${i}`, { ...message, sender_lease: sender, recipient_task: i % 2 === 0 ? "parent" : "child", causation_id: latest.message_id });
    expect(latest.origin).toBe("agent_message");
    expect(latest.remaining_hops).toBe(3 - i);
  }
  expect(() => mailbox.send(agent, "infinite", { ...message, sender_lease: child, recipient_task: "parent", causation_id: latest.message_id })).toThrow("message_loop_budget_exhausted");
  expect(() => mailbox.send(agent, "impersonate", message)).toThrow("agent_message_requires_lease");
});

test("queue bounds, expiry and cancellation prevent unbounded or stale delivery", () => {
  const { mailbox, kernel, child, message, advance } = fixture();
  expect(() => mailbox.send(actor, "large", { ...message, payload: { text: "x".repeat(33_000) } })).toThrow("message_too_large");
  for (let i = 0; i < 128; i++) mailbox.send(actor, `send-${i}`, { ...message, ttl_ms: 100 });
  expect(() => mailbox.send(actor, "overflow", message)).toThrow("mailbox_full");
  advance(100);
  expect(mailbox.pending(actor, child)).toEqual([]);
  const next = mailbox.send(actor, "next", message);
  expect(next.sequence).toBe(129);
  const state = kernel.inspect(actor, "child");
  kernel.cancel(actor, "cancel", "child", state.revision);
  expect(() => mailbox.pending(actor, child)).toThrow("task_not_executable");
  expect(() => mailbox.send(actor, "late", message)).toThrow("recipient_terminal");
});

test("reclaimed lease requires a new receipt and cannot accept previous device acknowledgement", () => {
  const { mailbox, kernel, child, message, advance } = fixture();
  const sent = mailbox.send(actor, "send", { ...message, ttl_ms: 60_000 });
  mailbox.acknowledge(actor, "receipt", child, sent.message_id, "received", null);
  advance(30_000);
  const other = { ...actor, device_id: "other" };
  const lease = kernel.claim(other, "reclaim", "child", 2, 30_000);
  expect(() => mailbox.acknowledge(actor, "consume-old", child, sent.message_id, "consumed", "old")).toThrow("stale_fence");
  expect(() => mailbox.acknowledge(other, "consume-new", lease, sent.message_id, "consumed", "new")).toThrow("receipt_required_for_current_episode");
  mailbox.acknowledge(other, "receipt-new", lease, sent.message_id, "received", null);
  mailbox.acknowledge(other, "consume-new", lease, sent.message_id, "consumed", "new");
  expect(mailbox.pending(other, lease)).toEqual([]);
});

test("agent cannot reset its initiation budget by omitting causation", () => {
  const { mailbox, parent, message } = fixture();
  const agent = { ...actor, origin: "agent_message" as const };
  for (let i = 0; i < 8; i++) mailbox.send(agent, `root-${i}`, { ...message, sender_lease: parent });
  expect(() => mailbox.send(agent, "root-reset", { ...message, sender_lease: parent })).toThrow("message_initiation_budget_exhausted");
});
