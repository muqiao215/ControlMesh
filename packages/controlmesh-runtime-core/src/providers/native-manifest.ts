import { closeSync, constants, fstatSync, lstatSync, openSync, readSync, realpathSync } from "node:fs";
import { createHash } from "node:crypto";
import { relative } from "node:path";
import { digest, object, requireThat } from "../value";
import type { LegacyTask } from "../value";
import type { ProbeBinding } from "./preflight-cache";
import type { NativeBaseline } from "./native-session";
import { inspectReadPermissions, readFileGrant } from "./opencode-profile";
import { decodeNativeMailbox, type NativeMailboxBatch } from "./native-mailbox-input";

export interface DirectoryIdentity { path: string; device: string; inode: string }
export interface ReadSnapshot { path: string; device: string; inode: string; size: string; modified_ns: string; changed_ns: string; sha256: string }
export interface NativeManifest extends Record<string, unknown> {
  schema_version: "controlmesh.native_dispatch.v1";
  task_digest: string;
  binding: ProbeBinding;
  native_store_id: string;
  baseline: NativeBaseline | null;
  directory: DirectoryIdentity;
  worktree: DirectoryIdentity;
  files: ReadSnapshot[];
  required_reads: string[];
  permission_evidence: { agent: string; data_home: string; resolved: Record<string, unknown>; digest: string };
  mailbox_delivery?: NativeMailboxBatch;
}

export function nativeTaskDigest(task: LegacyTask): string {
  return digest({ provider: task.provider, model: task.model, repo_root: task.repo_root, prompt: task.prompt,
    native_session: task.native_session ?? null, tool_grant: task.tool_grant ?? null, execution_context: task.execution_context ?? null });
}

export function nativeReadInstructions(required: readonly string[]): string {
  return [
    "You are the execution agent for the current ControlMesh task. Follow the current user request and use only the issued read permissions.",
    "Conversation history contains earlier decisions and possibly outdated file contents. Preserve that history, but use current tool results for current project facts.",
    ...(required.length ? [
      "Before answering this turn, you MUST call the read tool on EACH path in required_reads below, even if an earlier turn read it. These files may have changed since the previous conversation.",
      "Do not copy an earlier answer or infer current file contents from memory. If a required read cannot complete, report the blockage; do not claim completion.",
      `required_reads (literal path data): ${JSON.stringify(required)}`,
    ] : []),
    "Report the observed result accurately and honor the user's requested output format.",
  ].join("\n");
}

export function directoryIdentity(path: string): DirectoryIdentity {
  const resolved = realpathSync(path), stat = lstatSync(resolved, { bigint: true });
  requireThat(stat.isDirectory(), "native_workspace_unavailable");
  return { path: resolved, device: String(stat.dev), inode: String(stat.ino) };
}

function fileMetadata(path: string): Omit<ReadSnapshot, "sha256"> {
  const stat = lstatSync(path, { bigint: true });
  requireThat(stat.isFile() && realpathSync(path) === path, "native_read_file_replaced");
  return { path, device: String(stat.dev), inode: String(stat.ino), size: String(stat.size), modified_ns: String(stat.mtimeNs), changed_ns: String(stat.ctimeNs) };
}

export function snapshotReads(directory: string, paths: readonly string[]): ReadSnapshot[] {
  const files = readFileGrant(directory, paths);
  let total = 0;
  return files.map(path => {
    const before = fileMetadata(path);
    requireThat(Number(before.size) <= 4 * 1024 * 1024, "native_read_evidence_too_large");
    total += Number(before.size);
    requireThat(total <= 16 * 1024 * 1024, "native_read_evidence_too_large");
    const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
    try {
      const stat = fstatSync(fd, { bigint: true });
      requireThat(stat.isFile() && String(stat.dev) === before.device && String(stat.ino) === before.inode && String(stat.size) === before.size, "native_read_file_replaced");
      const hash = createHash("sha256"), chunk = Buffer.alloc(65_536);
      let size = 0;
      while (true) {
        const count = readSync(fd, chunk);
        if (!count) break;
        size += count;
        requireThat(size <= Number(before.size), "native_read_file_changed");
        hash.update(chunk.subarray(0, count));
      }
      requireThat(size === Number(before.size) && digest(before) === digest(fileMetadata(path)), "native_read_file_changed");
      return { ...before, sha256: hash.digest("hex") };
    } finally { closeSync(fd); }
  });
}

