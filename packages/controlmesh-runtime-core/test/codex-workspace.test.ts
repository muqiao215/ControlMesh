import { expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { canonical } from "../src/value";
import { NativeWorkspaceFiles } from "../src/providers/native-workspace-files";
import { codexWorkspaceBinding, verifyCodexWorkspace } from "../src/providers/codex-workspace";
import { codexCommunicationArguments } from "../src/providers/codex-communication";

test("Codex file completion requires exact native read receipts and current source bytes", () => {
  const root = mkdtempSync(join(tmpdir(), "cm-codex-file-proof-")), workspace = join(root, "project"), journal = join(root, "receipts");
  mkdirSync(workspace); mkdirSync(journal, { mode: 0o700 });
  const path = join(workspace, "PROJECT.md"), binding = codexWorkspaceBinding("config", "task", "episode");
  writeFileSync(path, "current project\n");
  const config = { node_executable: process.execPath, read_files: [path], required_reads: [path] };
  try {
    const files = new NativeWorkspaceFiles({ workspace, read_files: [path], tools: ["controlmesh_read_file"], journal_directory: journal, binding_digest: binding }, fn => fn(), () => {});
    const input = { request_id: "read", path: "PROJECT.md" }, response = files.call("controlmesh_read_file", input);
    const stdout = JSON.stringify({ type: "item.completed", item: { type: "mcp_tool_call", server: "controlmesh_workspace", tool: "read_file", arguments: input, status: "completed", error: null, result: { content: [{ type: "text", text: canonical(response) }] } } });
    const completion = { schema_version: "controlmesh.task_completion.v1", files: [{ path: "PROJECT.md", mode: "read" }] };
    expect(verifyCodexWorkspace(config, workspace, files.scope, binding, stdout, () => {}, completion).workspace_receipts.read_files).toEqual([path]);
    expect(() => verifyCodexWorkspace(config, workspace, files.scope, "wrong", stdout, () => {}, completion)).toThrow("codex_workspace_binding_changed");
    expect(() => verifyCodexWorkspace(config, workspace, files.scope, binding, "", () => {}, completion)).toThrow("workspace_tool_call_unobserved");
    expect(() => verifyCodexWorkspace(config, workspace, files.scope, binding, stdout, () => {}, { ...completion, files: [{ path: "PROJECT.md", mode: "read", sha256: "0".repeat(64) }] })).toThrow("task_completion_content_mismatch");
    writeFileSync(path, "changed after native execution\n");
    expect(() => verifyCodexWorkspace(config, workspace, files.scope, binding, stdout, () => {}, completion)).toThrow("workspace_tool_source_changed");
  } finally { rmSync(root, { recursive: true, force: true }); }
});
test("Codex workspace stdio exposes read_file while preserving the scoped message server", () => {
  const command = ["/bin/node", "/private/client.mjs", "/private/config.json"];
  const flags = codexCommunicationArguments(command, command)[1];
  expect(flags).toContain("controlmesh={"); expect(flags).toContain("controlmesh_workspace={");
  expect(flags).toContain('enabled_tools=["read_file"]'); expect(flags).not.toContain("write_file");
});
