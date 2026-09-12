import { test, expect } from "bun:test";
import { Database } from "bun:sqlite";
import { createHash } from "node:crypto";
import { mkdtempSync, mkdirSync, rmSync, readFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { RuntimeDatabase } from "../src/database";
import { WorkspaceSeedInbox } from "../src/workspace-seed-inbox";
import { digest } from "../src/value";

test("seed chunks and prepared publication survive database reopen without overwriting or duplication", () => {
  const root = mkdtempSync(join(tmpdir(), "cm-seed-inbox-")), state = join(root, "state"), workspace = join(root, "workspace"), path = join(root, "runtime.sqlite");
  mkdirSync(state, { mode: 0o700 }); mkdirSync(workspace);
  let db = new RuntimeDatabase(path), allowed = true;
  const bytes = Buffer.from("initial source bytes🙂"), manifest = { schema_version: "controlmesh.workspace_seed.v1", files: [{ path: "PROJECT.md", size: bytes.length, sha256: createHash("sha256").update(bytes).digest("hex") }] };
  const create = (binding = digest("assignment")) => new WorkspaceSeedInbox(db, binding, manifest, digest(manifest), ["PROJECT.md"], run => { if (!allowed) throw new Error("revoked"); return run(); });
  try {
    let inbox = create(); inbox.begin(); inbox.begin();
    expect(inbox.put("PROJECT.md", 0, bytes.subarray(0, 4))).toEqual({ next_offset: 4 });
    expect(() => inbox.prepare(state, workspace)).toThrow("workspace_seed_incomplete");
    expect(() => inbox.put("PROJECT.md", 0, Buffer.from("oops"))).toThrow("workspace_seed_chunk_conflict");
    expect(() => inbox.put("PROJECT.md", 8, bytes.subarray(8))).toThrow("workspace_seed_offset_mismatch");
    db.close(); db = new RuntimeDatabase(path); inbox = create();
    expect(inbox.status().files[0]).toMatchObject({ received: 4, complete: false });
    expect(inbox.put("PROJECT.md", 0, bytes.subarray(0, 4))).toEqual({ next_offset: 4 });
    const corrupt = Buffer.from(bytes.subarray(4)); corrupt[0] = 0;
    expect(() => inbox.put("PROJECT.md", 4, corrupt)).toThrow("workspace_seed_content_mismatch");
    expect(inbox.status().files[0]?.received).toBe(4);
    inbox.put("PROJECT.md", 4, bytes.subarray(4));
    expect(inbox.status().files[0]?.complete).toBe(true);
    const proposal = inbox.prepare(state, workspace); expect(existsSync(join(workspace, "PROJECT.md"))).toBe(false);
    db.close(); db = new RuntimeDatabase(path); inbox = create();
    expect(inbox.prepare(state, workspace).proposal_digest).toBe(proposal.proposal_digest);
    const other = join(root, "other"); mkdirSync(other);
    expect(() => inbox.prepare(state, other)).toThrow("workspace_seed_destination_changed");
    allowed = false; expect(() => inbox.promote()).toThrow("revoked"); expect(existsSync(join(workspace, "PROJECT.md"))).toBe(false);
    allowed = true; inbox.promote(); expect(readFileSync(join(workspace, "PROJECT.md"))).toEqual(bytes);
    expect(inbox.promote().proposal_digest).toBe(proposal.proposal_digest);
    expect(() => create(digest("other assignment")).status()).toThrow("workspace_seed_transfer_changed");
  } finally { db.close(); rmSync(root, { recursive: true, force: true }); }
});

test("schema 28 upgrade adds the private seed inbox and retains existing runtime metadata", () => {
  const root = mkdtempSync(join(tmpdir(), "cm-seed-migration-")), path = join(root, "runtime.sqlite");
  try {
    const current = new RuntimeDatabase(path); current.sql.query("INSERT INTO meta VALUES ('seed-upgrade-marker','kept')").run(); current.close();
    const old = new Database(path); old.exec("DROP TABLE workspace_seed_files; DROP TABLE workspace_seed_transfers; PRAGMA user_version=28;"); old.close();
    const upgraded = new RuntimeDatabase(path);
    try {
      expect(upgraded.sql.query("PRAGMA user_version").get()).toEqual({ user_version: 29 });
      expect(upgraded.sql.query("SELECT value FROM meta WHERE key='seed-upgrade-marker'").get()).toEqual({ value: "kept" });
      expect(upgraded.sql.query("SELECT COUNT(*) AS n FROM workspace_seed_transfers").get()).toEqual({ n: 0 });
    } finally { upgraded.close(); }
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("empty files require an explicit receipt; manifest conflicts and declared storage exhaustion fail closed", () => {
  const db = new RuntimeDatabase(":memory:");
  const empty = { schema_version: "controlmesh.workspace_seed.v1", files: [{ path: "empty.txt", size: 0, sha256: createHash("sha256").update("").digest("hex") }] };
  const allowed = ["empty.txt", "a", "b", "c", "d"], binding = digest("zero");
  const create = (id: string, manifest: unknown) => new WorkspaceSeedInbox(db, digest(id), manifest, digest(manifest), allowed, run => run());
  try {
    const zero = new WorkspaceSeedInbox(db, binding, empty, digest(empty), allowed, run => run()); zero.begin();
    expect(zero.status().files[0]?.complete).toBe(false);
    zero.put("empty.txt", 0, Buffer.alloc(0)); zero.put("empty.txt", 0, Buffer.alloc(0));
    expect(zero.status().files[0]?.complete).toBe(true);
    const changed = { ...empty, files: [{ ...empty.files[0], size: 1 }] };
    expect(() => new WorkspaceSeedInbox(db, binding, changed, digest(changed), allowed, run => run()).begin()).toThrow("workspace_seed_transfer_changed");
    const large = { schema_version: "controlmesh.workspace_seed.v1", files: ["a", "b", "c", "d"].map(path => ({ path, size: 4 * 1024 * 1024, sha256: "a".repeat(64) })) };
    for (let i = 0; i < 16; i++) create(`large-${i}`, large).begin();
    expect(() => create("over-budget", large).begin()).toThrow("workspace_seed_inbox_full");
  } finally { db.close(); }
});