export function assertWorkspaceManifest(manifest: NativeManifest, hashFiles = false): void {
  requireThat(digest(directoryIdentity(manifest.directory.path)) === digest(manifest.directory)
    && digest(directoryIdentity(manifest.worktree.path)) === digest(manifest.worktree), "native_workspace_replaced");
  for (const file of manifest.files) {
    const { sha256: _hash, ...metadata } = file;
    requireThat(digest(fileMetadata(file.path)) === digest(metadata), "native_read_file_changed");
  }
  if (hashFiles) requireThat(digest(snapshotReads(manifest.directory.path, manifest.files.map(file => file.path))) === digest(manifest.files), "native_read_content_changed");
}

export function permissionEvidence(resolved: unknown, agent: string, dataHome: string, worktree: string, files: readonly string[], baseline: NativeBaseline | null): NativeManifest["permission_evidence"] {
  requireThat(object(resolved) && object(resolved.tools), "native_permission_evidence_unavailable");
  // Persist only rules and tool names; native debug output can also contain unrelated prompt/configuration data.
  const compact = { name: resolved.name, mode: resolved.mode, permission: resolved.permission,
    ...(typeof resolved.prompt === "string" ? { prompt: resolved.prompt } : {}),
    tools: Object.fromEntries(Object.keys(resolved.tools).map(name => [name, {}])) };
  const checked = inspectReadPermissions(compact, agent, dataHome, files.map(file => relative(worktree, file)), baseline?.permissions ?? []);
  requireThat(checked, "native_read_grant_unverified");
  return { agent, data_home: dataHome, resolved: compact, digest: checked.digest };
}

export function decodeNativeManifest(value: unknown): NativeManifest {
  requireThat(object(value) && value.schema_version === "controlmesh.native_dispatch.v1", "unsupported_native_manifest");
  for (const key of ["task_digest", "native_store_id"]) requireThat(typeof value[key] === "string" && /^[a-f0-9]{64}$/.test(value[key] as string), "invalid_native_manifest");
  requireThat(object(value.binding) && value.binding.provider === "opencode" && value.binding.cli_version === "1.18.29", "native_permission_profile_unverified");
  for (const key of ["directory", "worktree"]) {
    const path = value[key];
    requireThat(object(path) && typeof path.path === "string" && typeof path.device === "string" && typeof path.inode === "string", "invalid_native_manifest");
  }
  requireThat(Array.isArray(value.files) && value.files.length <= 80 && value.files.every(file => object(file) && ["path", "device", "inode", "size", "modified_ns", "changed_ns", "sha256"].every(key => typeof file[key] === "string")), "invalid_native_manifest");
  requireThat(Array.isArray(value.required_reads) && value.required_reads.every(file => typeof file === "string" && (value.files as ReadSnapshot[]).some(saved => saved.path === file)), "invalid_native_manifest");
  const permission = value.permission_evidence;
  requireThat(object(permission) && typeof permission.agent === "string" && typeof permission.data_home === "string" && typeof permission.digest === "string" && object(permission.resolved), "invalid_native_manifest");
  requireThat(value.baseline === null || (object(value.baseline) && object(value.baseline.reference) && object(value.baseline.messages) && object(value.baseline.parts) && Array.isArray(value.baseline.permissions)), "invalid_native_manifest");
  if (value.mailbox_delivery !== undefined) decodeNativeMailbox(value.mailbox_delivery);
  return value as NativeManifest;
}
