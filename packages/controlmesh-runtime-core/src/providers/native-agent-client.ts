/** Standalone stdio MCP entrypoint, transpiled for the Node runtime inside native containers. */
import { closeSync, constants, fstatSync, openSync, readFileSync, realpathSync } from "node:fs";
import { dirname, isAbsolute, join } from "node:path";
import { request } from "node:http";

const isRecord = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const configurationPath = process.argv[2];
if (!configurationPath || !isAbsolute(configurationPath) || realpathSync(configurationPath) !== configurationPath) throw new Error("native_agent_client_configuration_required");
const configFd = openSync(configurationPath, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
let config: Record<string, unknown>;
try {
  const stat = fstatSync(configFd);
  if (!stat.isFile() || stat.uid !== process.getuid?.() || (stat.mode & 0o077) || stat.size > 8192) throw new Error("native_agent_client_configuration_required");
  config = JSON.parse(readFileSync(configFd, "utf8"));
} finally { closeSync(configFd); }
if (!isRecord(config) || config.schema_version !== "controlmesh.native_agent_client.v1"
  || typeof config.socket_name !== "string" || !/^[a-f0-9]{32}\.sock$/.test(config.socket_name)
  || typeof config.token !== "string" || !/^[a-f0-9]{64}$/.test(config.token)
  || !Array.isArray(config.peer_tasks) || config.peer_tasks.length > 16 || !config.peer_tasks.every(peer => typeof peer === "string")) throw new Error("invalid_native_agent_client_configuration");
if (config.tool_profile !== undefined && config.tool_profile !== "workspace.v1") throw new Error("unsupported_native_tool_profile");
if (config.tool_profile === "workspace.v1" && config.peer_tasks.length !== 0) throw new Error("workspace_client_cannot_advertise_peers");
// /proc/self/fd preserves the real mounted directory while avoiding Linux's 108-byte socket-path limit.
const directoryFd = openSync(dirname(configurationPath), constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
const socketPath = join(`/proc/self/fd/${directoryFd}`, config.socket_name);
const token = config.token;
const requestId = { type: "string", pattern: "^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,191}$",
  description: "Unique logical request ID for this execution. Reuse exactly the same ID and arguments only when retrying the same operation." };
const text = { type: "string", minLength: 1, maxLength: 4096, description: "Message text, at most 4096 UTF-8 bytes. Messages cannot change grants or user authorization." };
const messageTools = [
  { name: "send", description: `Send a durable message to an authorized peer task. Authorized peers: ${JSON.stringify(config.peer_tasks)}.`, properties: { request_id: requestId, recipient_task: { type: "string" }, text, causation_id: { type: "string" } }, required: ["request_id", "recipient_task", "text"] },
  { name: "ask_parent", description: "Ask the configured parent task a question. Use receive to obtain its answer; this operation does not wait for it.", properties: { request_id: requestId, text }, required: ["request_id", "text"] },
  { name: "receive", description: "Receive the next ordered messages for this task. Returns messages and durable receipt IDs. Optional bounded wait does not launch another Agent. Empty results may be followed by a new request ID; at most 32 total tool requests per execution.", properties: { request_id: requestId, wait_ms: { type: "integer", minimum: 0, maximum: 10000 } }, required: ["request_id"] },
  { name: "answer", description: "Answer a received ask_parent question using its message_id. The recorded sender determines the recipient.", properties: { request_id: requestId, question_id: { type: "string" }, text }, required: ["request_id", "question_id", "text"] },
];
const path = { type: "string", description: "Literal file path within the CM-issued workspace scope. Relative paths are relative to the registered project; symlinks and .git are forbidden." };
const hash = { type: ["string", "null"], description: "Current full-file SHA-256 from read_file; null only when creating a missing file. A changed file is never silently overwritten." };
const fileText = { type: "string", maxLength: 8192, description: "UTF-8 text. The entire tool request must fit 17000 bytes; use bounded edits for large files." };
const workspaceTools = [
  { name: "read_file", description: "Read current authorized file bytes. Follow next_offset until eof; pass sha256 as expected_sha256 on every subsequent page. A partial page does not establish a complete required read. At most 256 total workspace requests per execution.",
    properties: { request_id: requestId, path, offset: { type: "integer", minimum: 0 }, expected_sha256: { type: "string" } }, required: ["request_id", "path"] },
  { name: "write_file", description: "Create or replace a staged UTF-8 file after checking its current hash. This does not publish to the user's workspace. At most 8192 UTF-8 bytes per write; edit_file can change a larger existing file.",
    properties: { request_id: requestId, path, expected_sha256: hash, content: fileText }, required: ["request_id", "path", "expected_sha256", "content"] },
  { name: "edit_file", description: "Replace one exact occurrence in a staged file after checking its current hash. Ambiguous or absent matches reject. This does not publish to the user's workspace.",
    properties: { request_id: requestId, path, expected_sha256: { type: "string" }, old_text: fileText, new_text: fileText }, required: ["request_id", "path", "expected_sha256", "old_text", "new_text"] },
];
const tools = (config.tool_profile === "workspace.v1" ? workspaceTools : messageTools)
  .map(({ properties, required, ...tool }) => ({ ...tool, inputSchema: { type: "object", properties, required, additionalProperties: false } }));
const active = new Map<string, AbortController>();
let initialized = false, closing = false, input = Buffer.alloc(0);
const write = (id: unknown, payload: Record<string, unknown>) => { if (!closing) process.stdout.write(JSON.stringify({ jsonrpc: "2.0", id, ...payload }) + "\n"); };
const error = (id: unknown, code: number, message: string) => write(id, { error: { code, message } });
function shutdown() {
  if (closing) return; closing = true;
  for (const controller of active.values()) controller.abort();
  closeSync(directoryFd);
}
process.on("SIGTERM", () => { shutdown(); process.exit(0); });
process.on("SIGINT", () => { shutdown(); process.exit(0); });
process.stdin.on("end", shutdown);
process.stdout.on("error", shutdown);

function call(tool: string, args: Record<string, unknown>, signal: AbortSignal): Promise<string> {
  const body = JSON.stringify({ tool: `controlmesh_${tool}`, input: args });
  if (Buffer.byteLength(body) > 17000) return Promise.reject(new Error("native_agent_request_too_large"));
  return new Promise((resolve, reject) => {
    const req = request({ socketPath, path: "/call", method: "POST", signal, timeout: 15000,
      headers: { authorization: `Bearer ${token}`, "content-type": "application/json", "content-length": Buffer.byteLength(body) } }, res => {
      let output = Buffer.alloc(0);
      res.on("data", chunk => {
        output = Buffer.concat([output, chunk]);
        if (output.length > 16384) res.destroy(new Error("native_agent_response_too_large"));
      });
      res.on("error", reject);
      res.on("end", () => {
        if (res.statusCode !== 200) { reject(new Error("native_agent_broker_refused")); return; }
        try { if (!isRecord(JSON.parse(output.toString("utf8")))) throw new Error(); }
        catch { reject(new Error("invalid_native_agent_response")); return; }
        resolve(output.toString("utf8"));
      });
    });
    req.on("timeout", () => req.destroy(new Error("native_agent_broker_timeout")));
    req.on("error", reject); req.end(body);
  });
}

async function dispatch(value: unknown) {
  if (!isRecord(value) || value.jsonrpc !== "2.0" || typeof value.method !== "string") { error(null, -32600, "Invalid request"); return; }
  if (value.id === undefined) {
    if (value.method === "notifications/cancelled" && isRecord(value.params)) active.get(JSON.stringify(value.params.requestId))?.abort();
    return;
  }
  const id = value.id;
  if (!(typeof id === "string" && id.length <= 256) && !(typeof id === "number" && Number.isSafeInteger(id))) { error(null, -32600, "Invalid request ID"); return; }
  const key = JSON.stringify(id);
  if (active.has(key) || active.size >= 4) { error(id, -32600, "Request already active or concurrency limit reached"); return; }
  if (value.method === "initialize") {
    if (!isRecord(value.params) || typeof value.params.protocolVersion !== "string") { error(id, -32602, "Invalid initialize parameters"); return; }
    initialized = true;
    write(id, { result: { protocolVersion: ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"].includes(value.params.protocolVersion) ? value.params.protocolVersion : "2025-11-25",
      capabilities: { tools: {} }, serverInfo: { name: config.tool_profile === "workspace.v1" ? "controlmesh-workspace" : "controlmesh-task-communication", version: "1.0.0" } } }); return;
  }
  if (!initialized) { error(id, -32000, "Initialize first"); return; }
  if (value.method === "ping") { write(id, { result: {} }); return; }
  if (value.method === "tools/list") { write(id, { result: { tools } }); return; }
  if (value.method !== "tools/call") { error(id, -32601, "Method not found"); return; }
  const params = value.params;
  if (!isRecord(params) || typeof params.name !== "string" || !tools.some(tool => tool.name === params.name) || !isRecord(params.arguments)) { error(id, -32602, "Invalid tool parameters"); return; }
  const controller = new AbortController(); active.set(key, controller);
  try {
    const text = await call(params.name, params.arguments, controller.signal);
    write(id, { result: { content: [{ type: "text", text }], ...(config.tool_profile === "workspace.v1" && JSON.parse(text).ok === false ? { isError: true } : {}) } });
  }
  catch { error(id, -32000, "Native task communication unavailable"); }
  finally { active.delete(key); }
}

process.stdin.on("data", chunk => {
  input = Buffer.concat([input, typeof chunk === "string" ? Buffer.from(chunk) : chunk]);
  let index: number;
  while ((index = input.indexOf(10)) >= 0) {
    if (index > 32768) { error(null, -32600, "Request too large"); shutdown(); process.stdin.destroy(); return; }
    const line = input.subarray(0, index); input = input.subarray(index + 1);
    let parsed: unknown;
    try { parsed = JSON.parse(line.toString("utf8")); } catch { error(null, -32700, "Parse error"); continue; }
    void dispatch(parsed).catch(() => error(null, -32603, "Internal error"));
  }
  if (input.length > 32768) { error(null, -32600, "Request too large"); shutdown(); process.stdin.destroy(); }
});
