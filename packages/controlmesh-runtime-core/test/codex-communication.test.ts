import { expect, test } from "bun:test";
import { codexCommunicationArguments, codexCommunicationTools } from "../src/providers/codex-communication";

test("Codex communication registers only the four controller-owned messaging tools", () => {
  expect(codexCommunicationArguments()).toEqual([]);
  const flags = codexCommunicationArguments(["/bin/node", "/private/client.mjs", "/private/config.json"]);
  expect(flags[1]).toContain('enabled_tools=["send","ask_parent","receive","answer"]');
  expect(flags[1]).not.toContain("default_tools_approval_mode");
  for (const command of [["node", "/private/client.mjs", "/private/config.json"], ["/bin/sh", "-c", "echo test"], ["/bin/node", "/private/client.mjs"]]) {
    expect(() => codexCommunicationArguments(command)).toThrow("invalid_codex_communication_command");
  }
});
test("Codex message receipts reject failed, foreign, unknown or non-text tool results", () => {
  const item = { id: "tool", type: "mcp_tool_call", server: "controlmesh", tool: "send", arguments: { request_id: "send", recipient_task: "peer", text: "hello" }, status: "completed", error: null, result: { content: [{ type: "text", text: '{"ok":true}' }] } };
  const emit = (value: unknown) => JSON.stringify({ type: "item.completed", item: value });
  expect(codexCommunicationTools(emit(item))).toEqual([{ tool: "controlmesh_send", input: item.arguments, output: '{"ok":true}' }]);
  for (const changed of [{ ...item, error: { message: "failed" } }, { ...item, result: { ...item.result, isError: true } }, { ...item, status: "failed" }, { ...item, server: "outside" }, { ...item, tool: "exec" }, { ...item, result: null }, { ...item, result: { content: [{ type: "image", text: "pretend" }] } }]) {
    expect(() => codexCommunicationTools(emit(changed))).toThrow("codex_communication_receipt_unproven");
  }
});
