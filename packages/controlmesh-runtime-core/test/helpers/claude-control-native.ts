import { appendFileSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd(), scenario = JSON.parse(readFileSync(join(root, "scenario.json"), "utf8"));
if (process.argv.includes("--version")) { console.log(scenario.mode === "wrong-version" ? "0.0.0 (Claude Code)" : "2.1.263 (Claude Code)"); process.exit(0); }
writeFileSync(join(root, "native-pid"), String(process.pid));
const args = process.argv.slice(2), session = args[args.indexOf(args.includes("--resume") ? "--resume" : "--session-id") + 1];
const model = args[args.indexOf("--model") + 1];
writeFileSync(join(root, "native-arguments.json"), JSON.stringify(args));
const emit = (row: unknown) => process.stdout.write(JSON.stringify(row) + "\n");
let servers: Record<string, unknown> = {}, pending = "";
for await (const chunk of Bun.stdin.stream()) {
  pending += new TextDecoder().decode(chunk); let end: number;
  while ((end = pending.indexOf("\n")) >= 0) {
    const frame = JSON.parse(pending.slice(0, end)); pending = pending.slice(end + 1);
    appendFileSync(join(root, "received.jsonl"), JSON.stringify(frame) + "\n");
    if (frame.type === "control_request") {
      let response: Record<string, unknown>;
      if (frame.request.subtype === "initialize") response = { current_permission_mode: "dontAsk", remote_control_auto_enable: false };
      else if (frame.request.subtype === "mcp_set_servers") {
        servers = frame.request.servers;
        response = { added: Object.keys(servers), removed: [], errors: scenario.mode === "registration-error" ? { workspace: "fixture disconnected" } : {} };
      } else response = { mcpServers: scenario.mode === "empty" ? [] : Object.entries(servers).filter(([name]) => !(name === "controlmesh" && scenario.mode === "missing-messages"))
        .map(([name, config]) => ({ name, status: "connected", scope: "dynamic", config,
          serverInfo: { name: name === "workspace" ? "controlmesh-workspace" : "controlmesh-task-communication", version: "1.0.0" },
          tools: (name === "workspace" ? ["edit_file", "read_file", "write_file", ...(scenario.mode === "extra-tool" ? ["bash"] : [])]
            : ["send", "ask_parent", "receive", "answer", ...(scenario.mode === "extra-message-tool" ? ["read_file"] : [])]).map(name => ({ name })) })) };
      if (scenario.mode === "permission-control") emit({ type: "control_request", request_id: "native-permission", request: { subtype: "can_use_tool", tool_name: "Bash" } });
      else emit({ type: "control_response", response: { subtype: "success", request_id: frame.request_id, response } });
    } else if (frame.type === "user") {
      if (scenario.mode === "hang") {
        const child = Bun.spawn([process.execPath, "-e", "setInterval(() => {}, 1000)"], { stdin: "ignore", stdout: "ignore", stderr: "ignore" });
        writeFileSync(join(root, "descendant-pid"), String(child.pid));
        await new Promise(() => {});
      }
      emit({ type: "system", subtype: "init", cwd: root, session_id: session, claude_code_version: "2.1.263", model,
        permissionMode: "dontAsk", tools: ["mcp__workspace__edit_file", "mcp__workspace__read_file", "mcp__workspace__write_file", ...(scenario.mode === "builtin" ? ["Read"] : []),
          ...(servers.controlmesh ? ["send", "ask_parent", "receive", "answer"].map(name => `mcp__controlmesh__${name}`) : []), ...(args.includes("--json-schema") ? ["StructuredOutput"] : [])],
        mcp_servers: Object.keys(servers).map(name => ({ name, status: "connected" })), plugins: [], skills: [], slash_commands: [] });
      if (scenario.mode.startsWith("api-retry-")) {
        const cases: Record<string, [number | null, string]> = {
          quota: [429, "insufficient_quota"], rate: [429, "rate_limit_error"], auth: [401, "authentication_failed"], unknown: [null, "unknown"],
        };
        const [error_status, error] = cases[scenario.mode.slice("api-retry-".length)];
        emit({ type: "system", subtype: "api_retry", attempt: 1, max_retries: 10, retry_delay_ms: 1500, error_status, error,
          session_id: session, uuid: "aaaaaaaa-0000-0000-0000-000000000002" });
        await Bun.sleep(1500); writeFileSync(join(root, "api-retried"), "unexpected retry"); continue;
      }
      const schema = args.includes("--json-schema") ? JSON.parse(args[args.indexOf("--json-schema") + 1]!) : undefined;
      const structured = schema ? { schema_version: 1, topology: schema.properties.topology.const, substage: schema.properties.substage.const,
        worker_role: scenario.mode === "structured-wrong-role" ? "foreign" : schema.properties.worker_role.const, status: "completed", summary: "Verified fixture",
        result_items: [], evidence: [], confidence: null, artifacts: [], next_action: null, needs_parent_input: false, repair_hint: null } : undefined;
      if (structured) emit({ type: "assistant", session_id: session, message: { id: "structure", role: "assistant", model,
        content: [{ type: "tool_use", id: "structured", name: "StructuredOutput", input: structured }] } });
      if (structured) emit({ type: "user", session_id: session, message: { role: "user", content: [{ type: "tool_result", tool_use_id: "structured",
        content: "Structured output provided successfully" }] } });
      const terminalTool = structured && scenario.mode.startsWith("structured-terminal");
      if (!terminalTool) emit({ type: "assistant", session_id: scenario.mode === "foreign-session" ? "foreign" : session,
        message: { id: "answer", role: "assistant", model, content: [{ type: "text", text: "DONE" }] } });
      if (scenario.mode === "partial") { process.stdout.write('{"type":"result"'); process.exit(0); }
      if (scenario.mode === "quota") emit({ type: "result", session_id: session, is_error: true, subtype: "error_during_execution", errors: ["You have exceeded your current quota"] });
      else emit({ type: "result", session_id: session, is_error: false, subtype: "success", result: terminalTool ? JSON.stringify(structured) : "DONE", num_turns: structured ? 2 : 1,
        ...(structured && scenario.mode !== "structured-missing" ? { structured_output: structured } : {}) });
      if (scenario.mode === "extra-result") emit({ type: "result", session_id: session, is_error: false, subtype: "success", result: "DONE", num_turns: 1 });
    }
  }
}
