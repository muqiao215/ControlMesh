import { createHash } from "node:crypto";
import { constants, openSync, closeSync, fstatSync, readSync } from "node:fs";
import { join } from "node:path";
import { digest, object, requireThat } from "./value";
import { WorkspaceStage, type WorkspaceAuthority } from "./workspace-stage";

export interface WorkspaceSeedManifest {
  schema_version: "controlmesh.workspace_seed.v1";
  files: { path: string; size: number; sha256: string }[];
}
const sha = (bytes: Uint8Array) => createHash("sha256").update(bytes).digest("hex");

/** Receiver primitive. The caller must bind the expected digest and allowlist to device authority. */
export function validateWorkspaceSeed(value: unknown, expectedDigest: string, allowedFiles: readonly string[]): WorkspaceSeedManifest {
  requireThat(object(value) && Object.keys(value).every(key => ["schema_version", "files"].includes(key))
    && value.schema_version === "controlmesh.workspace_seed.v1" && Array.isArray(value.files)
    && value.files.length > 0 && value.files.length <= 80, "workspace_seed_invalid");
  const seen = new Set<string>(); let total = 0;
  for (const file of value.files) {
    requireThat(object(file) && Object.keys(file).length === 3 && typeof file.path === "string" && file.path.length <= 4096
      && !/[\\\x00-\x1f\x7f]/.test(file.path) && file.path.split("/").every(part => part && ![".", "..", ".git"].includes(part))
      && allowedFiles.includes(file.path) && !seen.has(file.path), "workspace_seed_path_not_authorized");
    requireThat(typeof file.sha256 === "string" && /^[a-f0-9]{64}$/.test(file.sha256) && Number.isSafeInteger(file.size)
      && Number(file.size) >= 0 && Number(file.size) <= 4 * 1024 * 1024, "workspace_seed_file_invalid");
    total += Number(file.size); seen.add(file.path);
  }
  requireThat(total <= 16 * 1024 * 1024 && digest(value) === expectedDigest, "workspace_seed_manifest_mismatch");
  return structuredClone(value) as unknown as WorkspaceSeedManifest;
}

/** Prepare only. Persist the returned stage/reference before invoking its existing gated promotion. */
export function prepareWorkspaceSeed(stateRoot: string, workspace: string, manifest: unknown, expectedDigest: string,
  allowedFiles: readonly string[], content: ReadonlyMap<string, Uint8Array>, authorityBinding: string, authority: WorkspaceAuthority) {
  const selected = validateWorkspaceSeed(manifest, expectedDigest, allowedFiles);
  requireThat(/^[a-f0-9]{64}$/.test(authorityBinding) && content.size === selected.files.length, "workspace_seed_binding_invalid");
  const bytes = new Map<string, Buffer>();
  for (const file of selected.files) {
    const value = content.get(file.path);
    requireThat(value instanceof Uint8Array && value.byteLength === file.size && sha(value) === file.sha256, "workspace_seed_content_mismatch");
    bytes.set(file.path, Buffer.from(value));
  }
  const binding = digest({ kind: "workspace_seed", authority: authorityBinding, manifest: expectedDigest });
  const stage = WorkspaceStage.createFiles(stateRoot, workspace, selected.files.map(file => file.path), binding, authority);
  stage.assertPrepared();
  // Compare the copied baseline; the stage rechecks original identities/content at seal/promotion.
  for (const file of selected.files) {
    let fd: number;
    try { fd = openSync(join(stage.path, "tree", file.path), constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK); }
    catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") continue; throw error; }
    try {
      const stat = fstatSync(fd);
      requireThat(stat.isFile() && stat.size === file.size, "workspace_seed_existing_conflict");
      const existing = Buffer.alloc(file.size + 1); let n = 0;
      while (n < existing.length) { const count = readSync(fd, existing, n, existing.length - n, null); if (!count) break; n += count; }
      requireThat(n === file.size && sha(existing.subarray(0, n)) === file.sha256, "workspace_seed_existing_conflict");
    } finally { closeSync(fd); }
  }
  for (const file of selected.files) stage.writeSelectedFile(authority, file.path, bytes.get(file.path)!);
  const proposal = stage.seal(authority);
  return { stage, reference: stage.reference(), manifest_digest: expectedDigest, proposal };
}
