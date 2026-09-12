import { isAbsolute } from "node:path";
import { canonical, digest, object, requireThat, RuntimeConflict } from "../value";
import type { ProcessOutcome } from "../process-supervisor";
import { nativeFailure, type ProviderFailure } from "./opencode-events";
import { claudeStructuredSchema, decodeClaudeStructuredOutput, verifyClaudeStructuredValue, type ClaudeStructuredOutput } from "./claude-structured-output";

export const claudeNativeVersion = "2.1.263";
const fileTools = ["edit_file", "read_file", "write_file"];
const messageTools = ["send", "ask_parent", "receive", "answer"];
function claudeRetryFailure(value: unknown): ProviderFailure {
  requireThat(object(value) && value.type === "system" && value.subtype === "api_retry"
    && Number.isSafeInteger(value.attempt) && Number(value.attempt) >= 1
    && Number.isSafeInteger(value.max_retries) && Number(value.max_retries) <= 10 && Number(value.attempt) <= Number(value.max_retries)
    && Number.isSafeInteger(value.retry_delay_ms) && Number(value.retry_delay_ms) >= 0 && Number(value.retry_delay_ms) <= 300000
    && (value.error_status === null || (Number.isInteger(value.error_status) && Number(value.error_status) >= 400 && Number(value.error_status) <= 599))
    && typeof value.error === "string" && value.error.length > 0 && value.error.length <= 4096 && !value.error.includes("\0")
    && typeof value.uuid === "string" && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(value.uuid), "invalid_claude_api_retry");
  // The SDK's planned backoff is not evidence of a provider reset time or a Retry-After header.
  return nativeFailure(`${value.error_status ?? ""} ${value.error}`);
}
export interface ClaudeControlInput {
  schema_version: "controlmesh.claude_control.v1";
  executable: string;
  workspace: string;
  session_id: string;
  resume: boolean;
  model: string;
  prompt: string;
  max_turns: number;
  workspace_command: string[];
  communication_command?: string[];
  structured_output?: ClaudeStructuredOutput;
}
export interface ClaudeControlAction { frames: Record<string, unknown>[]; delay_ms?: number }
const same = (a: unknown, b: unknown) => canonical(a) === canonical(b);
const names = (value: unknown, expected: string[]): boolean => Array.isArray(value)
  && value.every(name => typeof name === "string") && same([...value].sort(), [...expected].sort());

export function validateClaudeControlInput(value: unknown): asserts value is ClaudeControlInput {
  requireThat(object(value) && same(Object.keys(value).sort(), ["schema_version", "executable", "workspace", "session_id", "resume", "model", "prompt", "max_turns", "workspace_command",
    ...(value.communication_command === undefined ? [] : ["communication_command"]), ...(value.structured_output === undefined ? [] : ["structured_output"])].sort()), "invalid_claude_control_input");
  requireThat(value.schema_version === "controlmesh.claude_control.v1" && typeof value.executable === "string" && isAbsolute(value.executable)
    && typeof value.workspace === "string" && isAbsolute(value.workspace) && typeof value.session_id === "string"
    && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(value.session_id)
    && typeof value.resume === "boolean" && typeof value.model === "string" && /^[^\s\x00]{1,256}$/.test(value.model)
    && typeof value.prompt === "string" && value.prompt.length > 0 && Buffer.byteLength(value.prompt) <= 32768
    && Number.isSafeInteger(value.max_turns) && Number(value.max_turns) >= 1 && Number(value.max_turns) <= 128
    && Array.isArray(value.workspace_command) && value.workspace_command.length === 3
    && value.workspace_command.every(part => typeof part === "string" && isAbsolute(part) && part.length <= 4096 && !/[\x00\r\n]/.test(part)), "invalid_claude_control_input");
  requireThat(value.communication_command === undefined || (Array.isArray(value.communication_command) && value.communication_command.length === 3
    && value.communication_command.every(part => typeof part === "string" && isAbsolute(part) && part.length <= 4096 && !/[\x00\r\n]/.test(part))), "invalid_claude_control_input");
  requireThat(!/[\x00\r\n]/.test(value.executable + value.workspace) && Buffer.byteLength(canonical(value)) <= 65536, "invalid_claude_control_input");
  if (value.structured_output !== undefined) decodeClaudeStructuredOutput(value.structured_output);
}

