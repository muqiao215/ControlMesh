import * as fs from "node:fs";
import { createHash, randomUUID } from "node:crypto";
import { dirname, isAbsolute, join, relative } from "node:path";
import { canonical, digest, identifier, object, requireThat, RuntimeConflict } from "../value";
import { privateFile } from "../private-runtime-file";
import { WorkspaceStage, type WorkspaceAuthority } from "../workspace-stage";
import { contains } from "../containers/plan";
import { directoryIdentity, snapshotReads, type ReadSnapshot } from "./native-manifest";

export const nativeWorkspaceTools = ["controlmesh_read_file", "controlmesh_write_file", "controlmesh_edit_file"] as const;
export interface WorkspaceFilesConfiguration {
  workspace: string;
  read_files: readonly string[];
  tools: readonly (typeof nativeWorkspaceTools)[number][];
  journal_directory: string;
  binding_digest: string;
  stage?: WorkspaceStage;
}
interface FileValue { bytes: Buffer; sha256: string; mode: number; identity: string }
interface Intent { path: string; before_sha256: string | null; after_sha256: string; before_identity: string | null; size: number }
interface Receipt {
  schema_version: "controlmesh.workspace_tool_receipt.v1"; scope_digest: string; request_id: string;
  sequence: number;
  tool: string; input: Record<string, unknown>; state: "pending" | "done";
  intent: Intent | null; response: Record<string, unknown>;
}
const sha = (bytes: Uint8Array) => createHash("sha256").update(bytes).digest("hex");
const stamp = (s: fs.BigIntStats) => [s.dev, s.ino, s.size, s.mtimeNs, s.ctimeNs].map(String).join(":");
const hash = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const sync = (path: string) => { const fd = fs.openSync(path, fs.constants.O_RDONLY | fs.constants.O_DIRECTORY | fs.constants.O_NOFOLLOW); try { fs.fsyncSync(fd); } finally { fs.closeSync(fd); } };
function file(path: string, missing = false, anchored = false): FileValue | null {
  let before: fs.BigIntStats;
  try { before = fs.lstatSync(path, { bigint: true }); }
  catch (error) { if (missing && (error as NodeJS.ErrnoException).code === "ENOENT") return null; throw error; }
  requireThat(before.isFile() && before.size <= 4n * 1024n * 1024n && (anchored || fs.realpathSync(path) === path), "workspace_tool_file_unavailable");
  const fd = fs.openSync(path, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK);
  try {
    requireThat(stamp(fs.fstatSync(fd, { bigint: true })) === stamp(before), "workspace_tool_file_changed");
    const bytes = Buffer.alloc(Number(before.size) + 1); let count = 0, n: number;
    do { n = fs.readSync(fd, bytes, count, bytes.length - count, null); count += n; } while (n && count < bytes.length);
    requireThat(count === Number(before.size) && stamp(fs.fstatSync(fd, { bigint: true })) === stamp(before)
      && stamp(fs.lstatSync(path, { bigint: true })) === stamp(before) && (anchored || fs.realpathSync(path) === path), "workspace_tool_file_changed");
    const value = bytes.subarray(0, count);
    new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(value);
    return { bytes: value, sha256: sha(value), mode: Number(before.mode & 0o777n), identity: stamp(before) };
  } finally { fs.closeSync(fd); }
}

/** Private staged-file owner. Authority comes from the enclosing task/effect transaction,
 * never from MCP arguments. Receipts survive a provider or broker restart without replaying writes.
 */
