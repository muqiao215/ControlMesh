import { afterEach, expect, spyOn, test } from "bun:test";
import * as fs from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { WorkspaceStage, type WorkspaceAuthority } from "../src/workspace-stage";
import { digest } from "../src/value";
import { RuntimeDatabase } from "../src/database";
import { RuntimeKernel, type Principal } from "../src/kernel";

const roots: string[] = [];
afterEach(() => { for (const root of roots.splice(0)) fs.rmSync(root, { recursive: true, force: true }); });
const authority: WorkspaceAuthority = run => run();
function fixture(all = false) {
  const root = fs.realpathSync(fs.mkdtempSync(join(tmpdir(), "cm-stage-test-"))); roots.push(root);
  const repo = join(root, "repo"), state = join(root, "state"); fs.mkdirSync(repo); fs.mkdirSync(state, { mode: 0o700 }); fs.mkdirSync(join(repo, "src"));
  fs.writeFileSync(join(repo, "PROJECT.md"), "# Current project\n");
  fs.writeFileSync(join(repo, "src/a.ts"), "export const before = 1;\n"); fs.writeFileSync(join(repo, "src/old.ts"), "delete me\n");
  const git = (...args: string[]) => {
    const result = Bun.spawnSync(["/usr/bin/git", "-C", repo, ...args], { env: { PATH: "/usr/bin:/bin", HOME: root, GIT_CONFIG_NOSYSTEM: "1", GIT_CONFIG_GLOBAL: "/dev/null" }, stdout: "pipe", stderr: "pipe" });
    if (result.exitCode !== 0) throw new Error(result.stderr.toString()); return result.stdout.toString().trim();
  };
  git("init", "-q"); git("config", "user.name", "fixture"); git("config", "user.email", "fixture@example.invalid"); git("add", "."); git("commit", "-qm", "fixture");
  const binding = digest("issued task/episode/workspace"), writeRoots = [all ? repo : join(repo, "src")];
  const create = () => WorkspaceStage.create(state, repo, writeRoots, binding, authority);
  return { root, repo, state, git, binding, writeRoots, create };
}
const stageFile = (stage: WorkspaceStage, relative: string) => join(stage.path, "tree", relative);

test("first native attachment checks durable prepared content and identity without rejecting later owned edits", () => {
  for (const mutate of ["edit", "replace", "new"]) {
    const f = fixture(), stage = f.create(), ref = stage.reference();
    expect(() => WorkspaceStage.open(stage.path, ref).assertPrepared()).not.toThrow();
    const path = stageFile(stage, "src/a.ts");
    if (mutate === "edit") fs.writeFileSync(path, "changed before native dispatch\n");
    if (mutate === "replace") { fs.writeFileSync(stageFile(stage, "replacement"), fs.readFileSync(path)); fs.renameSync(stageFile(stage, "replacement"), path); }
    if (mutate === "new") fs.writeFileSync(stageFile(stage, "src/injected.ts"), "unexpected input\n");
    expect(() => WorkspaceStage.open(stage.path, ref).assertPrepared()).toThrow("workspace_stage_prepared_changed");
    // The running controller checks the canonical source, not the now writable staged snapshot.
    expect(() => stage.assertSourceCurrent()).not.toThrow();
  }
});

test("dirty source is staged at original paths; create/edit/delete promotes once and survives reopen", () => {
  const f = fixture(true); fs.writeFileSync(join(f.repo, "src/a.ts"), "dirty baseline\n"); fs.chmodSync(join(f.repo, "src/a.ts"), 0o755);
  const stage = f.create(), ref = stage.reference();
  expect(stage.projection()).toEqual([{ source: join(stage.path, "tree"), target: f.repo, readonly: false },
    { source: join(f.repo, ".git"), target: join(f.repo, ".git"), readonly: true }]);
  expect(fs.readFileSync(stageFile(stage, "src/a.ts"), "utf8")).toBe("dirty baseline\n");
  fs.writeFileSync(stageFile(stage, "src/a.ts"), "accepted edit\n"); fs.rmSync(stageFile(stage, "src/old.ts"));
  fs.mkdirSync(stageFile(stage, "src/new")); fs.writeFileSync(stageFile(stage, "src/new/result.ts"), "created\n");
  const proposal = stage.seal(authority); expect(proposal.changed_paths).toEqual(["src/a.ts", "src/new/result.ts", "src/old.ts"]);
  expect(fs.readFileSync(join(f.repo, "src/a.ts"), "utf8")).toBe("dirty baseline\n");
  const result = stage.promote(authority, proposal.proposal_digest);
  expect(fs.readFileSync(join(f.repo, "src/a.ts"), "utf8")).toBe("accepted edit\n"); expect(fs.statSync(join(f.repo, "src/a.ts")).mode & 0o777).toBe(0o755);
  expect(fs.readFileSync(join(f.repo, "src/new/result.ts"), "utf8")).toBe("created\n"); expect(fs.existsSync(join(f.repo, "src/old.ts"))).toBe(false);
  expect(WorkspaceStage.open(stage.path, ref).promote(authority, proposal.proposal_digest)).toEqual(result);
});

