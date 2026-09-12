import { afterEach, expect, test } from "bun:test";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { claudeControlCommand, observeClaudeControl, type ClaudeControlInput } from "../src/providers/claude-control";
import { ClaudeControlRunner } from "../src/providers/claude-control-runner";
import { ProcessSupervisor } from "../src/process-supervisor";

const roots: string[] = [];
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { force: true, recursive: true }); });
function fixture(mode = "success") {
  const root = mkdtempSync(join(tmpdir(), "cm-claude-control-")); roots.push(root);
  const workspace = join(root, "project"), home = join(root, "home"), config_directory = join(home, "config");
  for (const dir of [workspace, home, config_directory]) mkdirSync(dir, { mode: 0o700 });
  const executable = join(root, "claude");
  writeFileSync(executable, `#!${process.execPath}\nimport ${JSON.stringify(join(import.meta.dir, "helpers/claude-control-native.ts"))};\n`, { mode: 0o700 });
  writeFileSync(join(workspace, "scenario.json"), JSON.stringify({ mode }));
  const input: ClaudeControlInput = { schema_version: "controlmesh.claude_control.v1", executable, workspace,
    session_id: "aaaaaaaa-0000-0000-0000-000000000001", resume: false, model: "selected-model", prompt: "Perform exactly the authorized task.", max_turns: 6,
    workspace_command: ["/usr/bin/node", join(root, "client.mjs"), join(root, "client.json")] };
  const environment = { home, config_directory, credentials: {} };
  const received = () => existsSync(join(workspace, "received.jsonl")) ? readFileSync(join(workspace, "received.jsonl"), "utf8").trim().split("\n").map(line => JSON.parse(line)) : [];
  return { root, workspace, input, environment, received };
}
test("the owned control process admits exactly one input after the dynamic tool table; resume keeps the explicit session", async () => {
  const f = fixture(); f.input.resume = true;
  const outcome = await new ClaudeControlRunner().run(f.input, f.environment, { assertCurrent: () => {} });
  expect(outcome).toMatchObject({ reason: "exited", exit_code: 0, stderr: "" });
  expect(observeClaudeControl(outcome, f.input)).toEqual({ terminal: true, text: "DONE", input_attempted: true, invalid_reason: null, failure: null });
  expect(f.received().map(frame => frame.request?.subtype ?? frame.type)).toEqual(["initialize", "mcp_set_servers", "mcp_status", "user"]);
  expect(f.received().at(-1)).toMatchObject({ session_id: f.input.session_id, message: { role: "user", content: f.input.prompt } });
  const args = JSON.parse(readFileSync(join(f.workspace, "native-arguments.json"), "utf8"));
  expect(args).toContain("--resume"); expect(args).not.toContain("--continue"); expect(args).not.toContain("--no-session-persistence");
  expect(args[args.indexOf("--tools") + 1]).toBe(""); expect(args).not.toContain(f.input.prompt);
});
for (const mode of ["success", "structured-missing", "structured-wrong-role", "builtin"]) test(`native schema mode with dynamic MCP validates ${mode}`, async () => {
  const f = fixture(mode);
  f.input.structured_output = { schema_name: "team-structured-result.schema.json", bindings: { topology: "pipeline", substage: "worker_running", worker_role: "worker" } };
  const command = claudeControlCommand(f.input), schema = JSON.parse(command[command.indexOf("--json-schema") + 1]!);
  expect(schema.properties.worker_role.const).toBe("worker"); expect(schema.additionalProperties).toBe(false);
  const outcome = await new ClaudeControlRunner().run(f.input, f.environment, { assertCurrent: () => {} });
  const observed = observeClaudeControl(outcome, f.input); expect(observed.terminal).toBe(mode === "success");
  if (mode === "success") expect(observed).toMatchObject({ text: "DONE", structured_output: { worker_role: "worker", status: "completed" } });
});
test("native structured-output exhaustion is a task-format limit, not an account quota failure", async () => {
  const f = fixture();
  f.input.structured_output = { schema_name: "team-structured-result.schema.json", bindings: { topology: "pipeline", substage: "worker_running", worker_role: "worker" } };
  const outcome = await new ClaudeControlRunner().run(f.input, f.environment, { assertCurrent: () => {} });
  const rows = outcome.stdout.trim().split("\n").map(line => JSON.parse(line));
  const result = rows.find(row => row.event === "native" && row.row.type === "result").row;
  result.is_error = true; result.subtype = "error_max_structured_output_retries";
  const observed = observeClaudeControl({ ...outcome, stdout: rows.map(row => JSON.stringify(row)).join("\n") + "\n" }, f.input);
  expect(observed).toMatchObject({ terminal: false, failure: null, invalid_reason: "claude_structured_output_limit_exceeded" });
});
test("native API retries stop before another attempt and classify only verified native error fields", async () => {
  for (const [mode, code] of [["quota", "quota_exhausted"], ["rate", "rate_limited"], ["auth", "authentication_failed"], ["unknown", "provider_error"]]) {
    const f = fixture(`api-retry-${mode}`), outcome = await new ClaudeControlRunner().run(f.input, f.environment, { assertCurrent: () => {} });
    expect(outcome.exit_code).toBe(2);
    expect(observeClaudeControl(outcome, f.input)).toMatchObject({ terminal: false, input_attempted: true,
      invalid_reason: "claude_native_api_retry_refused", failure: { code, reset_at: null, retry_after_ms: null } });
    expect(existsSync(join(f.workspace, "api-retried"))).toBe(false);
    const original = outcome.stdout.trim().split("\n").map(line => JSON.parse(line));
    for (const defect of ["foreign-session", "bad-counter", "bad-delay", "wrong-kind", "missing-input", "changed-registration", "trailing-native"]) {
      const rows = structuredClone(original), retry = rows.find(row => row.row?.subtype === "api_retry");
      if (defect === "foreign-session") retry.row.session_id = "foreign";
      if (defect === "bad-counter") retry.row.attempt = 11;
      if (defect === "bad-delay") retry.row.retry_delay_ms = -1;
      if (defect === "wrong-kind") retry.row.type = "assistant";
      if (defect === "missing-input") rows.splice(rows.findIndex(row => row.event === "input_attempted"), 1);
      if (defect === "changed-registration") rows.find(row => row.row?.response?.request_id === "set-servers").row.response.response.errors = { workspace: "unconnected" };
      if (defect === "trailing-native") rows.splice(rows.length - 1, 0, structuredClone(retry));
      expect(observeClaudeControl({ ...outcome, stdout: rows.map(row => JSON.stringify(row)).join("\n") + "\n" }, f.input).failure).toBeNull();
    }
  }
});
test("terminal StructuredOutput needs matching stream call, successful receipt and value without a prose reply", async () => {
  const f = fixture("structured-terminal");
  f.input.structured_output = { schema_name: "team-structured-result.schema.json", bindings: { topology: "pipeline", substage: "worker_running", worker_role: "worker" } };
  const outcome = await new ClaudeControlRunner().run(f.input, f.environment, { assertCurrent: () => {} });
  const observed = observeClaudeControl(outcome, f.input);
  expect(observed.terminal).toBe(true); expect(JSON.parse(observed.text)).toEqual(observed.structured_output);
  const original = outcome.stdout.trim().split("\n").map(line => JSON.parse(line));
  for (const defect of ["missing-receipt", "error", "wrong-receipt", "wrong-value", "wrong-call", "duplicate-receipt"]) {
    const rows = structuredClone(original), receipt = rows.find(row => row.row?.type === "user"), result = rows.find(row => row.row?.type === "result");
    if (defect === "missing-receipt") rows.splice(rows.indexOf(receipt), 1);
    if (defect === "error") receipt.row.message.content[0].is_error = true;
    if (defect === "wrong-receipt") receipt.row.message.content[0].tool_use_id = "foreign";
    if (defect === "wrong-value") result.row.result = '{"unrelated":true}';
    if (defect === "wrong-call") rows.find(row => row.row?.type === "assistant").row.message.content[0].input.summary = "changed";
    if (defect === "duplicate-receipt") rows.splice(rows.indexOf(receipt), 0, structuredClone(receipt));
    expect(observeClaudeControl({ ...outcome, stdout: rows.map(row => JSON.stringify(row)).join("\n") + "\n" }, f.input).terminal).toBe(false);
  }
});
test("failed registration, extra tools and native permission requests withhold all user input", async () => {
  for (const mode of ["registration-error", "extra-tool", "permission-control"]) {
    const f = fixture(mode), outcome = await new ClaudeControlRunner().run(f.input, f.environment, { assertCurrent: () => {} });
    expect(outcome.exit_code).toBe(2); expect(f.received().filter(frame => frame.type === "user")).toHaveLength(0);
    expect(observeClaudeControl(outcome, f.input)).toMatchObject({ terminal: false, input_attempted: false });
  }
});
test("explicit message capability verifies both native servers and withholds input for missing or expanded peer tools", async () => {
  for (const mode of ["success", "missing-messages", "extra-message-tool"]) {
    const f = fixture(mode);
    f.input.communication_command = ["/usr/bin/node", join(f.root, "message.mjs"), join(f.root, "message.json")];
    const outcome = await new ClaudeControlRunner().run(f.input, f.environment, { assertCurrent: () => {} });
    expect(observeClaudeControl(outcome, f.input).terminal).toBe(mode === "success");
    expect(f.received().filter(frame => frame.type === "user")).toHaveLength(mode === "success" ? 1 : 0);
    const args = JSON.parse(readFileSync(join(f.workspace, "native-arguments.json"), "utf8"));
    expect(args[args.indexOf("--allowedTools") + 1]).toBe("mcp__workspace__*,mcp__controlmesh__*");
  }
});
test("an empty MCP table spends a bounded six control queries and zero task inputs", async () => {
  const f = fixture("empty"), outcome = await new ClaudeControlRunner().run(f.input, f.environment, { assertCurrent: () => {} });
  expect(outcome.exit_code).toBe(2); expect(outcome.stderr).toContain("claude_mcp_connection_unavailable");
  expect(f.received().filter(frame => frame.request?.subtype === "mcp_status")).toHaveLength(6);
  expect(f.received().filter(frame => frame.type === "user")).toHaveLength(0);
  expect(observeClaudeControl(outcome, f.input)).toMatchObject({ terminal: false, input_attempted: false });
});
test("wrong native version refuses control startup and environment injection is rejected before execution", async () => {
  const f = fixture("wrong-version");
  await expect(new ClaudeControlRunner().run(f.input, f.environment, { assertCurrent: () => {} })).rejects.toThrow("native_claude_version_changed");
  expect(f.received()).toHaveLength(0);
  await expect(new ClaudeControlRunner().run(f.input, { ...f.environment, credentials: { BUN_OPTIONS: "unexpected" } }, { assertCurrent: () => {} })).rejects.toThrow("unqualified_claude_control_environment");
});
test("unexpected builtins, foreign sessions, partial output and repeated result cannot establish completion", async () => {
  for (const mode of ["builtin", "foreign-session", "partial", "extra-result"]) {
    const f = fixture(mode), outcome = await new ClaudeControlRunner().run(f.input, f.environment, { assertCurrent: () => {} });
    const observed = observeClaudeControl(outcome, f.input);
    expect(observed.terminal).toBe(false); expect(observed.input_attempted).toBe(true);
    expect(f.received().filter(frame => frame.type === "user")).toHaveLength(1);
  }
});
test("retained native quota is classified, and changed input or truncated wrapper is not successful evidence", async () => {
  const f = fixture("quota"), outcome = await new ClaudeControlRunner().run(f.input, f.environment, { assertCurrent: () => {} });
  expect(observeClaudeControl(outcome, f.input)).toMatchObject({ terminal: false, input_attempted: true, failure: { code: "quota_exhausted" } });
  expect(observeClaudeControl(outcome, { ...f.input, prompt: "another task" })).toMatchObject({ terminal: false, input_attempted: null });
  expect(observeClaudeControl({ ...outcome, stdout: "" }, f.input)).toMatchObject({ terminal: false, input_attempted: null });
});
test("native max-turn completion is a task limit, not a provider health failure", async () => {
  const f = fixture("quota"), outcome = await new ClaudeControlRunner().run(f.input, f.environment, { assertCurrent() {} });
  const rows = outcome.stdout.trim().split("\n").map(line => JSON.parse(line));
  const result = rows.find(row => row.event === "native" && row.row?.type === "result").row;
  result.subtype = "error_max_turns"; result.errors = ["Reached maximum number of turns (6)"];
  delete result.error; result.result = "";
  expect(observeClaudeControl({ ...outcome, stdout: rows.map(row => JSON.stringify(row)).join("\n") + "\n" }, f.input))
    .toMatchObject({ terminal: false, input_attempted: true, invalid_reason: "claude_native_turn_limit_exceeded", failure: null });
  expect(observeClaudeControl(outcome, f.input)).toMatchObject({ failure: { code: "quota_exhausted" } });
});

