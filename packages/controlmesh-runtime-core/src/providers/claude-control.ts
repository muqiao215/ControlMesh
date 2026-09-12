import { isAbsolute } from "node:path";
import { canonical, digest, object, requireThat } from "../value";
import type { ProcessOutcome } from "../process-supervisor";
import { nativeFailure, type ProviderFailure } from "./opencode-events";

export const claudeNativeVersion = "2.1.263";
const fileTools = ["edit_file", "read_file", "write_file"];
const nativeTools = fileTools.map(name => `mcp__workspace__${name}`);
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
}
export interface ClaudeControlAction { frames: Record<string, unknown>[]; delay_ms?: number }
const same = (a: unknown, b: unknown) => canonical(a) === canonical(b);
const names = (value: unknown, expected: string[]): boolean => Array.isArray(value)
  && value.every(name => typeof name === "string") && same([...value].sort(), [...expected].sort());

export function validateClaudeControlInput(value: unknown): asserts value is ClaudeControlInput {
  requireThat(object(value) && same(Object.keys(value).sort(), ["schema_version", "executable", "workspace", "session_id", "resume", "model", "prompt", "max_turns", "workspace_command"].sort()), "invalid_claude_control_input");
  requireThat(value.schema_version === "controlmesh.claude_control.v1" && typeof value.executable === "string" && isAbsolute(value.executable)
    && typeof value.workspace === "string" && isAbsolute(value.workspace) && typeof value.session_id === "string"
    && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(value.session_id)
    && typeof value.resume === "boolean" && typeof value.model === "string" && /^[^\s\x00]{1,256}$/.test(value.model)
    && typeof value.prompt === "string" && value.prompt.length > 0 && Buffer.byteLength(value.prompt) <= 32768
    && Number.isSafeInteger(value.max_turns) && Number(value.max_turns) >= 1 && Number(value.max_turns) <= 128
    && Array.isArray(value.workspace_command) && value.workspace_command.length === 3
    && value.workspace_command.every(part => typeof part === "string" && isAbsolute(part) && part.length <= 4096 && !/[\x00\r\n]/.test(part)), "invalid_claude_control_input");
  requireThat(!/[\x00\r\n]/.test(value.executable + value.workspace) && Buffer.byteLength(canonical(value)) <= 65536, "invalid_claude_control_input");
}

export function claudeWorkspaceServer(input: ClaudeControlInput): Record<string, unknown> {
  return { type: "stdio", command: input.workspace_command[0], args: input.workspace_command.slice(1) };
}
export function claudeControlCommand(input: ClaudeControlInput): string[] {
  validateClaudeControlInput(input);
  return [input.executable, "--bare", "--print", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
    "--setting-sources", "", "--settings", '{"disableAllHooks":true}', "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
    "--no-chrome", "--disable-slash-commands", "--tools", "", "--permission-mode", "dontAsk", "--allowedTools", "mcp__workspace__*",
    "--model", input.model, "--effort", "low", "--max-turns", String(input.max_turns), input.resume ? "--resume" : "--session-id", input.session_id];
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
    requireThat(value.type !== "control_request", "claude_native_permission_request_refused");
    if (value.type === "control_response") {
      const response = value.response;
      requireThat(["initialize", "register", "status"].includes(this.phase) && object(response)
        && response.request_id === this.pending && response.subtype === "success" && object(response.response), "claude_control_response_unproven");
      const body = response.response;
      if (this.phase === "initialize") {
        requireThat(body.current_permission_mode === "dontAsk" && body.remote_control_auto_enable === false, "claude_control_configuration_unproven");
        this.phase = "register";
        return this.request("set-servers", { subtype: "mcp_set_servers", servers: { workspace: claudeWorkspaceServer(this.input) } });
      }
      if (this.phase === "register") {
        requireThat(names(body.added, ["workspace"]) && names(body.removed, []) && object(body.errors) && Object.keys(body.errors).length === 0, "claude_mcp_registration_failed");
        this.phase = "status"; return this.request("mcp-status-0", { subtype: "mcp_status" });
      }
      requireThat(Array.isArray(body.mcpServers), "claude_mcp_status_unproven");
      if (body.mcpServers.length === 0 || (body.mcpServers.length === 1 && object(body.mcpServers[0])
        && body.mcpServers[0].name === "workspace" && body.mcpServers[0].status === "pending")) {
        requireThat(++this.attempts < 6, "claude_mcp_connection_unavailable");
        return { ...this.request(`mcp-status-${this.attempts}`, { subtype: "mcp_status" }), delay_ms: 250 };
      }
      requireThat(body.mcpServers.length === 1 && object(body.mcpServers[0]), "claude_mcp_scope_unproven");
      const server = body.mcpServers[0];
      requireThat(server.name === "workspace" && server.status === "connected" && server.scope === "dynamic"
        && same(server.config, claudeWorkspaceServer(this.input)) && object(server.serverInfo)
        && server.serverInfo.name === "controlmesh-workspace" && server.serverInfo.version === "1.0.0"
        && Array.isArray(server.tools) && server.tools.every(object) && names(server.tools.map(tool => tool.name), fileTools), "claude_mcp_scope_unproven");
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
        && same(value.mcp_servers, [{ name: "workspace", status: "connected" }]), "claude_native_profile_unproven");
      this.phase = "running"; return { frames: [] };
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

export interface ClaudeControlObservation {
  terminal: boolean;
  text: string;
  input_attempted: boolean | null;
  invalid_reason: string | null;
  failure: ProviderFailure | null;
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
      attempted = last.input_attempted; return rejected(last.reason);
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
      const message = [result.error, ...(Array.isArray(result.errors) ? result.errors : []), result.result]
        .flatMap(value => typeof value === "string" ? [value] : object(value) && typeof value.message === "string" ? [value.message] : []).join("\n");
      const failure = nativeFailure(/you['’]?ve hit your limit|exceeded your current quota/i.test(message) ? `usage limit reached; ${message}` : message);
      return { ...rejected(failure.code), failure };
    }
    requireThat(outcome.reason === "exited" && outcome.exit_code === 0 && nativeExit === 0 && result.is_error === false && result.subtype === "success"
      && typeof result.result === "string" && Number.isSafeInteger(result.num_turns) && Number(result.num_turns) > 0
      && Number(result.num_turns) <= input.max_turns, "claude_native_completion_unproven");
    const assistants = machine.nativeRows.filter(row => row.type === "assistant"), final = assistants.at(-1);
    requireThat(final && object(final.message) && typeof final.message.id === "string", "claude_native_final_output_unproven");
    const parts = assistants.filter(row => object(row.message) && row.message.id === (final.message as Record<string, unknown>).id)
      .flatMap(row => (row.message as { content: Record<string, unknown>[] }).content);
    requireThat(!parts.some(part => part.type === "tool_use") && parts.filter(part => part.type === "text").map(part => part.text).join("") === result.result, "claude_native_final_output_unproven");
    return { terminal: true, text: result.result, input_attempted: true, invalid_reason: null, failure: null };
  } catch (error) { return rejected(error instanceof Error && /^[a-z0-9_]{1,96}$/.test(error.message) ? error.message : "invalid_claude_control_output"); }
}
