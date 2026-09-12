import { test, expect } from "bun:test";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync, symlinkSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { RuntimeDatabase } from "../src/database";
import { digest } from "../src/value";
import { freezeWorkspaceSeed } from "../src/workspace-seed-source";
import { WorkspaceSeedInbox } from "../src/workspace-seed-inbox";

test("frozen source transfers across two persistent stores and excludes unselected files", () => {
  const root = mkdtempSync(join(tmpdir(), "cm-seed-source-")), source = join(root, "source"), target = join(root, "target"), state = join(root, "state");
  for (const path of [source, target, state]) mkdirSync(path, { mode: 0o700 });
  let from = new RuntimeDatabase(join(root, "sender.sqlite")), to = new RuntimeDatabase(join(root, "receiver.sqlite"));
  const paths = ["PROJECT.md", "source.bin"], bytes = Buffer.alloc(70000, 42), authority = <T>(run: () => T) => run();
  try {
    writeFileSync(join(source, "PROJECT.md"), "original intent"); writeFileSync(join(source, "source.bin"), bytes);
    writeFileSync(join(source, "private.env"), "unselected fixture data"); writeFileSync(join(target, "local.txt"), "preserve");
    const saved = freezeWorkspaceSeed(from, source, paths, digest("issued source"), authority);
    expect(saved.manifest.files.map(file => file.path)).toEqual(paths);
    expect(JSON.stringify(saved)).not.toContain(source);
    writeFileSync(join(source, "PROJECT.md"), "changed after freeze");
    expect(() => freezeWorkspaceSeed(from, source, paths, digest("issued source"), authority)).toThrow("workspace_seed_transfer_changed");
    from.close(); from = new RuntimeDatabase(join(root, "sender.sqlite"));
    const sender = new WorkspaceSeedInbox(from, saved.binding, saved.manifest, saved.manifest_digest, paths, authority);
    let receiver = new WorkspaceSeedInbox(to, digest("issued receiver"), saved.manifest, saved.manifest_digest, paths, authority); receiver.begin();
    for (const file of saved.manifest.files) {
      let offset = 0;
      do {
        const chunk = sender.read(file.path, offset); expect(Buffer.from(chunk.content_base64, "base64").length).toBeLessThanOrEqual(32768);
        const receipt = receiver.put(file.path, offset, Buffer.from(chunk.content_base64, "base64")); offset = receipt.next_offset;
        // A receiver process can reopen between arbitrary chunks.
        to.close(); to = new RuntimeDatabase(join(root, "receiver.sqlite"));
        receiver = new WorkspaceSeedInbox(to, digest("issued receiver"), saved.manifest, saved.manifest_digest, paths, authority);
      } while (offset < file.size);
    }
    receiver.prepare(state, target); receiver.promote();
    expect(readFileSync(join(target, "PROJECT.md"), "utf8")).toBe("original intent");
    expect(readFileSync(join(target, "source.bin"))).toEqual(bytes);
    expect(readFileSync(join(target, "local.txt"), "utf8")).toBe("preserve");
    expect(() => sender.read("private.env")).toThrow("workspace_seed_read_invalid");
    expect(readFileSync(join(source, "PROJECT.md"), "utf8")).toBe("changed after freeze");
    from.sql.query("UPDATE workspace_seed_files SET content=? WHERE binding=? AND path='PROJECT.md'").run(Buffer.from("corrupt"), saved.binding);
    expect(() => sender.read("PROJECT.md")).toThrow("workspace_seed_store_corrupted");
  } finally { from.close(); to.close(); rmSync(root, { recursive: true, force: true }); }
});

test("source refuses symlinks, traversal and revoked authority before retaining bytes", () => {
  const root = mkdtempSync(join(tmpdir(), "cm-seed-source-refuse-")), source = join(root, "source"), db = new RuntimeDatabase(":memory:"); mkdirSync(source);
  try {
    writeFileSync(join(root, "outside"), "fixture outside"); symlinkSync(join(root, "outside"), join(source, "link"));
    expect(() => freezeWorkspaceSeed(db, source, ["link"], digest("source"), run => run())).toThrow();
    expect(() => freezeWorkspaceSeed(db, source, ["../outside"], digest("source"), run => run())).toThrow("workspace_seed_path_not_authorized");
    expect(() => freezeWorkspaceSeed(db, source, ["anything"], digest("source"), () => { throw new Error("revoked"); })).toThrow("revoked");
    expect(db.sql.query("SELECT COUNT(*) AS n FROM workspace_seed_transfers").get()).toEqual({ n: 0 });
  } finally { db.close(); rmSync(root, { recursive: true, force: true }); }
});
