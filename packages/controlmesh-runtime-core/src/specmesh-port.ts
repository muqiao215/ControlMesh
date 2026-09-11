import { existsSync, lstatSync, mkdtempSync, readdirSync, realpathSync, rmSync } from "node:fs";
import { isAbsolute, join, relative, sep } from "node:path";
import { tmpdir } from "node:os";
import { assertSpecMeshContract } from "@controlmesh/protocol/specmesh";
import { ProcessSupervisor, type ProcessAdmission } from "./process-supervisor";
import { directoryIdentity, snapshotReads } from "./providers/native-manifest";
import { decodeSnapshot } from "./migration";
import { digest, requireThat } from "./value";
import type { LocalTaskExecution } from "./local-task-runtime";

export type SpecMeshOperation = "inspect" | "check" | "prepare_handoff" | "verify_closeout";
export interface SpecMeshConfiguration { directory: string; python: string; task_path: string | null; timeout_ms?: number }
export interface SpecMeshResult {
  contract_version: "specmesh.port.v1-draft"; observed_head: string | null; status: "pass" | "blocked" | "unknown";
  references: { path: string; sha256: string; authority: "asserted_candidate" | "derived"; tracked: boolean; modified: boolean }[];
  findings: { code: string; severity: "info" | "warning" | "error"; path: string | null; message: string }[];
}
export interface SpecMeshObservation { result: SpecMeshResult; snapshot_digest: string; assertCurrent(): void }