export function claudeWorkspaceServer(input: ClaudeControlInput): Record<string, unknown> {
  return { type: "stdio", command: input.workspace_command[0], args: input.workspace_command.slice(1) };
}
export function claudeServerProfiles(input: ClaudeControlInput): Record<string, { command: Record<string, unknown>; name: string; tools: string[] }> {
  return { workspace: { command: claudeWorkspaceServer(input), name: "controlmesh-workspace", tools: fileTools },
    ...(input.communication_command ? { controlmesh: { command: { type: "stdio", command: input.communication_command[0], args: input.communication_command.slice(1) },
      name: "controlmesh-task-communication", tools: messageTools } } : {}) };
}
export function claudeControlCommand(input: ClaudeControlInput): string[] {
  validateClaudeControlInput(input);
  return [input.executable, "--bare", "--print", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
    "--setting-sources", "", "--settings", '{"disableAllHooks":true}', "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
    "--no-chrome", "--disable-slash-commands", "--tools", "", "--permission-mode", "dontAsk", "--allowedTools",
    Object.keys(claudeServerProfiles(input)).map(name => `mcp__${name}__*`).join(","),
    "--model", input.model, "--effort", "low", "--max-turns", String(input.max_turns),
    ...(input.structured_output ? ["--json-schema", canonical(claudeStructuredSchema(input.structured_output))] : []), input.resume ? "--resume" : "--session-id", input.session_id];
}

