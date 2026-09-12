import { createHash, randomUUID } from "node:crypto";
import { lstatSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { basename, dirname, isAbsolute, join } from "node:path";
import { tmpdir } from "node:os";
import { ContainerProcessSupervisor, type ContainerProcessSpec } from "../containers/process";
import { contains, planContainer, resourceMounts, type ContainerConfiguration } from "../containers/plan";
import type { ProcessAdmission, ProcessOutcome, ProcessSpec } from "../process-supervisor";
import { privateFile } from "../private-runtime-file";
import { canonical, digest, requireThat } from "../value";
import { assertNativeAgentConfiguration, type NativeAgentConfiguration } from "./native-agent-profile";
import { directoryIdentity, type DirectoryIdentity } from "./native-manifest";
import { ClaudeControlRunner, assertClaudeControlEnvironment, type ClaudeControlEnvironment } from "./claude-control-runner";
import { validateClaudeControlInput, type ClaudeControlInput } from "./claude-control";
import { claudeProbeCommand, claudeProbeCredentialKeys } from "./claude-preflight";
import type { ExecutionContext } from "../execution-context";
import { enforceExecutionPolicy } from "../execution-policy";

export interface ClaudeContainerProbeProfile {
  container: Omit<ContainerConfiguration, "resources" | "workspace_layout">;
  executable: string;
}
export interface ClaudeContainerControlProfile extends ClaudeContainerProbeProfile {
  workspace: string;
  bun_executable: string;
  asset_directory: string;
  environment: ClaudeControlEnvironment;
  workspace_channel: NativeAgentConfiguration;
  communication_channel?: NativeAgentConfiguration;
}
export interface ClaudeContainerExecution {
  schema_version: "controlmesh.claude_container_execution.v1";
  runtime_digest: string;
  state: DirectoryIdentity;
  helper: { path: string; revision: string };
  version_execution: string;
  task_execution: string;
}

/** Only ClaudePreflight's fresh private HOME is writable; no task workspace/native session is mounted. */
export class ClaudeContainerProbeRunner {
  private readonly profile: ClaudeContainerProbeProfile;
  private readonly configuration: ContainerConfiguration;
  private readonly containers: Containers;
  private readonly initial: string;
  constructor(profile: ClaudeContainerProbeProfile, containers?: Containers) {
    this.profile = structuredClone(profile);
    this.configuration = { ...this.profile.container, workspace_layout: "native", resources: [{ source: this.profile.executable, readonly: true }] };
    this.initial = this.runtimeDigest();
    this.containers = containers ?? new ContainerProcessSupervisor(this.configuration);
  }
  runtimeDigest(): string {
    return digest({ schema_version: "controlmesh.claude_container_probe.v1", profile: this.profile,
      executable: executableIdentity(this.profile.executable), resources: resourceMounts(this.configuration) });
  }
  assertSource(context: ExecutionContext): void {
    requireThat(this.runtimeDigest() === this.initial, "claude_container_probe_profile_changed");
    enforceExecutionPolicy(context, true);
    requireThat(context.origin === "user" && ["local_foreground", "direct_message", "group_message"].includes(context.source_scope), "source_execution_floor_unavailable");
    // This readiness profile can only dispatch through the concrete container supervisor.
  }
  async run(spec: ProcessSpec, admission: ProcessAdmission): Promise<ProcessOutcome> {
    const version = canonical(spec.command) === canonical([this.profile.executable, "--version"]), index = spec.command.indexOf("--model");
    requireThat(spec.stdin_text === undefined && (version || (index >= 0 && canonical(spec.command) === canonical(claudeProbeCommand(this.profile.executable, spec.command[index + 1])))), "claude_container_probe_command_unqualified");
    requireThat(spec.cwd === spec.env.HOME && dirname(spec.cwd) === realpathSync(tmpdir()) && /^cm-claude-preflight-[A-Za-z0-9]+$/.test(basename(spec.cwd))
      && spec.env.CLAUDE_CONFIG_DIR === join(spec.cwd, "config") && spec.env.CLAUDE_CODE_SAFE_MODE === "1"
      && spec.env.CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC === "1" && spec.env.CLAUDE_CODE_MAX_OUTPUT_TOKENS === "128"
      && spec.env.MAX_THINKING_TOKENS === "0" && spec.env.PATH === "/usr/bin:/bin" && spec.env.LANG === "C.UTF-8", "claude_container_probe_environment_unqualified");
    const allowed = new Set([...claudeProbeCredentialKeys, "HOME", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_SAFE_MODE", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
      "CLAUDE_CODE_MAX_OUTPUT_TOKENS", "MAX_THINKING_TOKENS", "PATH", "LANG"]);
    requireThat(Object.keys(spec.env).every(key => allowed.has(key)), "claude_container_probe_environment_unqualified");
    const identity = digest(directoryIdentity(spec.cwd));
    const current = () => {
      const stat = lstatSync(spec.cwd);
      requireThat(this.runtimeDigest() === this.initial && realpathSync(spec.cwd) === spec.cwd && digest(directoryIdentity(spec.cwd)) === identity
        && stat.isDirectory() && stat.uid === process.getuid?.() && (stat.mode & 0o077) === 0, "claude_container_probe_profile_changed");
      const checked: unknown = admission.assertCurrent();
      if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    };
    current();
    return this.containers.run({ ...spec, execution_id: `claude-probe-${randomUUID()}`, writable_roots: [spec.cwd], no_network: false }, { ...admission, assertCurrent: current });
  }
}
interface Containers { run(spec: ContainerProcessSpec, admission: ProcessAdmission): Promise<ProcessOutcome> }
const helperSource = join(import.meta.dir, "claude-control-process.ts");
const sources = [helperSource, join(import.meta.dir, "claude-control.ts"), join(import.meta.dir, "opencode-events.ts"), join(import.meta.dir, "../value.ts")];
const sourceDigest = () => digest(sources.map(path => createHash("sha256").update(readFileSync(path)).digest("hex")));

function executableIdentity(path: string): string {
  requireThat(isAbsolute(path) && realpathSync(path) === path, "claude_container_executable_not_canonical");
  const stat = lstatSync(path, { bigint: true });
  requireThat(stat.isFile() && (stat.mode & 0o111n) !== 0n, "claude_container_executable_unavailable");
  return digest({ path, device: String(stat.dev), inode: String(stat.ino), size: String(stat.size), changed: String(stat.ctimeNs), modified: String(stat.mtimeNs) });
}

/** Concrete container launch only; its file/message brokers and publication owner stay outside. */
export class ClaudeContainerControlRunner {
  private readonly configuration: ContainerConfiguration;
  private readonly initial: string;
  private readonly containers: Containers;
  private readonly versionExecution = `claude-version-${randomUUID()}`;
  private readonly taskExecution = `claude-task-${randomUUID()}`;

  private constructor(private readonly profile: ClaudeContainerControlProfile, private readonly helper: string,
    private readonly helperRevision: string, private readonly sourceRevision: string, containers?: Containers) {
    const writable = [profile.environment.home, profile.environment.config_directory].filter((path, index, paths) =>
      paths.indexOf(path) === index && !paths.some(parent => parent !== path && contains(parent, path)));
    const resources = [
      ...writable.map(source => ({ source, readonly: false })),
      ...[profile.executable, profile.bun_executable, helper, profile.workspace_channel.directory,
        ...(profile.communication_channel ? [profile.communication_channel.directory] : [])].map(source => ({ source, readonly: true })),
    ];
    requireThat(resources.filter(resource => resource.readonly).every(resource => writable.every(root =>
      !contains(root, resource.source) && !contains(resource.source, root))), "claude_container_resource_state_overlap");
    this.configuration = { ...profile.container, workspace_layout: "native", resources };
    planContainer(this.configuration, profile.workspace, [], false);
    this.initial = this.runtimeDigest();
    this.containers = containers ?? new ContainerProcessSupervisor(this.configuration);
  }

  static async create(selected: ClaudeContainerControlProfile, containers?: Containers): Promise<ClaudeContainerControlRunner> {
    const profile = structuredClone(selected);
    assertClaudeControlEnvironment(profile.workspace, profile.environment);
    requireThat(directoryIdentity(profile.workspace).path === profile.workspace, "claude_container_workspace_not_canonical");
    const directory = lstatSync(profile.asset_directory);
    requireThat(realpathSync(profile.asset_directory) === profile.asset_directory && directory.isDirectory()
      && directory.uid === process.getuid?.() && (directory.mode & 0o077) === 0, "claude_container_private_assets_required");
    requireThat([profile.workspace, profile.environment.home, profile.environment.config_directory, profile.container.state_root].every(root =>
      !contains(root, profile.asset_directory) && !contains(profile.asset_directory, root)), "claude_container_assets_overlap_state");
    executableIdentity(profile.executable); executableIdentity(profile.bun_executable);
    requireThat(profile.bun_executable === realpathSync(process.execPath), "claude_container_bun_runtime_changed");
    requireThat(profile.workspace_channel.tool_profile === "workspace.v1"
      && (!profile.communication_channel || profile.communication_channel.tool_profile === undefined), "claude_container_channel_profile_mismatch");
    for (const channel of [profile.workspace_channel, ...(profile.communication_channel ? [profile.communication_channel] : [])]) {
      assertNativeAgentConfiguration(channel);
      requireThat(channel.node_executable === profile.container.node_executable, "claude_container_client_node_mismatch");
    }
    const sourceRevision = sourceDigest();
    const built = await Bun.build({ entrypoints: [helperSource], target: "bun", format: "esm" });
    requireThat(built.success && built.outputs.length === 1 && sourceDigest() === sourceRevision, "claude_container_helper_build_failed");
    const text = await built.outputs[0].text(), hash = createHash("sha256").update(text).digest("hex");
    const helper = join(profile.asset_directory, `${hash}.mjs`);
    try { writeFileSync(helper, text, { flag: "wx", mode: 0o600 }); }
    catch (error) { if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error; }
    const saved = privateFile(helper);
    requireThat(saved.bytes.toString() === text, "claude_container_helper_changed");
    return new ClaudeContainerControlRunner(profile, helper, saved.revision, sourceRevision, containers);
  }

  runtimeDigest(): string {
    requireThat(sourceDigest() === this.sourceRevision && privateFile(this.helper).revision === this.helperRevision, "claude_container_helper_changed");
    return digest({ schema_version: "controlmesh.claude_container_control.v1", profile: this.profile,
      binaries: [executableIdentity(this.profile.executable), executableIdentity(this.profile.bun_executable)],
      helper: this.helperRevision, resources: resourceMounts(this.configuration),
      workspace: directoryIdentity(this.profile.workspace),
      channels: [assertNativeAgentConfiguration(this.profile.workspace_channel),
        ...(this.profile.communication_channel ? [assertNativeAgentConfiguration(this.profile.communication_channel)] : [])] });
  }

  execution(): ClaudeContainerExecution {
    return { schema_version: "controlmesh.claude_container_execution.v1", runtime_digest: this.runtimeDigest(),
      state: directoryIdentity(this.profile.container.state_root), helper: { path: this.helper, revision: this.helperRevision },
      version_execution: this.versionExecution, task_execution: this.taskExecution };
  }

  async run(input: ClaudeControlInput, environment: ClaudeControlEnvironment, admission: ProcessAdmission, timeoutMs = 60000): Promise<ProcessOutcome> {
    validateClaudeControlInput(input);
    requireThat(input.workspace === this.profile.workspace && input.executable === this.profile.executable
      && digest(environment) === digest(this.profile.environment) && Boolean(input.communication_command) === Boolean(this.profile.communication_channel), "claude_container_input_mismatch");
    const channels = [[input.workspace_command, this.profile.workspace_channel],
      ...(input.communication_command ? [[input.communication_command, this.profile.communication_channel!]] : [])] as [string[], NativeAgentConfiguration][];
    const configurations = channels.map(([command, channel]) => {
      requireThat(command.length === 3 && command[0] === this.profile.container.node_executable && command[1] === join(channel.directory, "client.mjs")
        && dirname(command[2]) === channel.directory, "claude_container_channel_command_mismatch");
      return { path: command[2], revision: privateFile(command[2], 8192).revision };
    });
    const current = () => {
      requireThat(this.runtimeDigest() === this.initial && configurations.every(file => privateFile(file.path, 8192).revision === file.revision), "claude_container_profile_changed");
      const checked: unknown = admission.assertCurrent();
      if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    };
    current();
    const runner = new ClaudeControlRunner({ run: async (spec, authority) => {
      current();
      const version = canonical(spec.command) === canonical([this.profile.executable, "--version"]);
      requireThat(version || canonical(spec.command) === canonical([process.execPath, helperSource]), "claude_container_command_unqualified");
      return this.containers.run({ ...spec, command: version ? spec.command : [this.profile.bun_executable, this.helper],
        execution_id: version ? this.versionExecution : this.taskExecution, writable_roots: [], no_network: false }, authority);
    } });
    return runner.run(input, environment, { ...admission, assertCurrent: current }, timeoutMs);
  }
}
