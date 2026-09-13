import { isAbsolute } from "node:path";
import { object, requireThat } from "../value";
import { nativeAgentTools, type NativeAgentToolResult } from "./native-agent-journal";

/** Controller-owned stdio servers; no caller-selected server map or shell command. */
export function codexCommunicationArguments(command?: readonly string[], workspace?: readonly string[]): string[] {
  if (!command && !workspace) return [];
  const validate = (command: readonly string[]) => {
    requireThat(command.length === 3 && command.every(part => typeof part === "string" && isAbsolute(part) && part.length <= 4096 && !/[\x00\r\n]/.test(part)), "invalid_codex_communication_command");
  };
  const entries: string[] = [];
  if (command) { validate(command); entries.push(`controlmesh={command=${JSON.stringify(command[0])},args=${JSON.stringify(command.slice(1))},required=true,enabled_tools=["send","ask_parent","receive","answer"],tools={send={approval_mode="approve"},ask_parent={approval_mode="approve"},receive={approval_mode="approve"},answer={approval_mode="approve"}}}`); }
  if (workspace) { validate(workspace); entries.push(`controlmesh_workspace={command=${JSON.stringify(workspace[0])},args=${JSON.stringify(workspace.slice(1))},required=true,enabled_tools=["read_file"],tools={read_file={approval_mode="approve"}}}`); }
  return ["-c", `mcp_servers={${entries.join(",")}}`];
}

/** Native tool outcomes must also match the controller journal before acceptance. */
export function codexCommunicationTools(stdout: string): NativeAgentToolResult[] { return codexTools(stdout, "controlmesh", nativeAgentTools, 32); }
export function codexWorkspaceTools(stdout: string): NativeAgentToolResult[] { return codexTools(stdout, "controlmesh_workspace", ["controlmesh_read_file"], 256); }
function codexTools(stdout: string, server: string, allowed: readonly string[], limit: number): NativeAgentToolResult[] {
  const tools: NativeAgentToolResult[] = [];
  for (const line of stdout.trim().split("\n").filter(Boolean)) {
    const row: unknown = JSON.parse(line);
    if (!object(row) || row.type !== "item.completed" || !object(row.item) || row.item.type !== "mcp_tool_call") continue;
    const item = row.item;
    requireThat(item.server === "controlmesh" || item.server === "controlmesh_workspace", "codex_communication_receipt_unproven");
    if (item.server !== server) continue;
    requireThat(typeof item.tool === "string" && object(item.arguments)
      && item.status === "completed" && (item.error === undefined || item.error === null) && object(item.result) && item.result.isError !== true && Array.isArray(item.result.content) && item.result.content.length === 1,
      "codex_communication_receipt_unproven");
    const part = item.result.content[0], tool = `controlmesh_${item.tool}`;
    requireThat(allowed.includes(tool) && object(part) && part.type === "text" && typeof part.text === "string", "codex_communication_receipt_unproven");
    tools.push({ tool, input: item.arguments, output: part.text });
    requireThat(tools.length <= limit, "native_agent_call_budget_exhausted");
  }
  return tools;
}
