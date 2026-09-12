import { realpathSync } from "node:fs";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";
import { contains } from "../containers/plan";
import { digest, object, requireThat } from "../value";
import { WorkspaceStage } from "../workspace-stage";
import { directoryIdentity, type NativeManifest, type NativeWorkspaceDispatch } from "./native-manifest";
import { assertWorkspaceGrantSnapshot, inspectWorkspacePermissions, readFileGrant } from "./opencode-profile";
import type { NativeSessionStore } from "./native-session";

/** Trusted workspace registration confers read/edit within these roots; it is never taken from a task body. */
export interface IssuedWorkspaceWrite { roots: readonly string[]; workflow_binding?: string }
export type NativeWriteReceipt = { proposal_digest: string; changed_paths: string[] };

export function writeRoots(workspace: string, input: IssuedWorkspaceWrite): string[] {
  requireThat(input && Array.isArray(input.roots) && input.roots.length > 0 && input.roots.length <= 64, "native_write_roots_required");
  requireThat(input.workflow_binding === undefined || (typeof input.workflow_binding === "string" && /^[a-f0-9]{64}$/.test(input.workflow_binding)), "native_workflow_binding_invalid");
  const roots = [...new Set(input.roots)].sort();
  for (const root of roots) requireThat(typeof root === "string" && isAbsolute(root) && !/[?*\x00\r\n]/.test(root)
    && directoryIdentity(root).path === root && contains(workspace, root) && !relative(workspace, root).split("/").includes(".git"), "native_write_root_outside_workspace");
  return roots.filter(root => !roots.some(parent => parent !== root && contains(parent, root)));
}

/** Mutable registered files can be deleted by an owned proposal; authority still uses the same literal path. */
export function registeredReads(workspace: string, files: readonly string[], roots: readonly string[], afterWrites = false): string[] {
  requireThat(Array.isArray(files) && files.length <= 80, "read_grant_too_large");
  const result = files.map(path => {
    requireThat(typeof path === "string" && isAbsolute(path) && resolve(path) === path && !/[?*\x00\r\n]/.test(path), "read_grant_requires_literal_path");
    if (afterWrites && roots.some(root => contains(root, path))) return path;
    const actual = readFileGrant(workspace, [path])[0];
    requireThat(!roots.some(root => contains(root, path)) || path === actual, "native_write_read_alias_not_issued");
    return actual;
  });
  return [...new Set(result)].sort();
}

export function workspacePatterns(worktree: string, files: readonly string[], roots: readonly string[], stage: WorkspaceStage) {
  const edit_patterns = roots.map(root => relative(worktree, root) ? `${relative(worktree, root)}/*` : "*");
  const read_patterns = [...new Set([...files.map(file => relative(worktree, file)), ...roots.map(root => relative(worktree, root) || "."), ...edit_patterns])].sort();
  const denied_patterns = [...new Set([".git", ".git/*", "*/.git", "*/.git/*",
    ...stage.deniedPaths().flatMap(path => [relative(worktree, path), `${relative(worktree, path)}/*`])])].sort();
  return { read_patterns, edit_patterns, denied_patterns };
}

export function openWorkspace(manifest: NativeManifest, stateHome: string, issued: IssuedWorkspaceWrite, grant: unknown): WorkspaceStage {
  const saved = manifest.workspace_write;
  requireThat(saved && dirname(saved.stage_path) === realpathSync(stateHome), "native_workspace_stage_state_mismatch");
  const roots = writeRoots(manifest.directory.path, issued);
  requireThat(saved.workflow_binding === (issued.workflow_binding ?? null), "native_workflow_binding_changed");
  requireThat(digest(roots.map(directoryIdentity)) === digest(saved.roots), "native_write_grant_changed");
  assertWorkspaceGrantSnapshot(grant, manifest.directory.path, roots, manifest.communication ? ["controlmesh_send", "controlmesh_ask_parent", "controlmesh_receive", "controlmesh_answer"] : []);
  const stage = WorkspaceStage.open(saved.stage_path, saved.stage_reference);
  requireThat(digest(workspacePatterns(manifest.worktree.path, manifest.files.map(file => file.path), roots, stage))
    === digest({ read_patterns: saved.read_patterns, edit_patterns: saved.edit_patterns, denied_patterns: saved.denied_patterns }), "native_write_permission_scope_changed");
  return stage;
}