/** Explicit trusted standalone plugin, with no access to native credentials or TaskHub files. */
export class SpecMeshPort {
  private readonly config: SpecMeshConfiguration;
  private readonly workspace: ReturnType<typeof directoryIdentity>;
  private readonly implementation: string;
  private stopping = false;
  private readonly active = new Map<AbortController, Promise<void>>();
  readonly binding_digest: string;
  constructor(config: SpecMeshConfiguration, workspace: string, private readonly current: () => void,
    private readonly supervisor = new ProcessSupervisor()) {
    this.config = structuredClone(config); this.workspace = directoryIdentity(workspace);
    requireThat(isAbsolute(config.directory) && realpathSync(config.directory) === config.directory
      && isAbsolute(config.python) && lstatSync(realpathSync(config.python)).isFile()
      && (config.task_path === null || this.relativePath(config.task_path))
      && Number.isInteger(config.timeout_ms ?? 15_000) && (config.timeout_ms ?? 15_000) >= 1000 && (config.timeout_ms ?? 15_000) <= 60_000,
      "invalid_specmesh_profile");
    this.implementation = this.codeIdentity();
    this.binding_digest = digest({ config, workspace: this.workspace, implementation: this.implementation });
    this.assertCurrent();
  }
  private relativePath(path: string): boolean {
    return typeof path === "string" && path.length > 0 && path.length <= 4096 && !isAbsolute(path)
      && !path.includes("\0") && !path.split(/[\\/]/).includes("..");
  }
  private codeIdentity(): string {
    const directory = join(this.config.directory, "specmesh_port");
    const files = readdirSync(directory, { recursive: true, withFileTypes: true })
      .filter(item => /\.(?:py|json)$/.test(item.name)).map(item => join(item.parentPath, item.name)).sort();
    requireThat(files.length >= 6 && files.length <= 64 && files.includes(join(directory, "snapshot.py"))
      && files.includes(join(directory, "git_reader.py")), "specmesh_snapshot_profile_required");
    const python = realpathSync(this.config.python), stat = lstatSync(python, { bigint: true });
    return digest({ root: directoryIdentity(this.config.directory), files: snapshotReads(this.config.directory, files),
      python: { path: python, device: String(stat.dev), inode: String(stat.ino), size: String(stat.size), modified: String(stat.mtimeNs), changed: String(stat.ctimeNs) } });
  }
  assertCurrent(): void {
    requireThat(!this.stopping, "specmesh_stopping");
    const checked: unknown = this.current();
    if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    requireThat(digest(directoryIdentity(this.workspace.path)) === digest(this.workspace) && this.codeIdentity() === this.implementation,
      "specmesh_profile_changed");
  }
  assertWorkspace(root: unknown): void {
    this.assertCurrent(); requireThat(typeof root === "string" && realpathSync(root) === this.workspace.path, "specmesh_task_workspace_mismatch");
  }
  async stop(): Promise<void> {
    this.stopping = true;
    for (const controller of this.active.keys()) controller.abort();
    await Promise.all(this.active.values());
  }
  private head(): string {
    const child = Bun.spawnSync(["/usr/bin/git", "--no-optional-locks", "--no-replace-objects", "-C", this.workspace.path, "rev-parse", "HEAD"],
      { env: { PATH: "/usr/bin:/bin", GIT_CONFIG_NOSYSTEM: "1", GIT_CONFIG_GLOBAL: "/dev/null", GIT_NO_LAZY_FETCH: "1", GIT_ALLOW_PROTOCOL: "" },
        timeout: 2000, stdout: "pipe", stderr: "pipe" });
    const head = child.stdout.toString().trim();
    requireThat(child.exitCode === 0 && /^(?:[a-f0-9]{40}|[a-f0-9]{64})$/.test(head), "specmesh_head_unavailable"); return head;
  }
  private capture(paths: string[]) {
    return paths.map(path => {
      requireThat(this.relativePath(path), "specmesh_reference_outside_scope");
      const absolute = join(this.workspace.path, path);
      if (!existsSync(absolute)) return { path, missing: true as const };
      const actual = realpathSync(absolute), scoped = relative(this.workspace.path, actual);
      requireThat(scoped !== ".." && !scoped.startsWith(`..${sep}`) && !isAbsolute(scoped), "specmesh_reference_outside_scope");
      const file = snapshotReads(this.workspace.path, [actual])[0];
      requireThat(Number(file.size) <= 256 * 1024, "specmesh_document_too_large");
      return { path, missing: false as const, file };
    });
  }
  async inspect(operation: SpecMeshOperation, admission: ProcessAdmission): Promise<SpecMeshObservation> {
    this.assertCurrent(); requireThat(this.active.size < 4, "specmesh_backpressure");
    const head = this.head(), cache = mkdtempSync(join(tmpdir(), "cm-specmesh-cache-"));
    const controller = new AbortController(); let finish!: () => void;
    this.active.set(controller, new Promise<void>(resolve => { finish = resolve; }));
    const signal = admission.signal ? AbortSignal.any([admission.signal, controller.signal]) : controller.signal;
    const assertCurrent = () => {
      this.assertCurrent(); const checked: unknown = admission.assertCurrent();
      if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
      requireThat(this.head() === head, "specmesh_head_changed");
    };
    const run = (args: string[], input?: unknown) => this.supervisor.run({ command: [this.config.python, "-B", "-s", "-m", "specmesh_port", ...args],
      cwd: this.config.directory, env: { PATH: "/usr/bin:/bin", PYTHONUTF8: "1", PYTHONNOUSERSITE: "1", PYTHONDONTWRITEBYTECODE: "1", PYTHONPYCACHEPREFIX: cache },
      timeout_ms: this.config.timeout_ms ?? 15_000, max_output_bytes: 1024 * 1024,
      ...(input === undefined ? {} : { stdin_text: JSON.stringify(input) }) }, { ...admission, signal, assertCurrent });
    try {
      const declared = await run(["--capabilities"]);
      requireThat(declared.reason === "exited" && declared.exit_code === 0, "specmesh_capabilities_unavailable");
      const capability = decodeSnapshot(Buffer.from(declared.stdout)).source;
      assertSpecMeshContract<{ supported: boolean }>("capabilities", capability);
      requireThat(capability.supported, "specmesh_profile_unsupported");
      const request = { contract_version: "specmesh.port.v1-draft", operation, repo_root: this.workspace.path,
        expected_head: head, task_path: this.config.task_path, mode: "read_only" };
      assertSpecMeshContract("request", request);
      const outcome = await run(["--allowed-root", this.workspace.path], request);
      requireThat(outcome.reason === "exited" && [0, 3].includes(outcome.exit_code!), "specmesh_process_failed");
      const result = decodeSnapshot(Buffer.from(outcome.stdout)).source;
      assertSpecMeshContract<SpecMeshResult>("result", result);
      requireThat(result.observed_head === head && (result.status === "pass" ? outcome.exit_code === 0 : outcome.exit_code === 3), "specmesh_result_conflict");
      requireThat(result.status !== "pass" || result.findings.every(item => item.severity !== "error"), "specmesh_result_conflict");
      const defaults = ["AGENTS.md", "PROJECT.md", "ARCHITECTURE.md", "DECISIONS.md", "docs/ARCHITECTURE.md", "docs/DECISIONS.md",
        ...(this.config.task_path ? ["task_plan.md", "findings.md", "progress.md", "acceptance.json"].map(name => join(this.config.task_path!, name)) : [])];
      const paths = [...new Set([...defaults, ...result.references.map(item => item.path), ...result.findings.flatMap(item => item.path ? [item.path] : [])])].sort();
      requireThat(paths.length <= 64 && new Set(result.references.map(item => item.path)).size === result.references.length, "specmesh_reference_limit");
      const files = this.capture(paths);
      for (const item of result.references) {
        const observed = files.find(file => file.path === item.path);
        requireThat(observed && !observed.missing && observed.file!.sha256 === item.sha256, "specmesh_reference_changed");
      }
      if (result.status === "pass") for (const path of ["AGENTS.md", "PROJECT.md", ...(this.config.task_path
        ? ["task_plan.md", "findings.md", "progress.md"].map(name => join(this.config.task_path!, name)) : [])])
        requireThat(result.references.some(item => item.path === path), "specmesh_required_reference_missing");
      assertCurrent();
      const resultIdentity = digest(result);
      const snapshot_digest = digest({ head, task_path: this.config.task_path, files, result });
      return { result, snapshot_digest, assertCurrent: () => { this.assertCurrent();
        requireThat(digest(result) === resultIdentity && this.head() === head && digest(this.capture(paths)) === digest(files), "specmesh_snapshot_changed"); } };
    } finally { this.active.delete(controller); finish(); rmSync(cache, { recursive: true, force: true }); }
  }
  bind(execution: LocalTaskExecution, requiredReads: readonly string[]): LocalTaskExecution {
    let observation: SpecMeshObservation | undefined;
    const synchronous = (operation: () => void) => { const response: unknown = operation();
      if (response !== undefined) { void Promise.resolve(response).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); } };
    return { binding_digest: digest({ execution: execution.binding_digest, specmesh: this.binding_digest }),
      assertCurrent: () => { this.assertCurrent(); synchronous(() => execution.assertCurrent()); observation?.assertCurrent(); },
      assertPublicationAuthority: () => { this.assertCurrent();
        synchronous(() => execution.assertPublicationAuthority ? execution.assertPublicationAuthority() : execution.assertCurrent()); },
      ensureReady: async (requestId, context) => {
        observation = await this.inspect("check", context);
        requireThat(observation.result.status === "pass", "specmesh_start_gate_blocked");
        // Project assertions cannot widen native permissions. The trusted profile must already
        // require these reads, so the Agent actually consumes its current continuity documents.
        const required = new Set(requiredReads.map(path => realpathSync(path)));
        requireThat(observation.result.references.every(item => required.has(realpathSync(join(this.workspace.path, item.path)))),
          "specmesh_context_reads_not_issued");
        return execution.ensureReady(requestId, context);
      },
      execute: (lease, context) => { requireThat(observation?.result.status === "pass", "specmesh_start_gate_required");
        observation.assertCurrent(); return execution.execute(lease, { ...context, verifyPublication: async assertPublished => {
          const assertCurrent = () => { (context.assertPublicationAuthority ?? context.assertCurrent)(); assertPublished(); };
          const next = await this.inspect("check", { ...context, assertCurrent });
          requireThat(next.result.status === "pass", "specmesh_publication_gate_blocked");
          const required = new Set(requiredReads);
          requireThat(next.result.references.every(item => required.has(join(this.workspace.path, item.path))), "specmesh_context_reads_not_issued");
          assertCurrent(); next.assertCurrent(); observation = next;
          return { specmesh: { snapshot_digest: next.snapshot_digest, status: "pass", closeout_verified: false } };
        } }); },
    };
  }
}