test("parallel tool blocks count as one model turn; reused identities and extra actual turns still reject", async () => {
  const f = fixture(), input = { ...f.input, max_turns: 1 };
  const outcome = await new ClaudeControlRunner().run(input, f.environment, { assertCurrent() {} });
  const rows = outcome.stdout.trim().split("\n").map(line => JSON.parse(line));
  const index = rows.findIndex(row => row.event === "native" && row.row?.type === "assistant");
  const tool = (id: string, number: number) => ({ type: "controlmesh.claude_control", event: "native", row: { type: "assistant", session_id: input.session_id,
    message: { id, model: input.model, content: [{ type: "tool_use", id: `call-${number}`, name: "mcp__workspace__read_file", input: { path: `file-${number}` } }] } } });
  rows.splice(index, 0, ...Array.from({ length: 7 }, (_, number) => tool("one-model-response", number)));
  rows.find(row => row.row?.type === "result").row.num_turns = 8;
  const observe = () => observeClaudeControl({ ...outcome, stdout: rows.map(row => JSON.stringify(row)).join("\n") + "\n" }, input);
  expect(observe().terminal).toBe(true);
  rows.splice(index + 7, 0, tool("second-model-response", 8));
  expect(observe()).toMatchObject({ terminal: false, invalid_reason: "claude_native_turn_limit_exceeded" });
  rows.splice(index + 8, 0, tool("one-model-response", 9));
  expect(observe()).toMatchObject({ terminal: false, invalid_reason: "claude_native_turn_identity_reused" });
  rows.splice(index + 7, 2); delete rows[index].row.message.id;
  expect(observe()).toMatchObject({ terminal: false, invalid_reason: "claude_native_turn_identity_unproven" });
});
test("cancel after input reaps the owned native child and descendant; lost output remains unknown without a replay", async () => {
  const f = fixture("hang"), controller = new AbortController();
  const run = new ClaudeControlRunner().run(f.input, f.environment, { assertCurrent: () => {}, signal: controller.signal });
  const until = performance.now() + 4000;
  while (!existsSync(join(f.workspace, "descendant-pid"))) { if (performance.now() > until) { controller.abort(); throw new Error("native fixture did not start"); } await Bun.sleep(10); }
  controller.abort(); const outcome = await run;
  expect(outcome.reason).toBe("cancelled"); expect(observeClaudeControl(outcome, f.input)).toMatchObject({ terminal: false, input_attempted: true });
  expect(f.received().filter(frame => frame.type === "user")).toHaveLength(1);
  for (const name of ["native-pid", "descendant-pid"]) {
    const pid = Number(readFileSync(join(f.workspace, name), "utf8")); expect(pid).toBeGreaterThan(1);
    const path = `/proc/${pid}/stat`;
    if (existsSync(path)) expect(readFileSync(path, "utf8").split(") ")[1].split(" ")[0]).toBe("Z");
  }
});
test("an authority change between version and native dispatch blocks the task input", async () => {
  const f = fixture(); let changed = false, calls = 0;
  const runner = new ClaudeControlRunner({ run: async (spec, admission) => { calls++; const outcome = await new ProcessSupervisor().run(spec, admission); changed = true; return outcome; } });
  await expect(runner.run(f.input, f.environment, { assertCurrent: () => { if (changed) throw new Error("current lease revoked"); } })).rejects.toThrow("current lease revoked");
  expect(calls).toBe(1); expect(f.received()).toHaveLength(0);
  expect(() => claudeControlCommand({ ...f.input, session_id: "--continue" })).toThrow("invalid_claude_control_input");
});
test("native executable replacement and state inside the granted workspace are refused", async () => {
  const f = fixture(); let calls = 0;
  const runner = new ClaudeControlRunner({ run: async (spec, admission) => {
    calls++; const outcome = await new ProcessSupervisor().run(spec, admission);
    writeFileSync(f.input.executable, "#!/bin/sh\nexit 0\n"); return outcome;
  } });
  await expect(runner.run(f.input, f.environment, { assertCurrent: () => {} })).rejects.toThrow("claude_control_configuration_changed");
  expect(calls).toBe(1); expect(f.received()).toHaveLength(0);
  await expect(new ClaudeControlRunner().run(f.input, { ...f.environment, home: f.workspace }, { assertCurrent: () => {} })).rejects.toThrow("claude_control_state_overlaps_workspace");
});
