import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";

// Synthetic native source with real stdio MCP; compiled for the container's own Node runtime.
const args = process.argv.slice(2), model = args[args.indexOf("--model") + 1], cwd = process.cwd();
const structuredSchema = args.includes("--json-schema") ? JSON.parse(args[args.indexOf("--json-schema") + 1]!) : undefined;
const emit = (row: unknown) => process.stdout.write(JSON.stringify(row) + "\n");
if (args.includes("--version")) { console.log("2.1.263 (Claude Code)"); process.exit(0); }
if (args.includes("--safe-mode")) {
  const session_id = randomUUID();
  emit({ type: "system", subtype: "init", session_id, model, tools: [], mcp_servers: [], plugins: [] });
  emit({ type: "assistant", session_id, message: { model, content: [{ type: "text", text: "PONG" }] } });
  emit({ type: "result", session_id, subtype: "success", is_error: false, result: "PONG", num_turns: 1 });
  process.exit(0);
}
const config = process.env.CLAUDE_CONFIG_DIR!, session_id = args[args.indexOf(args.includes("--resume") ? "--resume" : "--session-id") + 1];
const readOnly = existsSync(join(config, "fixture-read-only"));
const workspaceTools = ["edit_file", "read_file", "write_file"];
const projects = join(config, "projects", "fixture"); mkdirSync(projects, { recursive: true, mode: 0o700 });
const path = join(projects, session_id + ".jsonl");
let parent = existsSync(path) ? JSON.parse(readFileSync(path, "utf8").trim().split("\n").at(-1)!).uuid : null;
const source = (role: "user" | "assistant", content: unknown, stop_reason?: string, extras: Record<string, unknown> = {}, messageExtras: Record<string, unknown> = {}) => {
  const uuid = randomUUID(), message = { role, content, ...(role === "assistant" ? { id: randomUUID(), model, stop_reason } : {}), ...messageExtras };
  appendFileSync(path, JSON.stringify({ type: role, sessionId: session_id, cwd, isSidechain: false, uuid, parentUuid: parent, message, ...extras }) + "\n", { mode: 0o600 });
  parent = uuid; return message;
};
class Client {
  readonly child;
  private sequence = 0;
  private pending = new Map<number, { resolve: (row: any) => void; reject: (error: Error) => void }>();
  private readonly done: Promise<void>;
  constructor(command: { command: string; args: string[] }) {
    this.child = spawn(command.command, command.args, { stdio: ["pipe", "pipe", "inherit"] });
    createInterface({ input: this.child.stdout }).on("line", line => { const row = JSON.parse(line), waiter = this.pending.get(row.id); if (waiter) { this.pending.delete(row.id); waiter.resolve(row); } });
    this.done = new Promise((resolve, reject) => {
      this.child.once("error", reject); this.child.once("close", () => { for (const waiter of this.pending.values()) waiter.reject(new Error("fixture MCP closed")); resolve(); });
    });
  }
  request(method: string, params: unknown): Promise<any> {
    const id = ++this.sequence;
    return new Promise((resolve, reject) => { this.pending.set(id, { resolve, reject }); this.child.stdin.write(JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n"); });
  }
  async initialize() {
    await this.request("initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "fixture", version: "1" } });
    this.child.stdin.write(JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" }) + "\n");
  }
  async close() { this.child.stdin.end(); await this.done; }
}
let servers: Record<string, { command: string; args: string[] }> = {};
for await (const line of createInterface({ input: process.stdin })) {
  const frame = JSON.parse(line);
  if (frame.type === "control_request") {
    const type = frame.request.subtype;
    if (type === "mcp_set_servers") servers = frame.request.servers;
    const response = type === "initialize" ? { current_permission_mode: "dontAsk", remote_control_auto_enable: false }
      : type === "mcp_set_servers" ? { added: Object.keys(servers), removed: [], errors: {} }
      : { mcpServers: Object.entries(servers).map(([name, config]) => ({ name, config, status: "connected", scope: "dynamic",
        serverInfo: { name: name === "workspace" ? "controlmesh-workspace" : "controlmesh-task-communication", version: "1.0.0" },
        tools: (name === "workspace" ? workspaceTools : ["send", "ask_parent", "receive", "answer"]).map(name => ({ name })) })) };
    emit({ type: "control_response", response: { subtype: "success", request_id: frame.request_id, response } });
  } else if (frame.type === "user") {
    appendFileSync(join(config, "inputs.jsonl"), JSON.stringify({ session_id, prompt: frame.message.content }) + "\n");
    let directWriteDenied = false; try { writeFileSync(join(cwd, "PROJECT.md"), "forbidden"); } catch { directWriteDenied = true; }
    if (!directWriteDenied) throw new Error("fixture requires a read-only project");
    if (structuredSchema && args.includes("--resume")) {
      source("user", [{ type: "text", text: "Continue from where you left off." }], undefined,
        { isMeta: true, promptId: randomUUID(), version: "2.1.263", entrypoint: "sdk-cli" });
      source("assistant", [{ type: "text", text: "No response requested." }], "stop_sequence",
        { version: "2.1.263", entrypoint: "sdk-cli" }, { model: "<synthetic>", stop_sequence: "", usage: { input_tokens: 0, output_tokens: 0 } });
    }
    source("user", frame.message.content);
    emit({ type: "system", subtype: "init", cwd, session_id, model, claude_code_version: "2.1.263", permissionMode: "dontAsk",
      tools: [...workspaceTools.map(name => `mcp__workspace__${name}`), ...(structuredSchema ? ["StructuredOutput"] : [])], mcp_servers: [{ name: "workspace", status: "connected" }], plugins: [], skills: [], slash_commands: [] });
    const client = new Client(servers.workspace); await client.initialize();
    const call = async (name: string, input: Record<string, unknown>) => {
      const id = randomUUID(); source("assistant", [{ type: "tool_use", id, name: `mcp__workspace__${name}`, input }], "tool_use");
      const row = await client.request("tools/call", { name, arguments: input });
      source("user", [{ type: "tool_result", tool_use_id: id, content: row.result.content, ...(row.result.isError ? { is_error: true } : {}) }]);
      return JSON.parse(row.result.content[0].text);
    };
    try {
      if (!readOnly) {
      const read = await call("read_file", { request_id: "read", path: "PROJECT.md" });
      const result = await call("read_file", { request_id: "existing", path: "result.txt" });
      const written = await call("write_file", { request_id: "write", path: "result.txt", expected_sha256: result.ok ? result.sha256 : "missing", content: read.content });
      if (!written.ok) throw new Error("fixture write failed");
      await call("read_file", { request_id: "readback", path: "result.txt" });
      }
      let text = existsSync(join(config, "fixture-result.json")) ? readFileSync(join(config, "fixture-result.json"), "utf8") : "DONE";
      let structured: unknown;
      if (structuredSchema) {
        const raw = JSON.parse(text);
        structured = { schema_version: 1, confidence: null, evidence: [], artifacts: [], next_action: null, repair_hint: null,
          ...(structuredSchema.properties.round_index ? { stop_reason: null, ...(raw.topology === "director_worker"
            ? { dispatch_roles: [] } : { winner_role: null, next_candidate_roles: [] }) } : { result_items: [], needs_parent_input: false }), ...raw };
        if (args.includes("--resume")) {
          const id = randomUUID(), message = source("assistant", [{ type: "tool_use", id, name: "StructuredOutput", input: { ...structured as object, schema_version: "1" } }], "tool_use");
          emit({ type: "assistant", session_id, message });
          const receipt = source("user", [{ type: "tool_result", tool_use_id: id, content: "Output does not match required schema: invalid schema_version", is_error: true }]);
          emit({ type: "user", session_id, message: receipt });
        }
        const id = randomUUID(), message = source("assistant", [{ type: "tool_use", id, name: "StructuredOutput", input: structured }], "tool_use");
        emit({ type: "assistant", session_id, message });
        const uuid = randomUUID();
        appendFileSync(path, JSON.stringify({ type: "attachment", sessionId: session_id, cwd, isSidechain: false, uuid, parentUuid: parent,
          attachment: { type: "structured_output", data: structured } }) + "\n"); parent = uuid;
        const receipt = source("user", [{ type: "tool_result", tool_use_id: id, content: "Structured output provided successfully" }]);
        emit({ type: "user", session_id, message: receipt });
        text = JSON.stringify(structured);
      } else {
        const message = source("assistant", [{ type: "text", text }], "end_turn");
        emit({ type: "assistant", session_id, message });
      }
      emit({ type: "result", session_id, subtype: "success", is_error: false, result: text, num_turns: 5, ...(structured ? { structured_output: structured } : {}) });
    } finally { await client.close(); }
  }
}
