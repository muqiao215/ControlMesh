import { createHash } from "node:crypto";
import { dirname } from "node:path";
import type { RuntimeDatabase } from "./database";
import { canonical, digest, requireThat } from "./value";
import { prepareWorkspaceSeed, validateWorkspaceSeed, type WorkspaceSeedManifest } from "./workspace-seed";
import { WorkspaceStage, type WorkspaceAuthority } from "./workspace-stage";

interface Transfer { manifest_digest: string; manifest: string; stage_path: string | null; reference: string | null; proposal_digest: string | null }
const sha = (bytes: Uint8Array) => createHash("sha256").update(bytes).digest("hex");

/** Private receiving state; the runtime must issue binding/allowlist/authority, never the remote payload. */
export class WorkspaceSeedInbox {
  private readonly manifest: WorkspaceSeedManifest;
  constructor(private readonly db: RuntimeDatabase, private readonly binding: string, manifest: unknown,
    private readonly expectedDigest: string, private readonly allowed: readonly string[], private readonly authority: WorkspaceAuthority) {
    requireThat(/^[a-f0-9]{64}$/.test(binding), "workspace_seed_binding_invalid");
    this.manifest = validateWorkspaceSeed(manifest, expectedDigest, allowed);
  }
  private gated<T>(run: () => T): T {
    requireThat(this.authority.constructor.name !== "AsyncFunction", "workspace_authority_must_be_synchronous");
    return this.db.transaction(() => {
      let called = false;
      const result = this.authority(() => { requireThat(!called, "workspace_authority_repeated"); called = true; return run(); });
      requireThat(called && !(result instanceof Promise), "workspace_authority_must_be_synchronous"); return result;
    });
  }
  private row(): Transfer {
    const row = this.db.sql.query("SELECT manifest_digest,manifest,stage_path,reference,proposal_digest FROM workspace_seed_transfers WHERE binding=?").get(this.binding) as Transfer | null;
    requireThat(row && row.manifest_digest === this.expectedDigest && row.manifest === canonical(this.manifest), "workspace_seed_transfer_changed"); return row;
  }
  begin() {
    return this.gated(() => {
      const prior = this.db.sql.query("SELECT 1 FROM workspace_seed_transfers WHERE binding=?").get(this.binding);
      if (prior) { this.row(); return; }
      const budget = this.db.sql.query("SELECT COUNT(*) AS n,COALESCE(SUM(size),0) AS size FROM workspace_seed_transfers").get() as { n: number; size: number };
      const size = this.manifest.files.reduce((sum, file) => sum + file.size, 0);
      requireThat(budget.n < 128 && budget.size + size <= 256 * 1024 * 1024, "workspace_seed_inbox_full");
      this.db.sql.query("INSERT INTO workspace_seed_transfers(binding,manifest_digest,manifest,size) VALUES (?,?,?,?)").run(this.binding, this.expectedDigest, canonical(this.manifest), size);
    });
  }
  put(path: string, offset: number, content: Uint8Array): { next_offset: number } {
    const file = this.manifest.files.find(file => file.path === path);
    requireThat(file && content instanceof Uint8Array && content.byteLength <= 32 * 1024 && Number.isSafeInteger(offset)
      && offset >= 0 && offset + content.byteLength <= file.size && (content.byteLength > 0 || file.size === 0), "workspace_seed_chunk_invalid");
    const bytes = Buffer.from(content);
    return this.gated(() => {
      const transfer = this.row();
      const row = this.db.sql.query("SELECT received,content FROM workspace_seed_files WHERE binding=? AND path=?").get(this.binding, path) as { received: number; content: Uint8Array } | null;
      const before = row ? Buffer.from(row.content) : Buffer.alloc(0), end = offset + bytes.length;
      requireThat(!row || row.received === before.length, "workspace_seed_store_corrupted");
      if (row && end <= before.length) {
        requireThat(before.subarray(offset, end).equals(bytes), "workspace_seed_chunk_conflict"); return { next_offset: end };
      }
      requireThat(!transfer.stage_path && offset === before.length, "workspace_seed_offset_mismatch");
      const next = Buffer.concat([before, bytes]);
      requireThat(next.length !== file.size || sha(next) === file.sha256, "workspace_seed_content_mismatch");
      this.db.sql.query("INSERT INTO workspace_seed_files VALUES (?,?,?,?) ON CONFLICT(binding,path) DO UPDATE SET received=excluded.received,content=excluded.content")
        .run(this.binding, path, next.length, next);
      return { next_offset: next.length };
    });
  }
  status() {
    return this.gated(() => {
      const row = this.row();
      return { manifest_digest: this.expectedDigest, prepared: Boolean(row.stage_path), files: this.manifest.files.map(file => {
        const saved = this.db.sql.query("SELECT received FROM workspace_seed_files WHERE binding=? AND path=?").get(this.binding, file.path) as { received: number } | null;
        return { path: file.path, size: file.size, received: saved?.received ?? 0, complete: Boolean(saved && saved.received === file.size) };
      }) };
    });
  }
  prepare(stateRoot: string, workspace: string) {
    return this.gated(() => {
      const row = this.row();
      if (row.stage_path) {
        const saved = this.retained(row);
        WorkspaceStage.assertLocation(stateRoot, workspace);
        requireThat(dirname(saved.stage.path) === stateRoot && saved.stage.fileScope().workspace === workspace, "workspace_seed_destination_changed");
        return saved;
      }
      const content = new Map<string, Uint8Array>();
      for (const file of this.manifest.files) {
        const saved = this.db.sql.query("SELECT received,content FROM workspace_seed_files WHERE binding=? AND path=?").get(this.binding, file.path) as { received: number; content: Uint8Array } | null;
        requireThat(saved && saved.received === file.size, "workspace_seed_incomplete"); content.set(file.path, saved.content);
      }
      const prepared = prepareWorkspaceSeed(stateRoot, workspace, this.manifest, this.expectedDigest, this.allowed, content, this.binding, this.authority);
      this.db.sql.query("UPDATE workspace_seed_transfers SET stage_path=?,reference=?,proposal_digest=? WHERE binding=?")
        .run(prepared.stage.path, canonical(prepared.reference), prepared.proposal.proposal_digest, this.binding);
      return { stage: prepared.stage, proposal_digest: prepared.proposal.proposal_digest };
    });
  }
  private retained(row: Transfer) {
    requireThat(row.stage_path && row.reference && row.proposal_digest, "workspace_seed_stage_missing");
    const reference = JSON.parse(row.reference);
    requireThat(reference.binding_digest === digest({ kind: "workspace_seed", authority: this.binding, manifest: this.expectedDigest }), "workspace_seed_binding_invalid");
    const stage = WorkspaceStage.open(row.stage_path, reference); stage.assertProposal(row.proposal_digest);
    return { stage, proposal_digest: row.proposal_digest };
  }
  promote() {
    return this.gated(() => { const saved = this.retained(this.row()); return saved.stage.promote(this.authority, saved.proposal_digest); });
  }
}
