import { afterEach, expect, test } from "bun:test";
import { mkdtempSync, readdirSync, rmSync, writeFileSync, readFileSync, openSync, closeSync, constants } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { request } from "node:http";
import { AgentMailbox, RuntimeDatabase, RuntimeKernel, type Principal, type Lease } from "../src";
import { NativeAgentBroker } from "../src/providers/native-agent-broker";
import { NativeAgentJournal, nativeAgentTools, type NativeAgentToolResult } from "../src/providers/native-agent-journal";
import { prepareNativeAgentConfiguration, nativeAgentScope } from "../src/providers/native-agent-profile";
import { assertReadGrantSnapshot, inspectReadPermissions, readOnlyEnvironment } from "../src/providers/opencode-profile";
import { NativeMcpTestClient, type McpResponse } from "./helpers/native-mcp-client";

const cleanup: (() => void | Promise<void>)[] = [];
afterEach(async () => { for (const close of cleanup.splice(0).reverse()) await close(); });
const actor: Principal = { id: "operator", device_id: "local", origin: "human_request", scopes: ["task:create", "task:read", "task:execute", "task:cancel", "message:read", "message:send", "message:ack"] };
function fixture() {
  const root = mkdtempSync(join(tmpdir(), "cm-native-broker-")); cleanup.push(() => rmSync(root, { recursive: true, force: true }));
  const db = new RuntimeDatabase(":memory:"); cleanup.push(() => db.close());
  const kernel = new RuntimeKernel(db), mailbox = new AgentMailbox(kernel), journal = new NativeAgentJournal(kernel);
  const leases: Record<string, Lease> = {};
  for (const taskId of ["parent", "child"]) {
    kernel.submit(actor, `create-${taskId}`, { task_id: taskId, status: "waiting", chat_id: "test" });
    leases[taskId] = kernel.claim(actor, `claim-${taskId}`, taskId, 1, 30000);
    kernel.start(actor, `start-${taskId}`, leases[taskId]);
  }
  async function start(taskId: string) {
    const profile = prepareNativeAgentConfiguration(join(root, "long-state-path-".repeat(10), taskId), Bun.which("node")!, taskId,
      taskId === "parent" ? ["child"] : ["parent"], taskId === "child" ? "parent" : null);
    const scope = nativeAgentScope(profile, leases[taskId]);
    kernel.dispatchEffect(actor, `dispatch-${taskId}`, leases[taskId], `${taskId}-effect`, {}, { communication: scope });
    const broker = new NativeAgentBroker(kernel, actor, leases[taskId], `${taskId}-effect`, profile, () => {});
    cleanup.push(() => broker.close()); await broker.start();
    const client = new NativeMcpTestClient(broker.command); cleanup.push(() => client.close());
    expect((await client.initialize()).error).toBeUndefined();
    return { broker, client, scope, profile };
  }
  return { root, db, kernel, mailbox, journal, leases, start };
}
function body(response: McpResponse): Record<string, unknown> {
  expect(response.error).toBeUndefined(); expect(response.result?.content).toHaveLength(1);
  return JSON.parse(response.result!.content![0].text);
}

test("actual Node MCP clients exchange a scoped question and answer over long-path Unix sockets", async () => {
  const f = fixture(), parent = await f.start("parent"), child = await f.start("child");
  expect((await parent.client.request("tools/list")).result?.tools?.map(tool => tool.name)).toEqual(["send", "ask_parent", "receive", "answer"]);
  const parentProof: NativeAgentToolResult[] = [], childProof: NativeAgentToolResult[] = [];
  const call = async (client: NativeMcpTestClient, proofs: NativeAgentToolResult[], name: string, input: Record<string, unknown>) => {
    const response = await client.tool(name, input), result = body(response);
    proofs.push({ tool: `controlmesh_${name}`, input, output: response.result!.content![0].text }); return result;
  };
  const question = await call(child.client, childProof, "ask_parent", { request_id: "q", text: "Which gate?" });
  expect(question.ok).toBe(true);
  const received = await call(parent.client, parentProof, "receive", { request_id: "receive", wait_ms: 1000 });
  const message = (received.messages as { message_id: string; origin: string; sender_task: string }[])[0];
  expect(message).toMatchObject({ origin: "agent_message", sender_task: "child" });
  const answer = { request_id: "a", question_id: message.message_id, text: "Gate A" };
  const first = await call(parent.client, parentProof, "answer", answer);
  expect(await call(parent.client, parentProof, "answer", answer)).toEqual(first);
  const reply = await call(child.client, childProof, "receive", { request_id: "receive", wait_ms: 1000 });
  expect(reply.messages).toMatchObject([{ kind: "answer", origin: "agent_message", payload: { text: "Gate A" } }]);
  await parent.broker.close(); await child.broker.close();
  f.db.transaction(() => {
    f.journal.consume(actor, f.leases.parent, "parent-effect", parent.scope, parentProof);
    f.journal.consume(actor, f.leases.child, "child-effect", child.scope, childProof);
  });
  expect(f.mailbox.pendingCount(actor, "parent") + f.mailbox.pendingCount(actor, "child")).toBe(0);
  expect(readdirSync(parent.profile.directory)).toEqual(["client.mjs"]);
  expect((await parent.client.tool("send", { request_id: "late", recipient_task: "child", text: "Must fail" })).error).toBeDefined();
});