/** The native control channel is not a task queue. Exactly one input follows verified MCP admission. */
export class ClaudeControlSession {
  private phase: "new" | "initialize" | "register" | "status" | "input" | "running" | "done" = "new";
  private attempts = 0;
  private pending = "";
  private readonly binding: string;
  private readonly rows: Record<string, unknown>[] = [];
  constructor(readonly input: ClaudeControlInput) { validateClaudeControlInput(input); this.binding = digest(input); }
  get inputAttempted(): boolean { return ["input", "running", "done"].includes(this.phase); }
  get complete(): boolean { return this.phase === "done"; }
  get nativeRows(): readonly Record<string, unknown>[] { return this.rows; }
  private request(id: string, request: Record<string, unknown>): ClaudeControlAction {
    this.pending = id; return { frames: [{ type: "control_request", request_id: id, request }] };
  }
  start(): ClaudeControlAction {
    requireThat(this.phase === "new", "claude_control_already_started"); this.phase = "initialize";
    return this.request("initialize", { subtype: "initialize", hooks: null, skills: [] });
  }
  accept(value: unknown): ClaudeControlAction {
    requireThat(digest(this.input) === this.binding, "claude_control_input_changed");
    requireThat(object(value) && this.rows.length < 4096 && this.phase !== "new" && this.phase !== "done", "unexpected_claude_control_record");
    this.rows.push(structuredClone(value));
    const profiles = claudeServerProfiles(this.input), serverNames = Object.keys(profiles);
    const nativeTools = [...Object.entries(profiles).flatMap(([name, profile]) => profile.tools.map(tool => `mcp__${name}__${tool}`)), ...(this.input.structured_output ? ["StructuredOutput"] : [])];
    requireThat(value.type !== "control_request", "claude_native_permission_request_refused");
    if (value.type === "control_response") {
      const response = value.response;
      requireThat(["initialize", "register", "status"].includes(this.phase) && object(response)
        && response.request_id === this.pending && response.subtype === "success" && object(response.response), "claude_control_response_unproven");
      const body = response.response;
      if (this.phase === "initialize") {
        requireThat(body.current_permission_mode === "dontAsk" && body.remote_control_auto_enable === false, "claude_control_configuration_unproven");
        this.phase = "register";
        return this.request("set-servers", { subtype: "mcp_set_servers", servers: Object.fromEntries(Object.entries(profiles).map(([name, profile]) => [name, profile.command])) });
      }
      if (this.phase === "register") {
        requireThat(names(body.added, serverNames) && names(body.removed, []) && object(body.errors) && Object.keys(body.errors).length === 0, "claude_mcp_registration_failed");
        this.phase = "status"; return this.request("mcp-status-0", { subtype: "mcp_status" });
      }
      requireThat(Array.isArray(body.mcpServers) && body.mcpServers.every(server => object(server) && typeof server.name === "string"
        && serverNames.includes(server.name) && ["pending", "connected"].includes(String(server.status)))
        && new Set(body.mcpServers.map(server => server.name)).size === body.mcpServers.length, "claude_mcp_status_unproven");
      if (body.mcpServers.length < serverNames.length || body.mcpServers.some(server => server.status === "pending")) {
        requireThat(++this.attempts < 6, "claude_mcp_connection_unavailable");
        return { ...this.request(`mcp-status-${this.attempts}`, { subtype: "mcp_status" }), delay_ms: 250 };
      }
      requireThat(body.mcpServers.length === serverNames.length, "claude_mcp_scope_unproven");
      for (const server of body.mcpServers) {
        const profile = profiles[String(server.name)];
        requireThat(server.status === "connected" && server.scope === "dynamic"
          && same(server.config, profile.command) && object(server.serverInfo)
          && server.serverInfo.name === profile.name && server.serverInfo.version === "1.0.0"
          && Array.isArray(server.tools) && server.tools.every(object) && names(server.tools.map((tool: Record<string, unknown>) => tool.name), profile.tools), "claude_mcp_scope_unproven");
      }
      this.phase = "input"; this.pending = "";
      return { frames: [{ type: "user", session_id: this.input.session_id, parent_tool_use_id: null,
        message: { role: "user", content: this.input.prompt } }] };
    }
    requireThat(this.inputAttempted && value.session_id === this.input.session_id, "claude_native_input_or_identity_unproven");
    if (value.type === "result" && value.is_error === true) { this.phase = "done"; return { frames: [] }; }
    if (this.phase === "input") {
      requireThat(value.type === "system" && value.subtype === "init" && value.cwd === this.input.workspace
        && value.claude_code_version === claudeNativeVersion && value.model === this.input.model && value.permissionMode === "dontAsk"
        && names(value.tools, nativeTools) && names(value.plugins, []) && names(value.skills, []) && names(value.slash_commands, [])
        && Array.isArray(value.mcp_servers) && value.mcp_servers.every(server => object(server) && server.status === "connected")
        && names(value.mcp_servers.map(server => server.name), serverNames), "claude_native_profile_unproven");
      this.phase = "running"; return { frames: [] };
    }
    if (value.type === "system" && value.subtype === "api_retry") {
      claudeRetryFailure(value); throw new RuntimeConflict("claude_native_api_retry_refused");
    }
    requireThat(["assistant", "user", "result"].includes(String(value.type)), "unsupported_claude_native_record");
    if (value.type === "assistant") {
      requireThat(object(value.message) && value.message.model === this.input.model && Array.isArray(value.message.content), "claude_native_model_unproven");
      for (const part of value.message.content) requireThat(object(part) && (["text", "thinking"].includes(String(part.type))
        || (part.type === "tool_use" && nativeTools.includes(String(part.name)))), "claude_native_tool_ungranted");
    }
    if (value.type === "result") this.phase = "done";
    return { frames: [] };
  }
}

/** Streaming content blocks share one API message ID; parallel calls are not separate model turns. */
export function claudeModelTurns(messages: unknown[]): { model_turns: number; tool_turns: number } {
  const seen = new Set<string>(), tools = new Set<string>(); let previous: string | undefined;
  for (const message of messages) {
    requireThat(object(message) && typeof message.id === "string" && message.id.length > 0 && message.id.length <= 256
      && Array.isArray(message.content), "claude_native_turn_identity_unproven");
    requireThat(message.id === previous || !seen.has(message.id), "claude_native_turn_identity_reused");
    seen.add(message.id); previous = message.id;
    if (message.content.some(part => object(part) && part.type === "tool_use")) tools.add(message.id);
  }
  return { model_turns: seen.size, tool_turns: tools.size };
}

