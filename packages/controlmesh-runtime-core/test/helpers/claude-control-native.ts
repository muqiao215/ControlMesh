import { appendFileSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd(), scenario = JSON.parse(readFileSync(join(root, "scenario.json"), "utf8"));
if (process.argv.includes("--version")) { console.log(scenario.mode === "wrong-version" ? "0.0.0 (Claude Code)" : "2.1.263 (Claude Code)"); process.exit(0); }
writeFileSync(join(root, "native-pid"), String(process.pid));
const args = process.argv.slice(2), session = args[args.indexOf(args.includes("--resume") ? "--resume" : "--session-id") + 1];
const model = args[args.indexOf("--model") + 1];
writeFileSync(join(root, "native-arguments.json"), JSON.stringify(args));
const emit = (row: unknown) => process.stdout.write(JSON.stringify(row) + "\n");
let server: Record<string, unknown>, pending = "";
for await (const chunk of Bun.stdin.stream()) {
  pending += new TextDecoder().decode(chunk); let end: number;
  while ((end = pending.indexOf("\n")) >= 0) {
    const frame = JSON.parse(pending.slice(0, end)); pending = pending.slice(end + 1);
    appendFileSync(join(root, "received.jsonl"), JSON.stringify(frame) + "\n");
    if (frame.type === "control_request") {
      let response: Record<string, unknown>;
      if (frame.request.subtype === "initialize") response = { current_permission_mode: "dontAsk", remote_control_auto_enable: false };
      else if (frame.request.subtype === "mcp_set_servers") {
        server = frame.request.servers.workspace;
        response = { added: ["workspace"], removed: [], errors: scenario.mode === "registration-error" ? { workspace: "fixture disconnected" } : {} };
      } else response = { mcpServers: scenario.mode === "empty" ? [] : [{ name: "workspace", status: "connected", scope: "dynamic", config: server!,
        serverInfo: { name: "controlmesh-workspace", version: "1.0.0" }, tools: ["edit_file", "read_file", "write_file", ...(scenario.mode === "extra-tool" ? ["bash"] : [])].map(name => ({ name })) }] };
      if (scenario.mode === "permission-control") emit({ type: "control_request", request_id: "native-permission", request: { subtype: "can_use_tool", tool_name: "Bash" } });
      else emit({ type: "control_response", response: { subtype: "success", request_id: frame.request_id, response } });
    } else if (frame.type === "user") {
      if (scenario.mode === "hang") {
        const child = Bun.spawn([process.execPath, "-e", "setInterval(() => {}, 1000)"], { stdin: "ignore", stdout: "ignore", stderr: "ignore" });
        writeFileSync(join(root, "descendant-pid"), String(child.pid));
        await new Promise(() => {});
      }
      emit({ type: "system", subtype: "init", cwd: root, session_id: session, claude_code_version: "2.1.263", model,
        permissionMode: "dontAsk", tools: ["mcp__workspace__edit_file", "mcp__workspace__read_file", "mcp__workspace__write_file", ...(scenario.mode === "builtin" ? ["Read"] : [])],
        mcp_servers: [{ name: "workspace", status: "connected" }], plugins: [], skills: [], slash_commands: [] });
      emit({ type: "assistant", session_id: scenario.mode === "foreign-session" ? "foreign" : session,
        message: { id: "answer", role: "assistant", model, content: [{ type: "text", text: "DONE" }] } });
      if (scenario.mode === "partial") { process.stdout.write('{"type":"result"'); process.exit(0); }
      if (scenario.mode === "quota") emit({ type: "result", session_id: session, is_error: true, subtype: "error_during_execution", errors: ["You have exceeded your current quota"] });
      else emit({ type: "result", session_id: session, is_error: false, subtype: "success", result: "DONE", num_turns: 1 });
      if (scenario.mode === "extra-result") emit({ type: "result", session_id: session, is_error: false, subtype: "success", result: "DONE", num_turns: 1 });
    }
  }
}