test("duplicate in-flight receives share one durable result; closing a broker preserves foreign files", async () => {
  const f = fixture(), parent = await f.start("parent");
  const other = new NativeMcpTestClient(parent.broker.command); cleanup.push(() => other.close()); await other.initialize();
  const args = { request_id: "waiting", wait_ms: 1000 };
  const first = parent.client.tool("receive", args), replay = other.tool("receive", args);
  await new Promise(resolve => setTimeout(resolve, 100));
  f.mailbox.send(actor, "human-note", { recipient_task: "parent", sender_lease: null, kind: "tell", payload: { text: "Arrived while waiting" }, causation_id: null, ttl_ms: 10000 });
  expect(body(await first)).toEqual(body(await replay));
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM native_agent_calls").get()).toEqual({ n: 1 });
  const foreign = join(parent.profile.directory, "unrelated.json"); writeFileSync(foreign, "untouched", { mode: 0o600 });
  await parent.broker.close(); expect(readFileSync(foreign, "utf8")).toBe("untouched");
});

test("the broker rejects wrong credentials, changed clients and cancellation without sending a message", async () => {
  const f = fixture(), parent = await f.start("parent");
  const cfg = JSON.parse(readFileSync(parent.broker.command[2], "utf8"));
  const fd = openSync(dirname(parent.broker.command[2]), constants.O_RDONLY | constants.O_DIRECTORY);
  try {
    const status = await new Promise(resolve => {
      const req = request({ socketPath: join(`/proc/self/fd/${fd}`, cfg.socket_name), method: "POST", path: "/call", headers: { authorization: "Bearer wrong" } }, res => { res.resume(); res.on("end", () => resolve(res.statusCode)); });
      req.end(JSON.stringify({ tool: "controlmesh_send", input: { request_id: "wrong", recipient_task: "child", text: "No" } }));
    });
    expect(status).toBe(409);
  } finally { closeSync(fd); }
  f.kernel.cancel(actor, "cancel", "parent", f.kernel.inspect(actor, "parent").revision);
  expect((await parent.client.tool("send", { request_id: "cancelled", recipient_task: "child", text: "No" })).error).toBeDefined();
  expect(f.mailbox.pendingCount(actor, "child")).toBe(0);
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM native_agent_calls").get()).toEqual({ n: 0 });
  const child = await f.start("child");
  writeFileSync(join(child.profile.directory, "client.mjs"), "changed", { mode: 0o600 });
  expect((await child.client.tool("receive", { request_id: "changed" })).error).toBeDefined();
});

test("communication permissions remain explicit and persisted session rules cannot widen or disable them unnoticed", () => {
  const f = fixture(), env = readOnlyEnvironment({}, "fixture/model", { XDG_DATA_HOME: f.root }, f.root, "issued", [], "task", ["/usr/bin/node", "/fixture/client.mjs", "/fixture/config.json"]);
  const config = JSON.parse(env.OPENCODE_CONFIG_CONTENT);
  expect(Object.keys(config.mcp)).toEqual(["controlmesh"]);
  const rules = [{ permission: "*", pattern: "*", action: "deny" }, ...nativeAgentTools.map(permission => ({ permission, pattern: "*", action: "allow" }))];
  const agent = { name: "issued", mode: "primary", tools: { read: {}, bash: {} }, permission: rules };
  expect(inspectReadPermissions(agent, "issued", f.root, [], [], nativeAgentTools)).not.toBeNull();
  expect(inspectReadPermissions(agent, "issued", f.root, [])).toBeNull();
  expect(inspectReadPermissions(agent, "issued", f.root, [], [{ permission: "controlmesh_send", pattern: "*", action: "deny" }], nativeAgentTools)).toBeNull();
  expect(inspectReadPermissions(agent, "issued", f.root, [], [{ permission: "bash", pattern: "*", action: "allow" }], nativeAgentTools)).toBeNull();
  expect(() => assertReadGrantSnapshot({ schema_version: "controlmesh.tool_grant.v1", tool_allow: ["read"], tool_deny: [], network_policy: "sandbox_default", confirmation_policy: "provider_runtime" }, [], nativeAgentTools)).toThrow("communication_conflicts_task_grant");
  const preflight = readOnlyEnvironment(config, "fixture/model", { XDG_DATA_HOME: f.root }, f.root, "probe", [], "sentinel");
  expect(JSON.parse(preflight.OPENCODE_CONFIG_CONTENT).mcp).toBeUndefined();
});