export interface ClaudeControlObservation {
  structured_output?: Record<string, unknown>;
  terminal: boolean;
  text: string;
  input_attempted: boolean | null;
  invalid_reason: string | null;
  failure: ProviderFailure | null;
}

function replayRetryFailure(rows: unknown[], input: ClaudeControlInput): ProviderFailure {
  const machine = new ClaudeControlSession(input); machine.start();
  let expectsInput = false, attempted = false;
  for (const [index, row] of rows.entries()) {
    requireThat(object(row), "invalid_claude_control_output");
    if (expectsInput) {
      requireThat(row.event === "input_attempted" && row.input_digest === digest(input), "claude_control_input_unproven");
      expectsInput = false; attempted = true; continue;
    }
    requireThat(row.event === "native", "invalid_claude_control_output");
    if (index === rows.length - 1) {
      let refused = false;
      try { machine.accept(row.row); } catch (error) { refused = error instanceof RuntimeConflict && error.code === "claude_native_api_retry_refused"; }
      requireThat(attempted && refused, "claude_api_retry_unproven");
      return claudeRetryFailure(row.row);
    }
    expectsInput = machine.accept(row.row).frames.some(frame => frame.type === "user");
  }
  throw new RuntimeConflict("claude_api_retry_unproven");
}

/** Replay retained process evidence without another native/model invocation. Source JSONL is checked separately. */
export function observeClaudeControl(outcome: ProcessOutcome, input: ClaudeControlInput): ClaudeControlObservation {
  let attempted: boolean | null = null;
  const rejected = (reason: string): ClaudeControlObservation => ({ terminal: false, text: "", input_attempted: attempted, invalid_reason: reason, failure: null });
  try {
    const rows: unknown[] = outcome.stdout.trim().split("\n").filter(Boolean).map(line => JSON.parse(line));
    requireThat(rows.length <= 4100 && rows.every(object), "invalid_claude_control_output");
    const start = rows.shift();
    requireThat(object(start) && start.type === "controlmesh.claude_control" && start.event === "started" && start.input_digest === digest(input), "claude_control_binding_unproven");
    const last = rows.at(-1);
    if (object(last) && last.type === "controlmesh.claude_control" && last.event === "aborted" && last.input_digest === digest(input)
      && typeof last.input_attempted === "boolean" && typeof last.reason === "string" && /^[a-z0-9_]{1,96}$/.test(last.reason)) {
      requireThat(rows.every(row => object(row) && row.type === "controlmesh.claude_control"
        && ["native", "input_attempted", "aborted"].includes(String(row.event))) && rows.filter(row => (row as Record<string, unknown>).event === "aborted").length === 1,
      "invalid_claude_control_output");
      const inputRecords = rows.filter(row => (row as Record<string, unknown>).event === "input_attempted");
      requireThat(inputRecords.length <= 1 && (last.input_attempted || inputRecords.length === 0)
        && inputRecords.every(row => (row as Record<string, unknown>).input_digest === digest(input)), "claude_control_input_unproven");
      attempted = last.input_attempted;
      if (last.reason === "claude_native_api_retry_refused") {
        requireThat(attempted, "claude_api_retry_unproven");
        const failure = replayRetryFailure(rows.slice(0, -1), input);
        return { ...rejected(last.reason), failure };
      }
      return rejected(last.reason);
    }
    const machine = new ClaudeControlSession(input); machine.start();
    let expectsAttempt = false, attemptRecord = false, exited = false, nativeExit: number | null = null;
    for (const row of rows) {
      requireThat(object(row) && row.type === "controlmesh.claude_control" && !exited, "invalid_claude_control_output");
      if (expectsAttempt) {
        requireThat(row.event === "input_attempted" && row.input_digest === digest(input), "claude_control_input_unproven");
        attempted = true; attemptRecord = true; expectsAttempt = false; continue;
      }
      if (row.event === "native") {
        const action = machine.accept(row.row); expectsAttempt = action.frames.some(frame => frame.type === "user");
      } else if (row.event === "exited") {
        requireThat(Number.isInteger(row.exit_code), "claude_native_exit_unproven");
        nativeExit = Number(row.exit_code); exited = true;
      } else requireThat(false, "invalid_claude_control_output");
    }
    requireThat(exited && !expectsAttempt, "claude_control_completion_missing");
    if (!attemptRecord) attempted = false;
    const result = machine.nativeRows.at(-1);
    requireThat(machine.complete && attemptRecord && result?.type === "result", "claude_native_completion_unproven");
    if (result.is_error === true) {
      // A native task budget is not provider health or account quota evidence.
      if (result.subtype === "error_max_turns") return rejected("claude_native_turn_limit_exceeded");
      if (result.subtype === "error_max_structured_output_retries") return rejected("claude_structured_output_limit_exceeded");
      const message = [result.error, ...(Array.isArray(result.errors) ? result.errors : []), result.result]
        .flatMap(value => typeof value === "string" ? [value] : object(value) && typeof value.message === "string" ? [value.message] : []).join("\n");
      const failure = nativeFailure(/you['’]?ve hit your limit|exceeded your current quota/i.test(message) ? `usage limit reached; ${message}` : message);
      return { ...rejected(failure.code), failure };
    }
    requireThat(outcome.reason === "exited" && outcome.exit_code === 0 && nativeExit === 0 && result.is_error === false && result.subtype === "success"
      && typeof result.result === "string" && Number.isSafeInteger(result.num_turns) && Number(result.num_turns) > 0
      && Number(result.num_turns) <= 4100, "claude_native_completion_unproven");
    const assistants = machine.nativeRows.filter(row => row.type === "assistant"), final = assistants.at(-1);
    const turns = claudeModelTurns(assistants.map(row => row.message));
    requireThat(turns.tool_turns <= input.max_turns && turns.model_turns <= input.max_turns + 1, "claude_native_turn_limit_exceeded");
    requireThat(final && object(final.message) && typeof final.message.id === "string", "claude_native_final_output_unproven");
    const parts = assistants.filter(row => object(row.message) && row.message.id === (final.message as Record<string, unknown>).id)
      .flatMap(row => (row.message as { content: Record<string, unknown>[] }).content);
    requireThat(input.structured_output !== undefined || result.structured_output === undefined, "claude_structured_output_unrequested");
    const structured = input.structured_output ? verifyClaudeStructuredValue(input.structured_output, result.structured_output) : undefined;
    const calls = parts.filter(part => part.type === "tool_use");
    if (structured && calls.length > 0) {
      // Native --json-schema may terminate at the successful tool receipt, without a prose assistant turn.
      const call = calls[0]!;
      const receipts = machine.nativeRows.filter(row => row.type === "user" && object(row.message) && Array.isArray(row.message.content))
        .flatMap(row => (row.message as { content: Record<string, unknown>[] }).content)
        .filter(part => part.type === "tool_result" && part.tool_use_id === call.id);
      requireThat(calls.length === 1 && call.name === "StructuredOutput" && digest(call.input) === digest(structured)
        && receipts.length === 1 && receipts[0]!.is_error !== true && receipts[0]!.content === "Structured output provided successfully"
        && digest(JSON.parse(result.result)) === digest(structured), "claude_native_final_output_unproven");
    } else requireThat(calls.length === 0 && parts.filter(part => part.type === "text").map(part => part.text).join("") === result.result,
      "claude_native_final_output_unproven");
    return { terminal: true, text: result.result, input_attempted: true, invalid_reason: null, failure: null,
      ...(structured ? { structured_output: structured } : {}) };
  } catch (error) { return rejected(error instanceof Error && /^[a-z0-9_]{1,96}$/.test(error.message) ? error.message : "invalid_claude_control_output"); }
}
