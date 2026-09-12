import * as fs from "node:fs";
import { createHash, randomUUID } from "node:crypto";
import { dirname, isAbsolute, join, relative, sep } from "node:path";
import { canonical, digest, requireThat } from "./value";
import { privateFile } from "./private-runtime-file";
import { directoryIdentity, type DirectoryIdentity } from "./providers/native-manifest";
import { contains } from "./containers/plan";

const MAX_BYTES = 64 * 1024 * 1024, MAX_FILE = 4 * 1024 * 1024, MAX_ENTRIES = 2048;
type Identity = { device: string; inode: string; modified: string; changed: string };
type Entry = { path: string; kind: "file" | "directory" | "link"; mode: number; identity: Identity; size?: number; sha256?: string; link?: string };
type Snapshot = { entries: Entry[]; protected_git: Entry[] };
type Change = { path: string; before: Entry | null; after: Entry | null };
interface StageRecord {
  selection?: "files";
  schema_version: "controlmesh.workspace_stage.v1"; id: string; binding_digest: string;
  workspace: DirectoryIdentity; stage: DirectoryIdentity; roots: string[]; head: string | null; before: Snapshot; prepared: Snapshot;
  phase: "prepared" | "sealed" | "applying" | "applied";
  proposal: { after: Snapshot; changes: Change[]; digest: string } | null;
  applied: number; intent: { index: number; temporary: string | null } | null;
}
/** The runtime supplies a synchronous transaction, e.g. kernel.withLease. Never accept it from a request body. */
export type WorkspaceAuthority = <T>(operation: () => T) => T;
const identity = (s: fs.BigIntStats): Identity => ({ device: String(s.dev), inode: String(s.ino), modified: String(s.mtimeNs), changed: String(s.ctimeNs) });
const sha = (bytes: Buffer) => createHash("sha256").update(bytes).digest("hex");
const content = (entry: Entry | null | undefined) => entry ? { kind: entry.kind, mode: entry.mode, size: entry.size ?? null, sha256: entry.sha256 ?? null, link: entry.link ?? null } : null;
const same = (a: Entry | null | undefined, b: Entry | null | undefined) => digest(content(a)) === digest(content(b));
const files = (snapshot: Snapshot) => snapshot.entries.filter(entry => entry.kind !== "directory");
function syncDirectory(path: string): void { const fd = fs.openSync(path, fs.constants.O_RDONLY | fs.constants.O_DIRECTORY); try { fs.fsyncSync(fd); } finally { fs.closeSync(fd); } }
function safeRelative(path: string, empty = false): void {
  requireThat(typeof path === "string" && (empty || path.length > 0) && path.length <= 4096 && !isAbsolute(path)
    && !/[\x00\r\n]/.test(path) && !path.split(/[\\/]/).some(part => part === ".." || part === ".git"), "workspace_stage_path_invalid");
}
function regular(path: string, anchored = false): { bytes: Buffer; entry: Omit<Entry, "path"> } {
  requireThat(anchored || fs.realpathSync(path) === path, "workspace_stage_path_replaced");
  const before = fs.lstatSync(path, { bigint: true });
  requireThat(before.isFile() && before.size <= BigInt(MAX_FILE), "workspace_stage_file_limit");
  const fd = fs.openSync(path, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK);
  try {
    const held = fs.fstatSync(fd, { bigint: true });
    requireThat(held.isFile() && digest(identity(before)) === digest(identity(held)) && held.size === before.size, "workspace_stage_file_changed");
    const bytes = Buffer.alloc(Number(before.size) + 1); let count = 0;
    while (count < bytes.length) { const n = fs.readSync(fd, bytes, count, bytes.length - count, null); if (!n) break; count += n; }
    requireThat(count === Number(before.size) && (anchored || fs.realpathSync(path) === path)
      && digest(identity(before)) === digest(identity(fs.fstatSync(fd, { bigint: true })))
      && digest(identity(before)) === digest(identity(fs.lstatSync(path, { bigint: true }))), "workspace_stage_file_changed");
    const data = bytes.subarray(0, count);
    return { bytes: data, entry: { kind: "file", mode: Number(before.mode) & 0o777, identity: identity(before), size: count, sha256: sha(data) } };
  } finally { fs.closeSync(fd); }
}
function observe(root: string, roots: string[], copy?: (entry: Entry, bytes?: Buffer) => void, excluded?: string, trustedLinks?: Map<string, string>, selectedFiles = false): Snapshot {
  const anchor = directoryIdentity(root), entries: Entry[] = [], protectedGit: Entry[] = []; let total = 0;
  const walk = (path: string) => {
    if (path === excluded) return;
    requireThat(entries.length + protectedGit.length < MAX_ENTRIES, "workspace_stage_entry_limit");
    const absolute = join(root, path), stat = fs.lstatSync(absolute, { bigint: true });
    const entry: Entry = { path, kind: stat.isDirectory() ? "directory" : stat.isSymbolicLink() ? "link" : "file", mode: Number(stat.mode) & 0o777, identity: identity(stat) };
    if (path.split(sep).at(-1) === ".git") {
      requireThat(stat.isDirectory() || stat.isFile(), "workspace_git_metadata_invalid"); protectedGit.push(entry); return;
    }
    safeRelative(path, true);
    if (stat.isSymbolicLink()) {
      entry.link = fs.readlinkSync(absolute);
      requireThat(trustedLinks ? trustedLinks.get(path) === entry.link : contains(root, fs.realpathSync(absolute)), "workspace_stage_link_outside_workspace");
      entries.push(entry); copy?.(entry); return;
    }
    requireThat(fs.realpathSync(absolute) === absolute, "workspace_stage_path_replaced");
    if (stat.isDirectory()) {
      entries.push(entry); copy?.(entry);
      for (const name of fs.readdirSync(absolute).sort()) walk(join(path, name));
      requireThat(digest(identity(stat)) === digest(identity(fs.lstatSync(absolute, { bigint: true }))), "workspace_stage_directory_changed");
    } else {
      requireThat(stat.isFile(), "workspace_stage_regular_file_required");
      const read = regular(absolute), value: Entry = { path, ...read.entry }; total += read.bytes.length;
      requireThat(total <= MAX_BYTES, "workspace_stage_byte_limit"); entries.push(value); copy?.(value, read.bytes);
    }
  };
  for (const path of roots) {
    if (selectedFiles) {
      let absolute = root, missing = false;
      for (const [index, component] of path.split(sep).entries()) {
        absolute = join(absolute, component);
        let stat: fs.Stats;
        try { stat = fs.lstatSync(absolute); } catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") { missing = true; break; } throw error; }
        requireThat(!stat.isSymbolicLink() && fs.realpathSync(absolute) === absolute
          && (index === path.split(sep).length - 1 ? stat.isFile() : stat.isDirectory()), "workspace_stage_selected_path_changed");
      }
      if (missing) continue;
    }
    walk(path);
  }
  requireThat(digest(directoryIdentity(root)) === digest(anchor), "workspace_stage_root_changed");
  return { entries: entries.sort((a, b) => a.path.localeCompare(b.path, "en")), protected_git: protectedGit };
}
function head(root: string): string | null {
  const result = Bun.spawnSync(["/usr/bin/git", "--no-optional-locks", "--no-replace-objects", "-C", root, "rev-parse", "HEAD"],
    { timeout: 2000, stdout: "pipe", stderr: "pipe", env: { PATH: "/usr/bin:/bin", GIT_CONFIG_NOSYSTEM: "1", GIT_CONFIG_GLOBAL: "/dev/null", GIT_NO_LAZY_FETCH: "1", GIT_ALLOW_PROTOCOL: "" } });
  const value = result.stdout.toString().trim();
  if (result.exitCode === 128) return null;
  requireThat(result.exitCode === 0 && /^(?:[a-f0-9]{40}|[a-f0-9]{64})$/.test(value), "workspace_stage_head_unavailable"); return value;
}