test("an external canonical change blocks seal or promotion without overwriting parallel work", () => {
  for (const when of ["before-seal", "after-seal"]) {
    const f = fixture(), stage = f.create(); fs.writeFileSync(stageFile(stage, "src/a.ts"), "agent proposal\n");
    const proposal = when === "after-seal" ? stage.seal(authority) : null;
    fs.writeFileSync(join(f.repo, "src/a.ts"), "other developer\n");
    expect(() => proposal ? stage.promote(authority, proposal.proposal_digest) : stage.seal(authority)).toThrow("workspace_stage_source_changed");
    expect(fs.readFileSync(join(f.repo, "src/a.ts"), "utf8")).toBe("other developer\n");
  }
});

test("sealed content, original identity and Git HEAD changes revoke promotion", () => {
  for (const mutate of ["stage", "replace", "head", "blob"]) {
    const f = fixture(), stage = f.create(); fs.writeFileSync(stageFile(stage, "src/a.ts"), "new\n"); const proposal = stage.seal(authority);
    if (mutate === "stage") fs.writeFileSync(stageFile(stage, "src/a.ts"), "late native output\n");
    if (mutate === "replace") { const bytes = fs.readFileSync(join(f.repo, "src/a.ts")); fs.writeFileSync(join(f.root, "replacement"), bytes); fs.renameSync(join(f.root, "replacement"), join(f.repo, "src/a.ts")); }
    if (mutate === "head") f.git("commit", "--allow-empty", "-qm", "another commit");
    if (mutate === "blob") fs.writeFileSync(join(stage.path, "blobs", fs.readdirSync(join(stage.path, "blobs"))[0]), "tampered\n");
    expect(() => stage.promote(authority, proposal.proposal_digest)).toThrow();
    expect(fs.readFileSync(join(f.repo, "src/a.ts"), "utf8")).toBe("export const before = 1;\n");
  }
});

test("lost authority after one file leaves an explicit partial journal; new authority resumes the same proposal", () => {
  const f = fixture(), stage = f.create(), ref = stage.reference();
  fs.writeFileSync(stageFile(stage, "src/a.ts"), "one\n"); fs.writeFileSync(stageFile(stage, "src/old.ts"), "two\n");
  const proposal = stage.seal(authority); let calls = 0;
  const expired: WorkspaceAuthority = run => { if (++calls === 3) throw new Error("lease expired"); return run(); };
  expect(() => stage.promote(expired, proposal.proposal_digest)).toThrow("lease expired");
  expect(fs.readFileSync(join(f.repo, "src/a.ts"), "utf8")).toBe("one\n"); expect(fs.readFileSync(join(f.repo, "src/old.ts"), "utf8")).toBe("delete me\n");
  const state = JSON.parse(fs.readFileSync(join(stage.path, "record.json"), "utf8")); expect(state).toMatchObject({ phase: "applying", applied: 1 });
  WorkspaceStage.open(stage.path, ref).promote(authority, proposal.proposal_digest);
  expect(fs.readFileSync(join(f.repo, "src/old.ts"), "utf8")).toBe("two\n");
});

test("crash after rename but before receipt is reconciled without rewriting the native result", () => {
  const f = fixture(), stage = f.create(), ref = stage.reference(); fs.writeFileSync(stageFile(stage, "src/a.ts"), "one\n");
  const proposal = stage.seal(authority), original = fs.renameSync; let replacements = 0;
  const spy = spyOn(fs, "renameSync").mockImplementation((from, to) => {
    original(from, to); if (String(to).startsWith("/proc/self/fd/") && String(to).endsWith("/a.ts")) { replacements++; throw new Error("controller crash after rename"); }
  });
  try { expect(() => stage.promote(authority, proposal.proposal_digest)).toThrow("controller crash after rename"); }
  finally { spy.mockRestore(); }
  expect(replacements).toBe(1); const inode = fs.statSync(join(f.repo, "src/a.ts")).ino;
  WorkspaceStage.open(stage.path, ref).promote(authority, proposal.proposal_digest);
  expect(fs.statSync(join(f.repo, "src/a.ts")).ino).toBe(inode);
});

