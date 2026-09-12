import { test, expect } from "bun:test";
import { createHash } from "node:crypto";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync, existsSync, symlinkSync, chmodSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { prepareWorkspaceSeed, validateWorkspaceSeed } from "../src/workspace-seed";
import { WorkspaceStage, type WorkspaceAuthority } from "../src/workspace-stage";
import { digest } from "../src/value";
const authority: WorkspaceAuthority = run => run();
function setup() {
  const root = mkdtempSync(join(tmpdir(), "cm-seed-")), state = join(root, "state"), workspace = join(root, "project");
  mkdirSync(state, { mode: 0o700 }); mkdirSync(workspace);
  const content = new Map([["PROJECT.md", Buffer.from("current intent\n")], ["src/input.txt", Buffer.from("source 🙂\n")]]);
  const manifest = { schema_version: "controlmesh.workspace_seed.v1", files: [...content].map(([path, bytes]) => ({ path, size: bytes.length, sha256: createHash("sha256").update(bytes).digest("hex") })) };
  const prepare = () => prepareWorkspaceSeed(state, workspace, manifest, digest(manifest), [...content.keys()], content, digest("issued assignment"), authority);
  return { root, state, workspace, content, manifest, prepare };
}
test("seed preparation leaves the destination untouched and retained stage publishes exact authorized inputs", () => {
  const f = setup();
  try {
    writeFileSync(join(f.workspace, "PROJECT.md"), f.content.get("PROJECT.md")!);
    writeFileSync(join(f.workspace, "unrelated.txt"), "user work");
    const prepared = f.prepare();
    expect(existsSync(join(f.workspace, "src/input.txt"))).toBe(false);
    expect(prepared.proposal.changed_paths).toEqual(["src/input.txt"]);
    const reopened = WorkspaceStage.open(prepared.stage.path, prepared.reference);
    reopened.promote(authority, prepared.proposal.proposal_digest);
    expect(readFileSync(join(f.workspace, "src/input.txt"))).toEqual(f.content.get("src/input.txt")!);
    expect(readFileSync(join(f.workspace, "unrelated.txt"), "utf8")).toBe("user work");
    expect(f.prepare().proposal.changed_paths).toEqual([]);
  } finally { rmSync(f.root, { recursive: true, force: true }); }
});
test("seed refuses conflicting user content, corrupt bytes and unapproved paths", () => {
  const f = setup();
  try {
    writeFileSync(join(f.workspace, "PROJECT.md"), "newer local work");
    expect(f.prepare).toThrow("workspace_seed_existing_conflict");
    expect(readFileSync(join(f.workspace, "PROJECT.md"), "utf8")).toBe("newer local work");
    expect(existsSync(join(f.workspace, "src/input.txt"))).toBe(false);
    f.content.set("src/input.txt", Buffer.from("wrong bytes"));
    expect(f.prepare).toThrow("workspace_seed_content_mismatch");
    expect(() => validateWorkspaceSeed(f.manifest, digest(f.manifest), ["PROJECT.md"])).toThrow("workspace_seed_path_not_authorized");
    const bad = { ...f.manifest, files: [{ ...f.manifest.files[0], path: "../outside" }] };
    expect(() => validateWorkspaceSeed(bad, digest(bad), ["../outside"])).toThrow("workspace_seed_path_not_authorized");
  } finally { rmSync(f.root, { recursive: true, force: true }); }
});
test("seed cannot follow a destination symlink or overwrite a file created after preparation", () => {
  const f = setup();
  try {
    const outside = join(f.root, "outside"); mkdirSync(outside); symlinkSync(outside, join(f.workspace, "src"));
    expect(f.prepare).toThrow(); expect(existsSync(join(outside, "input.txt"))).toBe(false);
    rmSync(join(f.workspace, "src"));
    const prepared = f.prepare(); mkdirSync(join(f.workspace, "src")); writeFileSync(join(f.workspace, "src/input.txt"), "concurrent work");
    expect(() => prepared.stage.promote(authority, prepared.proposal.proposal_digest)).toThrow();
    expect(readFileSync(join(f.workspace, "src/input.txt"), "utf8")).toBe("concurrent work");
  } finally { rmSync(f.root, { recursive: true, force: true }); }
});

 test("seed preserves executable permissions and refuses mode conflicts or special bits", () => {
  const f = setup();
  try {
    const manifest = { ...f.manifest, files: f.manifest.files.map(file => ({ ...file, mode: 0o755 })) };
    const prepare = () => prepareWorkspaceSeed(f.state, f.workspace, manifest, digest(manifest), [...f.content.keys()], f.content, digest("mode-bound assignment"), authority);
    writeFileSync(join(f.workspace, "PROJECT.md"), f.content.get("PROJECT.md")!); chmodSync(join(f.workspace, "PROJECT.md"), 0o644);
    expect(prepare).toThrow("workspace_seed_existing_conflict");
    expect(statSync(join(f.workspace, "PROJECT.md")).mode & 0o777).toBe(0o644);
    chmodSync(join(f.workspace, "PROJECT.md"), 0o755);
    const prepared = prepare(); prepared.stage.promote(authority, prepared.proposal.proposal_digest);
    expect(statSync(join(f.workspace, "src/input.txt")).mode & 0o777).toBe(0o755);
    const bad = { ...manifest, files: manifest.files.map(file => ({ ...file, mode: 0o4755 })) };
    expect(() => validateWorkspaceSeed(bad, digest(bad), [...f.content.keys()])).toThrow("workspace_seed_mode_invalid");
  } finally { rmSync(f.root, { recursive: true, force: true }); }
});