/** Isolated proposal and durable per-file promotion; it never launches an Agent or claims an atomic multi-file commit. */
export class WorkspaceStage {
  private revision = "";
  private record: StageRecord;
  private readonly directory: DirectoryIdentity;
  private constructor(readonly path: string, binding: string) {
    this.directory = directoryIdentity(path);
    const directory = fs.lstatSync(path);
    requireThat(this.directory.path === path && directory.uid === process.getuid?.() && (directory.mode & 0o077) === 0, "workspace_stage_private_state_required");
    const loaded = privateFile(join(path, "record.json")); this.record = JSON.parse(loaded.bytes.toString()); this.revision = loaded.revision;
    const value = this.record;
    requireThat(value.selection === undefined || value.selection === "files", "workspace_stage_record_invalid");
    requireThat(value.schema_version === "controlmesh.workspace_stage.v1" && value.binding_digest === binding
      && /^[a-f0-9]{64}$/.test(binding) && ["prepared", "sealed", "applying", "applied"].includes(value.phase), "workspace_stage_binding_mismatch");
    requireThat(value.stage.path === join(path, "tree") && Array.isArray(value.roots) && value.roots.length > 0 && value.roots.length <= (value.selection === "files" ? 80 : 64)
      && Number.isSafeInteger(value.applied) && value.applied >= 0 && value.applied <= (value.proposal?.changes.length ?? 0), "workspace_stage_record_invalid");
    value.roots.forEach(root => safeRelative(root, true));
    this.assertCurrent();
  }
  private gated<T>(authority: WorkspaceAuthority, run: () => T): T {
    requireThat(authority.constructor.name !== "AsyncFunction", "workspace_authority_must_be_synchronous");
    let called = false; const result = authority(() => { requireThat(!called, "workspace_authority_repeated"); called = true; this.assertCurrent(); return run(); });
    requireThat(called && !(result instanceof Promise), "workspace_authority_must_be_synchronous"); return result;
  }
  /** Reject invalid local staging layout before spending a provider preflight. */
  static assertLocation(stateRoot: string, workspace: string): DirectoryIdentity {
    const root = directoryIdentity(workspace), state = directoryIdentity(stateRoot), stat = fs.lstatSync(state.path);
    requireThat(workspace === root.path && stateRoot === state.path && stat.uid === process.getuid?.() && (stat.mode & 0o077) === 0
      && !contains(workspace, stateRoot) && !contains(stateRoot, workspace), "workspace_stage_private_state_required");
    return root;
  }
  static create(stateRoot: string, workspace: string, writeRoots: readonly string[], binding: string, authority: WorkspaceAuthority): WorkspaceStage {
    return WorkspaceStage.createSelection(stateRoot, workspace, writeRoots, binding, authority, false);
  }
  /** Exact completion files, including absent destinations; unrelated repository trees are not copied. */
  static createFiles(stateRoot: string, workspace: string, paths: readonly string[], binding: string, authority: WorkspaceAuthority): WorkspaceStage {
    for (const path of paths) {
      safeRelative(path); requireThat(!path.includes("\\") && path.split("/").every(part => part && part !== "."), "workspace_stage_path_invalid");
    }
    return WorkspaceStage.createSelection(stateRoot, workspace, paths.map(path => join(workspace, path)), binding, authority, true);
  }
  private static createSelection(stateRoot: string, workspace: string, writeRoots: readonly string[], binding: string, authority: WorkspaceAuthority, selectedFiles: boolean): WorkspaceStage {
    requireThat(authority.constructor.name !== "AsyncFunction", "workspace_authority_must_be_synchronous");
    requireThat(isAbsolute(stateRoot) && /^[a-f0-9]{64}$/.test(binding), "workspace_stage_binding_mismatch");
    const root = WorkspaceStage.assertLocation(stateRoot, workspace);
    const selected = [...new Set(writeRoots)].sort();
    requireThat(selected.length > 0 && selected.length <= (selectedFiles ? 80 : 64), "workspace_stage_roots_required");
    for (const path of selected) {
      requireThat(isAbsolute(path) && contains(workspace, path) && (selectedFiles || directoryIdentity(path).path === path), "workspace_stage_root_outside_workspace");
      safeRelative(relative(workspace, path), true);
    }
    requireThat(!selectedFiles || selected.every(path => path !== workspace && !selected.some(parent => parent !== path && contains(parent, path))), "workspace_stage_overlapping_files");
    const roots = selected.filter(path => !selected.some(parent => parent !== path && contains(parent, path))).map(path => relative(workspace, path));
    let called = false;
    const created = authority(() => {
      requireThat(!called, "workspace_authority_repeated"); called = true;
      const path = fs.mkdtempSync(join(stateRoot, "workspace-stage-")); fs.chmodSync(path, 0o700);
      try {
        const stage = join(path, "tree"); fs.mkdirSync(stage, { mode: 0o700 }); fs.mkdirSync(join(path, "blobs"), { mode: 0o700 });
        const originalHead = head(workspace);
        const before = observe(workspace, roots, (entry, bytes) => {
          const target = join(stage, entry.path); fs.mkdirSync(dirname(target), { recursive: true, mode: 0o700 });
          if (entry.kind === "directory") fs.mkdirSync(target, { recursive: true, mode: entry.mode });
          else if (entry.kind === "link") fs.symlinkSync(entry.link!, target);
          else {
            const fd = fs.openSync(target, "wx", entry.mode);
            try { fs.writeFileSync(fd, bytes!); fs.fchmodSync(fd, entry.mode); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
          }
        }, undefined, undefined, selectedFiles);
        requireThat(head(workspace) === originalHead && digest(observe(workspace, roots, undefined, undefined, undefined, selectedFiles)) === digest(before), "workspace_stage_source_changed");
        for (const entry of before.protected_git) {
          const target = join(stage, entry.path); fs.mkdirSync(dirname(target), { recursive: true, mode: 0o700 });
          if (entry.kind === "directory") fs.mkdirSync(target, { mode: 0o700 });
          else { const fd = fs.openSync(target, "wx", 0o400); try { fs.fsyncSync(fd); } finally { fs.closeSync(fd); } }
        }
        const prepared = observe(stage, roots, undefined, undefined,
          new Map(before.entries.filter(entry => entry.kind === "link").map(entry => [entry.path, entry.link!])), selectedFiles);
        const directories = new Set([stage, join(path, "blobs")]);
        for (const entry of [...prepared.entries, ...prepared.protected_git]) {
          let directory = entry.kind === "directory" ? join(stage, entry.path) : dirname(join(stage, entry.path));
          while (contains(stage, directory)) { directories.add(directory); if (directory === stage) break; directory = dirname(directory); }
        }
        for (const directory of [...directories].sort((a, b) => b.length - a.length)) syncDirectory(directory);
        const record: StageRecord = { schema_version: "controlmesh.workspace_stage.v1", id: randomUUID(), binding_digest: binding, workspace: root,
          stage: directoryIdentity(stage), roots, head: originalHead, before, prepared, phase: "prepared", proposal: null, applied: 0, intent: null,
          ...(selectedFiles ? { selection: "files" as const } : {}) };
        fs.writeFileSync(join(path, "record.json"), canonical(record), { mode: 0o600, flag: "wx" });
        const result = new WorkspaceStage(path, binding); result.persist(); syncDirectory(stateRoot); result.assertPrepared(); return result;
      } catch (error) { fs.rmSync(path, { recursive: true, force: true }); throw error; }
    });
    requireThat(called && !(created instanceof Promise), "workspace_authority_must_be_synchronous"); return created;
  }
  static open(path: string, reference: { binding_digest: string; basis_digest: string }): WorkspaceStage {
    const stage = new WorkspaceStage(path, reference.binding_digest);
    requireThat(stage.reference().basis_digest === reference.basis_digest, "workspace_stage_basis_changed"); return stage;
  }
  reference(): { binding_digest: string; basis_digest: string } {
    this.assertCurrent(); const { schema_version, id, binding_digest, workspace, stage, roots, head, before, prepared } = this.record;
    return { binding_digest, basis_digest: digest({ schema_version, id, binding_digest, workspace, stage, roots, head, before, prepared,
      ...(this.record.selection ? { selection: this.record.selection } : {}) }) };
  }
  publicationState() { this.assertCurrent(); return { phase: this.record.phase, proposal_digest: this.record.proposal?.digest ?? null }; }
  /** Restrict a fresh publication to targets not already delivered by an accepted descendant. */
  assertSelectedSourceCurrent(paths: readonly string[]): void {
    this.assertCurrent();
    requireThat(this.record.selection === "files" && this.record.phase === "prepared" && paths.every(path => this.record.roots.includes(path))
      && head(this.record.workspace.path) === this.record.head, "workspace_stage_source_changed");
    const expected = { entries: this.record.before.entries.filter(entry => paths.includes(entry.path)), protected_git: [] };
    requireThat(digest(observe(this.record.workspace.path, [...paths], undefined, undefined, undefined, true)) === digest(expected), "workspace_stage_source_changed");
  }
  writeSelectedFile(authority: WorkspaceAuthority, path: string, bytes: Uint8Array, selectedMode?: number): void {
    this.gated(authority, () => {
      requireThat(this.record.selection === "files" && this.record.phase === "prepared" && this.record.roots.includes(path)
        && bytes.length <= MAX_FILE, "workspace_stage_file_not_selected");
      requireThat(selectedMode === undefined || (Number.isSafeInteger(selectedMode) && selectedMode >= 0 && selectedMode <= 0o777), "workspace_stage_mode_invalid");
      const mode = selectedMode ?? this.record.before.entries.find(entry => entry.path === path)?.mode ?? 0o644;
      let parent = fs.openSync(this.record.stage.path, fs.constants.O_RDONLY | fs.constants.O_DIRECTORY | fs.constants.O_NOFOLLOW);
      try {
        const root = fs.fstatSync(parent, { bigint: true });
        requireThat(String(root.dev) === this.record.stage.device && String(root.ino) === this.record.stage.inode, "workspace_stage_root_changed");
        for (const component of dirname(path).split(sep).filter(part => part && part !== ".")) {
          const target = `/proc/self/fd/${parent}/${component}`;
          try { fs.mkdirSync(target, { mode: 0o700 }); fs.fsyncSync(parent); } catch (error) { if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error; }
          const next = fs.openSync(target, fs.constants.O_RDONLY | fs.constants.O_DIRECTORY | fs.constants.O_NOFOLLOW);
          fs.closeSync(parent); parent = next;
        }
        const fd = fs.openSync(`/proc/self/fd/${parent}/${path.split(sep).at(-1)}`, fs.constants.O_WRONLY | fs.constants.O_CREAT | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK, mode);
        try {
          const stat = fs.fstatSync(fd); requireThat(stat.isFile() && stat.nlink === 1, "workspace_stage_path_replaced");
          fs.writeFileSync(fd, bytes); fs.ftruncateSync(fd, bytes.length); fs.fchmodSync(fd, mode); fs.fsyncSync(fd);
        } finally { fs.closeSync(fd); }
        fs.fsyncSync(parent);
      } finally { fs.closeSync(parent); }
    });
  }
  /** Check once before attaching a fresh native runner; subsequent native writes are expected to change the tree. */
  assertPrepared(): void {
    this.assertSourceCurrent();
    requireThat(this.record.phase === "prepared" && digest(this.staged()) === digest(this.record.prepared), "workspace_stage_prepared_changed");
  }
  assertCurrent(): void {
    requireThat(digest(directoryIdentity(this.path)) === digest(this.directory)
      && digest(directoryIdentity(this.record.workspace.path)) === digest(this.record.workspace)
      && digest(directoryIdentity(this.record.stage.path)) === digest(this.record.stage)
      && privateFile(join(this.path, "record.json")).revision === this.revision, "workspace_stage_changed");
  }
  assertSourceCurrent(): void {
    this.assertCurrent();
    requireThat(["prepared", "sealed"].includes(this.record.phase) && head(this.record.workspace.path) === this.record.head, "workspace_stage_source_changed");
    for (const entry of this.record.before.entries) {
      const path = join(this.record.workspace.path, entry.path), stat = fs.lstatSync(path, { bigint: true });
      requireThat(digest(identity(stat)) === digest(entry.identity) && (entry.kind === "link" ? stat.isSymbolicLink() && fs.readlinkSync(path) === entry.link
        : fs.realpathSync(path) === path && (entry.kind === "directory" ? stat.isDirectory() : stat.isFile())), "workspace_stage_source_changed");
    }
  }
  private persist(): void {
    const bytes = canonical(this.record); requireThat(Buffer.byteLength(bytes) <= 2 * 1024 * 1024, "workspace_stage_record_limit");
    const pending = join(this.path, `${randomUUID()}.pending`);
    const fd = fs.openSync(pending, fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_WRONLY | fs.constants.O_NOFOLLOW, 0o600);
    try { fs.writeFileSync(fd, bytes); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
    fs.renameSync(pending, join(this.path, "record.json")); syncDirectory(this.path);
    this.revision = privateFile(join(this.path, "record.json")).revision;
  }
  projection(): { source: string; target: string; readonly: boolean }[] {
    this.assertCurrent();
    requireThat(this.record.phase === "prepared", "workspace_stage_not_writable");
    return [...this.record.roots.map(path => ({ source: join(this.record.stage.path, path), target: join(this.record.workspace.path, path), readonly: false })),
      ...this.record.before.protected_git.map(entry => ({ source: join(this.record.workspace.path, entry.path), target: join(this.record.workspace.path, entry.path), readonly: true }))];
  }
  /** Read-only mapping for the scoped file owner, including retained-proposal inspection. */
  fileScope(): { workspace: string; tree: string; roots: string[]; denied: string[] } {
    this.assertCurrent();
    return { workspace: this.record.workspace.path, tree: this.record.stage.path,
      roots: this.record.roots.map(path => join(this.record.workspace.path, path)), denied: this.deniedPaths() };
  }
  deniedPaths(): string[] {
    this.assertCurrent();
    return [...this.record.before.entries.filter(entry => entry.kind === "link"), ...this.record.before.protected_git]
      .map(entry => join(this.record.workspace.path, entry.path));
  }
  assertProposal(expectedDigest: string): void {
    this.assertCurrent(); const proposal = this.record.proposal;
    requireThat(proposal && ["sealed", "applying", "applied"].includes(this.record.phase) && proposal.digest === expectedDigest
      && digest({ before: this.record.before, after: proposal.after, changes: proposal.changes }) === expectedDigest
      && digest(this.staged()) === digest(proposal.after), "workspace_stage_proposal_changed");
    for (const change of proposal.changes) if (change.after)
      requireThat(sha(regular(join(this.path, "blobs", change.after.sha256!)).bytes) === change.after.sha256, "workspace_stage_blob_changed");
    this.checkMixed();
  }
  assertApplied(expectedDigest: string): void {
    this.assertProposal(expectedDigest);
    requireThat(this.record.phase === "applied" && this.record.applied === this.record.proposal!.changes.length && this.record.intent === null,
      "workspace_stage_publication_incomplete");
  }
  proposalReceipt(): { proposal_digest: string; changed_paths: string[] } {
    this.assertCurrent(); requireThat(this.record.proposal, "workspace_stage_not_sealed");
    return { proposal_digest: this.record.proposal.digest, changed_paths: this.record.proposal.changes.map(change => change.path) };
  }
  seal(authority: WorkspaceAuthority): { stage_id: string; binding_digest: string; proposal_digest: string; changed_paths: string[] } {
    return this.gated(authority, () => {
      requireThat(this.record.phase === "prepared", "workspace_stage_not_prepared");
      requireThat(head(this.record.workspace.path) === this.record.head && digest(this.source()) === digest(this.record.before), "workspace_stage_source_changed");
      const before = new Map(files(this.record.before).map(entry => [entry.path, entry]));
      const after = this.staged(), result = new Map(files(after).map(entry => [entry.path, entry]));
      const changes = [...new Set([...before.keys(), ...result.keys()])].sort().flatMap(path => {
        const a = before.get(path) ?? null, b = result.get(path) ?? null;
        if (same(a, b)) return [];
        requireThat(b?.kind !== "link", "workspace_stage_new_link_unqualified");
        if (b) {
          const bytes = regular(join(this.record.stage.path, path)).bytes;
          requireThat(sha(bytes) === b.sha256, "workspace_stage_proposal_changed");
          const blob = join(this.path, "blobs", b.sha256!);
          if (!fs.existsSync(blob)) { const fd = fs.openSync(blob, "wx", 0o600); try { fs.writeFileSync(fd, bytes); fs.fsyncSync(fd); } finally { fs.closeSync(fd); } }
        }
        return [{ path, before: a, after: b }];
      });
      requireThat(digest(this.staged()) === digest(after), "workspace_stage_proposal_changed");
      syncDirectory(join(this.path, "blobs"));
      const proposal = { after, changes, digest: digest({ before: this.record.before, after, changes }) };
      this.record.proposal = proposal; this.record.phase = "sealed"; this.persist();
      return { stage_id: this.record.id, binding_digest: this.record.binding_digest, proposal_digest: proposal.digest, changed_paths: changes.map(change => change.path) };
    });
  }
  private staged(): Snapshot {
    return observe(this.record.stage.path, this.record.roots, undefined, undefined,
      new Map(this.record.before.entries.filter(entry => entry.kind === "link").map(entry => [entry.path, entry.link!])), this.record.selection === "files");
  }
  private source(): Snapshot { return observe(this.record.workspace.path, this.record.roots, undefined, this.record.intent?.temporary ?? undefined, undefined, this.record.selection === "files"); }
  private currentFiles(): Map<string, Entry> {
    requireThat(head(this.record.workspace.path) === this.record.head, "workspace_stage_head_changed");
    return new Map(files(this.source()).map(entry => [entry.path, entry]));
  }
  private checkMixed(): void {
    const proposal = this.record.proposal!, current = this.currentFiles(), expected = new Map(files(this.record.before).map(entry => [entry.path, entry]));
    for (const change of proposal.changes.slice(0, this.record.applied)) { if (change.after) expected.set(change.path, change.after); else expected.delete(change.path); }
    const pending = this.record.intent ? proposal.changes[this.record.intent.index] : undefined;
    if (pending && same(current.get(pending.path), pending.after)) { if (pending.after) expected.set(pending.path, pending.after); else expected.delete(pending.path); }
    requireThat(current.size === expected.size && [...expected].every(([path, entry]) => same(current.get(path), entry)), "workspace_stage_publication_conflict");
    // Untouched files retain identity, so an external edit/revert cannot masquerade as the captured baseline.
    const owned = new Set(proposal.changes.slice(0, this.record.applied).map(entry => entry.path)); if (pending) owned.add(pending.path);
    for (const entry of files(this.record.before)) if (!owned.has(entry.path))
      requireThat(digest(current.get(entry.path)?.identity) === digest(entry.identity), "workspace_stage_publication_conflict");
  }
  private replace(change: Change, temporary: string | null): void {
    requireThat(process.platform === "linux", "workspace_stage_promotion_platform_unverified");
    let parent = fs.openSync(this.record.workspace.path, fs.constants.O_RDONLY | fs.constants.O_DIRECTORY | fs.constants.O_NOFOLLOW);
    try {
    const root = fs.fstatSync(parent, { bigint: true });
    requireThat(String(root.dev) === this.record.workspace.device && String(root.ino) === this.record.workspace.inode, "workspace_stage_root_changed");
    for (const component of dirname(change.path).split(sep).filter(part => part && part !== ".")) {
      const path = `/proc/self/fd/${parent}/${component}`;
      try { fs.mkdirSync(path, { mode: 0o755 }); fs.fsyncSync(parent); }
      catch (error) { if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error; }
      const next = fs.openSync(path, fs.constants.O_RDONLY | fs.constants.O_DIRECTORY | fs.constants.O_NOFOLLOW);
      fs.closeSync(parent); parent = next;
    }
    const target = `/proc/self/fd/${parent}/${change.path.split(sep).at(-1)}`;
    if (!change.after) { fs.unlinkSync(target); fs.fsyncSync(parent); return; }
    const bytes = regular(join(this.path, "blobs", change.after.sha256!)).bytes;
    requireThat(sha(bytes) === change.after.sha256, "workspace_stage_blob_changed");
    const path = `/proc/self/fd/${parent}/${temporary!.split(sep).at(-1)}`;
    let fd: number;
    try { fd = fs.openSync(path, fs.constants.O_RDWR | fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_NOFOLLOW, 0o600); }
    catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
      const held = regular(path, true); requireThat(held.bytes.length <= bytes.length && held.bytes.equals(bytes.subarray(0, held.bytes.length)), "workspace_stage_temporary_conflict");
      fd = fs.openSync(path, fs.constants.O_RDWR | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK);
      const stat = fs.fstatSync(fd, { bigint: true });
      if (!stat.isFile() || stat.uid !== BigInt(process.getuid!()) || stat.nlink !== 1n || digest(identity(stat)) !== digest(held.entry.identity)) {
        fs.closeSync(fd); requireThat(false, "workspace_stage_temporary_conflict");
      }
    }
    try {
      let written = 0; while (written < bytes.length) { const n = fs.writeSync(fd, bytes, written, bytes.length - written, written); requireThat(n > 0, "workspace_stage_write_failed"); written += n; }
      fs.ftruncateSync(fd, bytes.length); fs.fchmodSync(fd, change.after.mode); fs.fsyncSync(fd);
    }
    finally { fs.closeSync(fd); }
    fs.renameSync(path, target); fs.fsyncSync(parent);
    } finally { fs.closeSync(parent); }
  }
  promote(authority: WorkspaceAuthority, expectedDigest: string): { proposal_digest: string; changed_paths: string[] } {
    this.gated(authority, () => {
      const proposal = this.record.proposal;
      requireThat(proposal && proposal.digest === expectedDigest && digest({ before: this.record.before, after: proposal.after, changes: proposal.changes }) === expectedDigest, "workspace_stage_proposal_changed");
      requireThat(digest(this.staged()) === digest(proposal.after), "workspace_stage_proposal_changed");
      for (const change of proposal.changes) if (change.after)
        requireThat(sha(regular(join(this.path, "blobs", change.after.sha256!)).bytes) === change.after.sha256, "workspace_stage_blob_changed");
      if (this.record.phase === "sealed") {
        requireThat(digest(this.source()) === digest(this.record.before), "workspace_stage_source_changed");
        this.record.phase = "applying"; this.persist();
      }
      requireThat(["applying", "applied"].includes(this.record.phase), "workspace_stage_not_sealed"); this.checkMixed();
    });
    while (this.record.applied < this.record.proposal!.changes.length) this.gated(authority, () => {
      this.checkMixed(); const index = this.record.applied, change = this.record.proposal!.changes[index];
      if (!this.record.intent) {
        this.record.intent = { index, temporary: change.after ? join(dirname(change.path), `.cm-write-${this.record.id}-${index}`) : null }; this.persist();
      }
      requireThat(this.record.intent.index === index, "workspace_stage_journal_conflict");
      if (!same(this.currentFiles().get(change.path), change.after)) this.replace(change, this.record.intent.temporary);
      this.record.applied++; this.record.intent = null; this.persist();
    });
    return this.gated(authority, () => {
      this.checkMixed(); this.record.phase = "applied"; this.persist();
      return { proposal_digest: expectedDigest, changed_paths: this.record.proposal!.changes.map(change => change.path) };
    });
  }
}
