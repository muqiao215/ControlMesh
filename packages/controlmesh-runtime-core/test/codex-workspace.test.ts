import { expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { canonical } from "../src/value";
import { WorkspaceStage } from "../src/workspace-stage";
import { nativeWorkspaceTools, NativeWorkspaceFiles } from "../src/providers/native-workspace-files";
import { codexWorkspaceBinding, verifyCodexWorkspace } from "../src/providers/codex-workspace";
import { codexCommunicationArguments, codexWorkspaceTools } from "../src/providers/codex-communication";

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

test("Codex staged write evidence survives publication and reopen without repeating a write", () => {
  const root = mkdtempSync(join(tmpdir(), "cm-codex-stage-proof-")), workspace = join(root, "project"), state = join(root, "state"), journal = join(root, "receipts");
  mkdirSync(workspace); mkdirSync(state, { mode: 0o700 }); mkdirSync(journal, { mode: 0o700 });
  const path = join(workspace, "PROJECT.md"), binding = codexWorkspaceBinding("config", "task", "episode");
  writeFileSync(path, "before\n");
  const config = { node_executable: process.execPath, read_files: [path], required_reads: [] };
  try {
    const stage = WorkspaceStage.createFiles(state, workspace, ["PROJECT.md"], binding, fn => fn());
    const files = new NativeWorkspaceFiles({ workspace, read_files: [path], tools: nativeWorkspaceTools, journal_directory: journal, binding_digest: binding, stage }, fn => fn(), () => {});
    const rows: string[] = [];
    const call = (tool: string, input: Record<string, unknown>) => {
      const response = files.call(`controlmesh_${tool}`, input);
      rows.push(JSON.stringify({ type: "item.completed", item: { type: "mcp_tool_call", server: "controlmesh_workspace", tool, arguments: input, status: "completed", error: null, result: { content: [{ type: "text", text: canonical(response) }] } } }));
      return response;
    };
    const read = call("read_file", { request_id: "read", path: "PROJECT.md" });
    const write = call("write_file", { request_id: "write", path: "PROJECT.md", content: "after\n", expected_sha256: read.sha256 });
    expect(write.ok).toBe(true);
    expect(readFileSync(path, "utf8")).toBe("before\n");
    const stdout = rows.join("\n"), completion = { schema_version: "controlmesh.task_completion.v1", files: [{ path: "PROJECT.md", mode: "write", sha256: write.sha256 }] };
    expect(() => codexWorkspaceTools(stdout)).toThrow("codex_communication_receipt_unproven");
    const proof = verifyCodexWorkspace(config, workspace, files.scope, binding, stdout, () => {}, completion, stage);
    expect(proof.workspace_receipts.written_files).toEqual([path]);
    expect(() => verifyCodexWorkspace(config, workspace, files.scope, binding, stdout, () => {}, completion)).toThrow("workspace_tool_retained_scope_changed");
    const proposal = stage.seal(fn => fn());
    stage.promote(fn => fn(), proposal.proposal_digest);
    expect(readFileSync(path, "utf8")).toBe("after\n");
    const reopened = WorkspaceStage.open(stage.path, stage.reference());
    expect(verifyCodexWorkspace(config, workspace, files.scope, binding, stdout, () => {}, completion, reopened)).toEqual(proof);
    reopened.assertApplied(proposal.proposal_digest);
    const command = ["/bin/node", "/private/client.mjs", "/private/config.json"];
    expect(codexCommunicationArguments(undefined, command, nativeWorkspaceTools)[1]).toContain('enabled_tools=["read_file","write_file","edit_file"]');
    expect(() => codexCommunicationArguments(undefined, command, ["shell"])).toThrow("invalid_codex_workspace_tools");
  } finally { rmSync(root, { recursive: true, force: true }); }
});