test("a partial temporary write is checked against the sealed bytes and resumed after process failure", () => {
  const f = fixture(), stage = f.create(), ref = stage.reference(); fs.writeFileSync(stageFile(stage, "src/a.ts"), "complete staged output\n");
  const proposal = stage.seal(authority), original = fs.writeSync; let interrupted = false;
  const intercept = ((...args: unknown[]) => {
    if (!interrupted && Buffer.isBuffer(args[1]) && fs.readlinkSync(`/proc/self/fd/${args[0]}`).includes("/.cm-write-")) {
      interrupted = true; original(args[0] as number, args[1], 0, 3, 0); throw new Error("partial temporary write");
    }
    return Reflect.apply(original, fs, args) as number;
  }) as typeof fs.writeSync;
  const spy = spyOn(fs, "writeSync").mockImplementation(intercept);
  try { expect(() => stage.promote(authority, proposal.proposal_digest)).toThrow("partial temporary write"); } finally { spy.mockRestore(); }
  expect(interrupted).toBe(true); expect(fs.readFileSync(join(f.repo, "src/a.ts"), "utf8")).toBe("export const before = 1;\n");
  WorkspaceStage.open(stage.path, ref).promote(authority, proposal.proposal_digest);
  expect(fs.readFileSync(join(f.repo, "src/a.ts"), "utf8")).toBe("complete staged output\n");
  expect(fs.readdirSync(join(f.repo, "src")).some(path => path.startsWith(".cm-write-"))).toBe(false);
});

test("descriptor-relative replacement cannot follow a parent swapped immediately before rename", () => {
  const f = fixture(), stage = f.create(); fs.writeFileSync(stageFile(stage, "src/a.ts"), "proposal\n"); const proposal = stage.seal(authority);
  fs.mkdirSync(join(f.root, "outside")); fs.writeFileSync(join(f.root, "outside/a.ts"), "outside\n");
  const original = fs.renameSync; let swapped = false;
  const spy = spyOn(fs, "renameSync").mockImplementation((from, to) => {
    if (!swapped && String(to).startsWith("/proc/self/fd/") && String(to).endsWith("/a.ts")) {
      swapped = true; original(join(f.repo, "src"), join(f.root, "detached")); fs.symlinkSync(join(f.root, "outside"), join(f.repo, "src"));
    }
    original(from, to);
  });
  try { expect(() => stage.promote(authority, proposal.proposal_digest)).toThrow(); } finally { spy.mockRestore(); }
  expect(swapped).toBe(true); expect(fs.readFileSync(join(f.root, "outside/a.ts"), "utf8")).toBe("outside\n");
  expect(fs.readFileSync(join(f.root, "detached/a.ts"), "utf8")).toBe("proposal\n");
});

test("real kernel lease expiry blocks promotion; trusted reconciliation applies the retained proposal without another execution", () => {
  const f = fixture(); let now = 1000;
  const db = new RuntimeDatabase(join(f.state, "runtime.sqlite"), () => now), kernel = new RuntimeKernel(db);
  const actor: Principal = { id: "operator", device_id: "local", origin: "human_request", scopes: ["task:create", "task:read", "task:execute", "task:reconcile", "task:admin"] };
  try {
    kernel.submit(actor, "submit", { task_id: "task", status: "waiting", chat_id: "fixture", repo_root: f.repo });
    const lease = kernel.claim(actor, "claim", "task", 1, 1000), gate: WorkspaceAuthority = run => kernel.withLease(actor, lease, run);
    const stage = WorkspaceStage.create(f.state, f.repo, f.writeRoots, digest(lease), gate), ref = stage.reference();
    kernel.start(actor, "start", lease); kernel.dispatchEffect(actor, "dispatch", lease, "write-effect", { fixture: true }, { stage_path: stage.path, stage_reference: ref });
    fs.writeFileSync(stageFile(stage, "src/a.ts"), "retained native result\n"); const proposal = stage.seal(gate);
    kernel.recordEffectObservation(actor, "observed", lease, "write-effect", { proposal_digest: proposal.proposal_digest });
    now = 3000; kernel.recoverExpired({ ...actor, origin: "recovery" });
    expect(() => stage.promote(gate, proposal.proposal_digest)).toThrow();
    expect(fs.readFileSync(join(f.repo, "src/a.ts"), "utf8")).toBe("export const before = 1;\n");
    const revision = kernel.inspect(actor, "task").revision, evidence = kernel.inspectReconciliation(actor, "task", revision, "write-effect");
    const binding = { episode_id: evidence.episode.episode_id, effect_id: "write-effect", manifest_digest: evidence.manifest_digest, observation_digest: evidence.observation_digest };
    const accepted = kernel.reconcileEffect(actor, "accept", "task", revision, binding, current => {
      const resumed = WorkspaceStage.open(current.manifest.stage_path as string, current.manifest.stage_reference as typeof ref);
      return resumed.promote(run => { kernel.inspectReconciliation(actor, "task", revision, "write-effect"); return run(); }, current.observation.proposal_digest as string);
    });
    expect(accepted.task.status).toBe("done"); expect(fs.readFileSync(join(f.repo, "src/a.ts"), "utf8")).toBe("retained native result\n");
    expect(db.sql.query("SELECT COUNT(*) AS n FROM effects").get()).toEqual({ n: 1 });
  } finally { db.close(); }
});