export class NativeWorkspaceFiles {
  readonly scope: Record<string, unknown>;
  private readonly scopeDigest: string;
  private readonly reads: ReadSnapshot[];
  private readonly root: ReturnType<typeof directoryIdentity>;
  private readonly journal: ReturnType<typeof directoryIdentity>;
  private readonly stageScope?: ReturnType<WorkspaceStage["fileScope"]>;
  private readonly stageRoot?: ReturnType<typeof directoryIdentity>;
  private readonly tools: readonly string[];
  constructor(private readonly config: WorkspaceFilesConfiguration, private readonly authority: WorkspaceAuthority, private readonly assertCurrent: () => void) {
    requireThat(hash(config.binding_digest) && authority.constructor.name !== "AsyncFunction", "invalid_workspace_tool_binding");
    requireThat(config.tools.length > 0 && config.tools.length <= 3 && new Set(config.tools).size === config.tools.length
      && config.tools.every(tool => (nativeWorkspaceTools as readonly string[]).includes(tool)), "invalid_workspace_tool_grant");
    this.tools = [...config.tools];
    requireThat(config.stage || this.tools.every(tool => tool === "controlmesh_read_file"), "workspace_tool_write_requires_stage");
    this.root = directoryIdentity(config.workspace); this.journal = directoryIdentity(config.journal_directory);
    const journal = fs.lstatSync(config.journal_directory);
    requireThat(this.root.path === config.workspace && this.journal.path === config.journal_directory && journal.uid === process.getuid?.()
      && (journal.mode & 0o077) === 0 && !contains(config.workspace, config.journal_directory) && !contains(config.journal_directory, config.workspace), "workspace_tool_private_journal_required");
    this.reads = snapshotReads(config.workspace, config.read_files);
    this.stageScope = config.stage?.fileScope();
    this.stageRoot = this.stageScope ? directoryIdentity(this.stageScope.tree) : undefined;
    requireThat(!this.stageScope || this.stageScope.workspace === config.workspace, "workspace_tool_stage_mismatch");
    this.scope = { schema_version: "controlmesh.workspace_tool_scope.v1", binding_digest: config.binding_digest, workspace: this.root,
      reads: this.reads, tools: this.tools, journal: this.journal, stage: config.stage ? { path: config.stage.path, reference: config.stage.reference(), files: this.stageScope } : null };
    this.scopeDigest = digest(this.scope);
    this.owner(false);
  }
  private owner(create: boolean): void {
    const path = join(this.journal.path, "owner.json"), expected = canonical({ schema_version: "controlmesh.workspace_tool_journal.v1", scope_digest: this.scopeDigest });
    try { requireThat(privateFile(path).bytes.toString() === expected, "workspace_tool_journal_scope_changed"); }
    catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      requireThat(fs.readdirSync(this.journal.path).length === 0, "workspace_tool_journal_unowned");
      if (create) { fs.writeFileSync(path, expected, { mode: 0o600, flag: "wx" }); const fd = fs.openSync(path, fs.constants.O_RDONLY); try { fs.fsyncSync(fd); } finally { fs.closeSync(fd); } sync(this.journal.path); }
    }
  }
  private names(): string[] {
    const names = fs.readdirSync(this.journal.path);
    requireThat(names.length <= 1025 && names.every(name => name === "owner.json" || /^[a-f0-9]{64}\.json$/.test(name)
      || (/^[a-f0-9]{64}\.[a-f0-9-]{36}\.pending$/.test(name) && names.includes(name.slice(0, 64) + ".json"))), "workspace_tool_receipts_unresolved");
    return names.filter(name => /^[a-f0-9]{64}\.json$/.test(name));
  }
  private check(): void {
    this.assertCurrent();
    requireThat(digest(this.scope) === this.scopeDigest && digest(directoryIdentity(this.config.workspace)) === digest(this.root)
      && digest(directoryIdentity(this.config.journal_directory)) === digest(this.journal)
      && digest(this.config.tools) === digest(this.tools), "workspace_tool_scope_changed");
    this.owner(false);
    requireThat(digest([...this.config.read_files].sort()) === digest(this.reads.map(read => read.path).sort()), "workspace_tool_source_changed");
    for (const read of this.reads) {
      const stat = fs.lstatSync(read.path, { bigint: true });
      requireThat(stat.isFile() && fs.realpathSync(read.path) === read.path && String(stat.dev) === read.device && String(stat.ino) === read.inode
        && String(stat.size) === read.size && String(stat.mtimeNs) === read.modified_ns && String(stat.ctimeNs) === read.changed_ns, "workspace_tool_source_changed");
    }
    if (this.config.stage) {
      requireThat(digest(this.config.stage.fileScope()) === digest(this.stageScope)
        && digest(directoryIdentity(this.stageScope!.tree)) === digest(this.stageRoot)
        && digest(this.config.stage.reference()) === digest((this.scope.stage as { reference: unknown }).reference), "workspace_tool_stage_changed");
      this.config.stage.assertSourceCurrent();
    }
  }
  private gated<T>(run: () => T): T {
    let called = false;
    const result = this.authority(() => { requireThat(!called, "workspace_authority_repeated"); called = true; this.check(); return run(); });
    requireThat(called && !(result instanceof Promise), "workspace_authority_must_be_synchronous"); return result;
  }
  private location(input: unknown, write: boolean): { original: string; actual: string; path: string } {
    requireThat(typeof input === "string" && input.length > 0 && input.length <= 4096 && !/[\x00\r\n\\]/.test(input), "workspace_tool_path_invalid");
    requireThat(!input.split("/").some((part, index) => part === "." || part === ".." || part === ".git" || (part === "" && index !== 0)), "workspace_tool_path_invalid");
    const original = isAbsolute(input) ? input : join(this.root.path, input), path = relative(this.root.path, original);
    requireThat(contains(this.root.path, original) && original !== this.root.path && join(this.root.path, path) === original, "workspace_tool_path_outside_scope");
    const staged = this.stageScope?.roots.some(root => contains(root, original));
    requireThat(!(this.stageScope?.denied.some(root => contains(root, original))), "workspace_tool_path_denied");
    requireThat(write ? staged : staged || this.reads.some(read => read.path === original), "workspace_tool_path_not_granted");
    return { original, path, actual: staged ? join(this.stageScope!.tree, path) : original };
  }
  private receiptPath(requestId: string): string { identifier(requestId); return join(this.journal.path, `${digest([this.scopeDigest, requestId])}.json`); }
  private load(path: string): Receipt | null {
    try {
      const row: unknown = JSON.parse(privateFile(path).bytes.toString());
      requireThat(object(row) && row.schema_version === "controlmesh.workspace_tool_receipt.v1" && row.scope_digest === this.scopeDigest
        && typeof row.request_id === "string" && path === this.receiptPath(row.request_id) && ["pending", "done"].includes(String(row.state))
        && Number.isSafeInteger(row.sequence) && Number(row.sequence) > 0 && Number(row.sequence) <= 256
        && (nativeWorkspaceTools as readonly unknown[]).includes(row.tool) && object(row.input) && object(row.response)
        && (row.intent === null || (object(row.intent) && typeof row.intent.path === "string" && hash(row.intent.after_sha256)
          && (row.intent.before_sha256 === null || hash(row.intent.before_sha256)) && Number.isSafeInteger(row.intent.size)
          && Number(row.intent.size) >= 0 && Number(row.intent.size) <= 4 * 1024 * 1024)), "workspace_tool_receipt_changed");
      return row as unknown as Receipt;
    } catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return null; throw error; }
  }
  private save(path: string, row: Receipt): void {
    this.check(); const data = canonical(row); requireThat(Buffer.byteLength(data) <= 32768, "workspace_tool_receipt_limit");
    const temporary = path.slice(0, -5) + `.${randomUUID()}.pending`;
    const fd = fs.openSync(temporary, fs.constants.O_WRONLY | fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_NOFOLLOW, 0o600);
    try { fs.writeFileSync(fd, data); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
    fs.renameSync(temporary, path); sync(this.journal.path);
  }
  private readPage(path: string, current: FileValue, input: Record<string, unknown>): Record<string, unknown> {
    const offset = input.offset ?? 0;
    requireThat(Number.isSafeInteger(offset) && Number(offset) >= 0 && Number(offset) <= current.bytes.length, "workspace_tool_offset_invalid");
    requireThat((offset === 0 && input.expected_sha256 === undefined) || input.expected_sha256 === current.sha256, "workspace_tool_content_changed");
    let end = Math.min(current.bytes.length, Number(offset) + 2048), text: string;
    for (;;) {
      try { text = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(current.bytes.subarray(Number(offset), end)); break; }
      catch { requireThat(end > Number(offset) && Number(offset) + 2048 - end < 4, "workspace_tool_offset_invalid"); end--; }
    }
    const response = { ok: true, path, sha256: current.sha256, size: current.bytes.length, offset, next_offset: end, eof: end === current.bytes.length, content: text };
    requireThat(Buffer.byteLength(canonical(response)) <= 16384, "workspace_tool_response_limit"); return response;
  }
  call(tool: string, input: Record<string, unknown>): Record<string, unknown> {
    identifier(input.request_id);
    requireThat((nativeWorkspaceTools as readonly string[]).includes(tool) && Buffer.byteLength(canonical(input)) <= 16384, "invalid_workspace_tool");
    return this.gated(() => {
      requireThat(this.tools.includes(tool), "workspace_tool_not_granted");
      this.owner(true);
      const path = this.receiptPath(input.request_id as string), previous = this.load(path);
      if (previous) {
        requireThat(previous.tool === tool && canonical(previous.input) === canonical(input), "idempotency_conflict");
        requireThat(previous.state === "done", "workspace_tool_outcome_unknown"); return previous.response;
      }
      const names = this.names(); requireThat(names.length < 256, "workspace_tool_budget_exhausted");
      const receipt: Receipt = { schema_version: "controlmesh.workspace_tool_receipt.v1", scope_digest: this.scopeDigest,
        request_id: input.request_id as string, sequence: names.length + 1, tool, input, state: "pending", intent: null, response: {} };
      let bytes: Buffer | undefined, target: ReturnType<NativeWorkspaceFiles["location"]> | undefined, mode = 0o644;
      try {
        const write = tool !== "controlmesh_read_file", allowed = tool === "controlmesh_read_file" ? ["offset", "expected_sha256"] : tool === "controlmesh_write_file" ? ["content", "expected_sha256"] : ["old_text", "new_text", "expected_sha256"];
        requireThat(Object.keys(input).every(key => key === "request_id" || key === "path" || allowed.includes(key)), "unexpected_workspace_tool_argument");
        target = this.location(input.path, write);
        const current = file(target.actual, write);
        if (!write) { requireThat(current, "workspace_tool_file_unavailable"); receipt.response = this.readPage(target.path, current, input); }
        else {
          this.config.stage!.projection();
          requireThat(input.expected_sha256 === (current?.sha256 ?? null), "workspace_tool_content_changed");
          const small = (text: unknown): text is string => typeof text === "string" && Buffer.byteLength(text) <= 8192 && Buffer.from(text).toString() === text;
          if (tool === "controlmesh_write_file") { requireThat(small(input.content), "workspace_tool_content_limit"); bytes = Buffer.from(input.content); }
          else {
            requireThat(current && small(input.old_text) && input.old_text.length > 0 && small(input.new_text), "workspace_tool_edit_invalid");
            const text = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(current.bytes), index = text.indexOf(input.old_text);
            requireThat(index >= 0 && text.indexOf(input.old_text, index + 1) < 0, "workspace_tool_edit_ambiguous");
            bytes = Buffer.from(text.slice(0, index) + input.new_text + text.slice(index + input.old_text.length));
          }
          requireThat(bytes.length <= 4 * 1024 * 1024, "workspace_tool_file_limit"); mode = current?.mode ?? mode;
          receipt.intent = { path: target.path, before_sha256: current?.sha256 ?? null, after_sha256: sha(bytes), before_identity: current?.identity ?? null, size: bytes.length };
          receipt.response = { ok: true, path: target.path, sha256: sha(bytes), size: bytes.length, staged: true };
        }
      } catch (error) { receipt.response = { ok: false, error: error instanceof RuntimeConflict ? error.code : "workspace_tool_operation_failed" }; bytes = undefined; receipt.intent = null; }
      this.save(path, receipt);
      if (bytes) this.replace(target!, bytes, mode, receipt.intent!);
      receipt.state = "done"; this.save(path, receipt); return receipt.response;
    });
  }
  private replace(target: { path: string; actual: string }, bytes: Buffer, mode: number, intent: Intent): void {
    requireThat(process.platform === "linux", "workspace_tool_platform_unqualified");
    this.check(); this.config.stage!.projection();
    let parent = fs.openSync(this.stageScope!.tree, fs.constants.O_RDONLY | fs.constants.O_DIRECTORY | fs.constants.O_NOFOLLOW);
    try {
      const root = fs.fstatSync(parent, { bigint: true });
      requireThat(String(root.dev) === this.stageRoot!.device && String(root.ino) === this.stageRoot!.inode, "workspace_tool_stage_changed");
      for (const part of dirname(target.path).split("/").filter(part => part !== ".")) {
        const child = `/proc/self/fd/${parent}/${part}`;
        try { fs.mkdirSync(child, { mode: 0o755 }); fs.fsyncSync(parent); } catch (error) { if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error; }
        const next = fs.openSync(child, fs.constants.O_RDONLY | fs.constants.O_DIRECTORY | fs.constants.O_NOFOLLOW); fs.closeSync(parent); parent = next;
      }
      const destination = `/proc/self/fd/${parent}/${target.path.split("/").at(-1)}`;
      const current = file(destination, true, true);
      requireThat((current?.identity ?? null) === intent.before_identity && (current?.sha256 ?? null) === intent.before_sha256, "workspace_tool_content_changed");
      const temporary = `/proc/self/fd/${parent}/.cm-tool-${randomUUID()}`;
      const fd = fs.openSync(temporary, fs.constants.O_WRONLY | fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_NOFOLLOW, mode);
      try { fs.writeFileSync(fd, bytes); fs.fchmodSync(fd, mode); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
      this.check(); fs.renameSync(temporary, destination); fs.fsyncSync(parent);
      requireThat(file(target.actual)?.sha256 === intent.after_sha256, "workspace_tool_write_unproven");
    } finally { fs.closeSync(parent); }
  }
  /** An owner may reconcile an interrupted receipt only from the already staged result. */
  reconcile(requestId: string): Record<string, unknown> {
    return this.gated(() => {
      const path = this.receiptPath(requestId), row = this.load(path); requireThat(row, "workspace_tool_receipt_missing");
      if (row.state === "done") return row.response;
      if (row.intent) {
        const current = file(this.location(row.intent.path, true).actual);
        requireThat(current?.sha256 === row.intent.after_sha256 && current.bytes.length === row.intent.size, "workspace_tool_outcome_unknown");
      }
      row.state = "done"; this.save(path, row); return row.response;
    });
  }
  verify(native: readonly { tool: string; input: Record<string, unknown>; output: string }[], requiredReads: readonly string[]): { receipts_digest: string; read_files: string[]; written_files: string[] } {
    this.check();
    requireThat(digest(snapshotReads(this.config.workspace, this.config.read_files)) === digest(this.reads), "workspace_tool_source_changed");
    const names = this.names(); requireThat(names.length <= 256, "workspace_tool_receipts_unresolved");
    const rows = names.map(name => this.load(join(this.journal.path, name))!).sort((a, b) => a.sequence - b.sequence);
    requireThat(rows.every((row, index) => row?.state === "done" && row.sequence === index + 1), "workspace_tool_receipts_unresolved");
    const seen = new Set<string>();
    for (const call of native) {
      const saved = rows.find(row => row.tool === call.tool && canonical(row.input) === canonical(call.input));
      requireThat(saved && canonical(saved.response) === call.output, "workspace_tool_call_unproven"); seen.add(saved.request_id);
    }
    requireThat(rows.every(row => seen.has(row.request_id)), "workspace_tool_call_unobserved");
    const reads = new Set<string>(), writes = new Set<string>(), finalWrites = new Map<string, Intent>(), readPages = new Map<string, Record<string, unknown>[]>();
    for (const row of rows) if (row.response.ok === true) {
      if (row.intent) { writes.add(this.location(row.intent.path, true).original); finalWrites.set(row.intent.path, row.intent); }
      else if (row.tool === "controlmesh_read_file") {
        const path = this.location(row.response.path, false).original;
        const pages = readPages.get(path) ?? []; pages.push(row.response); readPages.set(path, pages);
      }
    }
    for (const [path, recorded] of readPages) {
      const location = this.location(path, false), current = file(location.actual)!;
      const pages = recorded.filter(page => page.sha256 === current.sha256).sort((a, b) => Number(a.offset) - Number(b.offset));
      let end = 0; for (const page of pages) { if (Number(page.offset) > end) break; end = Math.max(end, Number(page.next_offset)); }
      if (pages.length > 0 && end === current.bytes.length) reads.add(location.original);
    }
    for (const [path, intent] of finalWrites) {
      const current = file(this.location(path, true).actual);
      requireThat(current?.sha256 === intent.after_sha256 && current.bytes.length === intent.size, "workspace_tool_write_changed");
    }
    requireThat(requiredReads.every(path => reads.has(this.location(path, false).original)), "workspace_tool_required_read_missing");
    return { receipts_digest: digest(rows), read_files: [...reads].sort(), written_files: [...writes].sort() };
  }
}