export function workspacePermissionEvidence(resolved: unknown, agent: string, dataHome: string, saved: NativeWorkspaceDispatch,
  baseline: NativeManifest["baseline"], communication: readonly string[]): NativeManifest["permission_evidence"] {
  requireThat(object(resolved) && object(resolved.tools), "native_permission_evidence_unavailable");
  const compact = { name: resolved.name, mode: resolved.mode, permission: resolved.permission,
    ...(typeof resolved.prompt === "string" ? { prompt: resolved.prompt } : {}), tools: Object.fromEntries(Object.keys(resolved.tools).map(tool => [tool, {}])) };
  const checked = inspectWorkspacePermissions(compact, agent, dataHome, saved.read_patterns, saved.edit_patterns, baseline?.permissions ?? [], communication, saved.denied_patterns);
  requireThat(checked, "native_write_grant_unverified");
  return { agent, data_home: dataHome, resolved: compact, digest: checked.digest };
}

export function verifyWorkspaceTools(manifest: NativeManifest, stage: WorkspaceStage,
  evidence: ReturnType<NativeSessionStore["verifyTurn"]>, receipt: NativeWriteReceipt): { read_files: string[]; written_files: string[] } {
  const saved = manifest.workspace_write!;
  requireThat(object(receipt) && typeof receipt.proposal_digest === "string" && /^[a-f0-9]{64}$/.test(receipt.proposal_digest)
    && Array.isArray(receipt.changed_paths) && receipt.changed_paths.every(path => typeof path === "string"), "native_write_receipt_invalid");
  stage.assertProposal(receipt.proposal_digest);
  requireThat(digest({ proposal_digest: receipt.proposal_digest, changed_paths: receipt.changed_paths }) === digest(stage.proposalReceipt()), "native_write_receipt_changed");
  const roots = saved.roots.map(root => root.path), denied = stage.deniedPaths(), written = new Set<string>();
  const path = (value: unknown, write = false) => {
    requireThat(typeof value === "string" && value.length > 0 && !/[\x00\r\n]/.test(value), "native_file_tool_path_invalid");
    const absolute = resolve(manifest.directory.path, value);
    requireThat(contains(manifest.directory.path, absolute) && !relative(manifest.directory.path, absolute).split("/").includes(".git")
      && !denied.some(root => contains(root, absolute)) && (roots.some(root => contains(root, absolute))
        || (!write && manifest.files.some(file => file.path === absolute))), "native_ungranted_file_access");
    return absolute;
  };
  const read = evidence.read_files.map(file => path(file));
  requireThat(manifest.required_reads.every(file => read.includes(file)), "required_native_read_unproven");
  for (const tool of evidence.file_tools) {
    if (tool.tool === "read") path(tool.input.filePath);
    else if (tool.tool === "apply_patch") {
      requireThat(Array.isArray(tool.metadata.files) && tool.metadata.files.length > 0 && tool.metadata.files.length <= 2048, "native_patch_paths_unproven");
      for (const file of tool.metadata.files) {
        requireThat(object(file) && ["add", "update", "delete", "move"].includes(String(file.type)), "native_patch_paths_unproven");
        written.add(path(file.filePath, true));
        if (file.type === "move") written.add(path(file.movePath, true));
      }
    } else written.add(path(tool.input.filePath, true));
  }
  requireThat(receipt.changed_paths.every(changed => written.has(path(join(manifest.directory.path, changed), true))), "native_write_tool_evidence_missing");
  return { read_files: read, written_files: [...written] };
}