test("parallel changes after partial application remain conflicts and are never overwritten by recovery", () => {
  const f = fixture(), stage = f.create(), ref = stage.reference();
  for (const path of ["src/a.ts", "src/old.ts"]) fs.writeFileSync(stageFile(stage, path), "proposal\n");
  const proposal = stage.seal(authority); let calls = 0;
  expect(() => stage.promote(run => { if (++calls === 3) throw new Error("stop"); return run(); }, proposal.proposal_digest)).toThrow("stop");
  fs.writeFileSync(join(f.repo, "src/old.ts"), "parallel edit\n");
  expect(() => WorkspaceStage.open(stage.path, ref).promote(authority, proposal.proposal_digest)).toThrow("workspace_stage_publication_conflict");
  expect(fs.readFileSync(join(f.repo, "src/old.ts"), "utf8")).toBe("parallel edit\n");
});

test("contained existing links are preserved; new links and links outside the project cannot expand a proposal", () => {
  const f = fixture(true); fs.symlinkSync(join(f.repo, "src/a.ts"), join(f.repo, "alias"));
  const stage = f.create(); expect(stage.seal(authority).changed_paths).toEqual([]);
  const other = f.create(); fs.symlinkSync("a.ts", stageFile(other, "src/new-link")); expect(() => other.seal(authority)).toThrow();
  fs.symlinkSync(f.state, join(f.repo, "escape")); expect(f.create).toThrow("workspace_stage_link_outside_workspace");
});

test("replaced parent directories do not redirect promotion into unrelated files", () => {
  const f = fixture(), stage = f.create(); fs.writeFileSync(stageFile(stage, "src/a.ts"), "proposal\n"); const proposal = stage.seal(authority);
  fs.mkdirSync(join(f.root, "outside")); fs.writeFileSync(join(f.root, "outside/a.ts"), "outside\n");
  fs.renameSync(join(f.repo, "src"), join(f.repo, "saved-src")); fs.symlinkSync(join(f.root, "outside"), join(f.repo, "src"));
  expect(() => stage.promote(authority, proposal.proposal_digest)).toThrow();
  expect(fs.readFileSync(join(f.root, "outside/a.ts"), "utf8")).toBe("outside\n");
});

test("reopen binds the original immutable snapshot and a stale controller cannot advance the journal", () => {
  const f = fixture(), stage = f.create(), ref = stage.reference(), stale = WorkspaceStage.open(stage.path, ref);
  fs.writeFileSync(stageFile(stage, "src/a.ts"), "proposal\n"); const proposal = stage.seal(authority);
  expect(() => stale.promote(authority, proposal.proposal_digest)).toThrow("workspace_stage_changed");
  expect(() => WorkspaceStage.open(stage.path, { ...ref, basis_digest: "0".repeat(64) })).toThrow("workspace_stage_basis_changed");
});

test("invalid roots, special files, size limits and async authority fail before publishing source changes", () => {
  const f = fixture(); expect(() => WorkspaceStage.create(f.state, f.repo, [f.root], f.binding, authority)).toThrow("workspace_stage_root_outside_workspace");
  expect(() => WorkspaceStage.create(f.state, f.repo, f.writeRoots, f.binding, (async run => run()) as WorkspaceAuthority)).toThrow("workspace_authority_must_be_synchronous");
  const pipe = join(f.repo, "src/pipe"); expect(Bun.spawnSync(["/usr/bin/mkfifo", pipe]).exitCode).toBe(0);
  expect(f.create).toThrow("workspace_stage_regular_file_required"); fs.rmSync(pipe);
  const large = join(f.repo, "src/large"); fs.writeFileSync(large, Buffer.alloc(4 * 1024 * 1024 + 1)); expect(f.create).toThrow("workspace_stage_file_limit");
  expect(fs.readFileSync(join(f.repo, "src/a.ts"), "utf8")).toBe("export const before = 1;\n");
});
