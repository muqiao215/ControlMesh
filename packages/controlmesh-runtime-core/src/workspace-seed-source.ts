import { constants, openSync, closeSync, readSync } from "node:fs";
import { join, relative } from "node:path";
import { createHash } from "node:crypto";
import type { RuntimeDatabase } from "./database";
import { directoryIdentity, snapshotReads } from "./providers/native-manifest";
import { digest, requireThat } from "./value";
import { validateWorkspaceSeed, type WorkspaceSeedManifest } from "./workspace-seed";
import { WorkspaceSeedInbox } from "./workspace-seed-inbox";
import type { WorkspaceAuthority } from "./workspace-stage";

/** Caller supplies an issued source scope; no paths or authority are taken from a worker request. */
export function freezeWorkspaceSeed(db: RuntimeDatabase, workspace: string, allowedFiles: readonly string[],
  authorityBinding: string, authority: WorkspaceAuthority) {
  requireThat(authority.constructor.name !== "AsyncFunction" && /^[a-f0-9]{64}$/.test(authorityBinding), "workspace_seed_binding_invalid");
  let called = false;
  return db.transaction(() => {
    const result = authority(() => {
      requireThat(!called, "workspace_authority_repeated"); called = true;
      const paths = [...allowedFiles].sort();
      const placeholder = { schema_version: "controlmesh.workspace_seed.v1", files: paths.map(path => ({ path, size: 0, sha256: "0".repeat(64) })) };
      validateWorkspaceSeed(placeholder, digest(placeholder), paths);
      const root = directoryIdentity(workspace); requireThat(root.path === workspace, "workspace_seed_source_not_canonical");
      const before = snapshotReads(workspace, paths.map(path => join(workspace, path)));
      const content = new Map<string, Buffer>();
      for (const file of before) {
        const fd = openSync(file.path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
        try {
          const bytes = Buffer.alloc(Number(file.size) + 1); let n = 0;
          while (n < bytes.length) { const read = readSync(fd, bytes, n, bytes.length - n, null); if (!read) break; n += read; }
          requireThat(n === Number(file.size) && createHash("sha256").update(bytes.subarray(0, n)).digest("hex") === file.sha256, "workspace_seed_source_changed");
          content.set(relative(workspace, file.path), bytes.subarray(0, n));
        } finally { closeSync(fd); }
      }
      requireThat(digest(root) === digest(directoryIdentity(workspace)) && digest(before) === digest(snapshotReads(workspace, before.map(file => file.path))), "workspace_seed_source_changed");
      const manifest: WorkspaceSeedManifest = { schema_version: "controlmesh.workspace_seed.v1", files: before.map(file => ({ path: relative(workspace, file.path), size: Number(file.size), sha256: file.sha256 })) };
      const manifestDigest = digest(manifest), binding = digest({ direction: "workspace_seed_source", authority: authorityBinding });
      const store = new WorkspaceSeedInbox(db, binding, manifest, manifestDigest, paths, authority); store.begin();
      for (const file of manifest.files) {
        const bytes = content.get(file.path)!;
        if (!bytes.length) store.put(file.path, 0, bytes);
        for (let offset = 0; offset < bytes.length; offset += 32 * 1024) store.put(file.path, offset, bytes.subarray(offset, offset + 32 * 1024));
      }
      return { binding, manifest, manifest_digest: manifestDigest };
    });
    requireThat(called && !(result instanceof Promise), "workspace_authority_must_be_synchronous"); return result;
  });
}
