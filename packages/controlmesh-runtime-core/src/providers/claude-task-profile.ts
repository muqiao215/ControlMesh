import { decodeTaskCompletion } from "../task-completion";
import { existsSync, lstatSync, readdirSync, realpathSync, statSync } from "node:fs";
import { isAbsolute, join } from "node:path";
import { contains, type ContainerConfiguration } from "../containers/plan";
import { decodeToolGrant, enforceProviderConfirmation } from "../execution-grants";
import { enforceNativeReadSource } from "../execution-policy";
import { digest, requireThat, type LegacyTask } from "../value";
import { WorkspaceStage } from "../workspace-stage";
import { nativeWorkspaceTools } from "./native-workspace-files";
import { directoryIdentity } from "./native-manifest";
import { registeredReads, writeRoots } from "./native-workspace";
import { assertClaudeControlEnvironment, type ClaudeControlEnvironment } from "./claude-control-runner";
import { ClaudeSessionStore, type ClaudeSessionRef } from "./claude-session";
import type { ProbeBinding } from "./preflight-cache";
import { decodeNativeAgentScope, nativeAgentTools } from "./native-agent-journal";
import { ClaudeContainerProbeRunner } from "./claude-container";

export interface ClaudeTaskConfiguration {
  executable: string;
  node_executable: string;
  state_home: string;
  environment: ClaudeControlEnvironment;
  model: string;
  workspace: string;
  read_files: readonly string[];
  required_reads: readonly string[];
  write_roots: readonly string[];
  workflow_binding?: string;
  timeout_ms?: number;
  max_turns?: number;
  communication?: { peer_tasks: string[]; parent_task: string | null };
  container?: Omit<ContainerConfiguration, "state_root" | "resources" | "workspace_layout">;
}
export function claudeContainerProfile(config: ClaudeTaskConfiguration) {
  requireThat(config.container !== undefined, "claude_container_not_registered");
  return { executable: config.executable, container: { ...config.container, state_root: join(config.state_home, "claude-containers") } };
}
export function claudeProbeBinding(config: ClaudeTaskConfiguration, deviceId: string): ProbeBinding {
  return { provider: "claude", device_id: deviceId, model: config.model, cli_version: "2.1.263", config_digest: digest({}),
    credential_revision: digest(config.environment.credentials), permission_profile: "claude-native-none-v1",
    ...(config.container ? { runtime_digest: new ClaudeContainerProbeRunner(claudeContainerProfile(config)).runtimeDigest() } : {}) };
}
export function assertClaudeTaskConfiguration(config: ClaudeTaskConfiguration): void {
  requireThat(typeof config.model === "string" && /^[^\s\x00]{1,256}$/.test(config.model)
    && Number.isSafeInteger(config.max_turns ?? 128) && (config.max_turns ?? 128) >= 1 && (config.max_turns ?? 128) <= 128
    && Number.isSafeInteger(config.timeout_ms ?? 60000) && (config.timeout_ms ?? 60000) >= 1000 && (config.timeout_ms ?? 60000) <= 300000,
  "invalid_claude_task_configuration");
  assertClaudeControlEnvironment(config.workspace, config.environment);
  requireThat(isAbsolute(config.node_executable) && !/[\x00\r\n]/.test(config.node_executable), "invalid_claude_task_executable");
  if (config.container) requireThat(config.node_executable === config.container.node_executable
    && Object.keys(config.container).every(key => ["docker", "socket", "image_id", "node_executable", "memory_mb", "pids", "cpus"].includes(key)), "invalid_claude_container_profile");
  for (const path of [config.executable, ...(config.container ? [] : [config.node_executable])]) {
    requireThat(isAbsolute(path) && !/[\x00\r\n]/.test(path), "invalid_claude_task_executable");
    const stat = statSync(path); requireThat(stat.isFile() && (stat.mode & 0o111) !== 0, "invalid_claude_task_executable");
  }
}

/** Resolve one native UUID only under the configured provider store. History/body paths have no authority. */
export function findClaudeSession(config: { environment: Pick<ClaudeTaskConfiguration["environment"], "config_directory"> }, deviceId: string, sessionId: string): ClaudeSessionStore | null {
  requireThat(/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(sessionId), "invalid_native_session_id");
  const root = join(config.environment.config_directory, "projects");
  if (!existsSync(root)) return null;
  requireThat(realpathSync(root) === root && lstatSync(root).isDirectory(), "claude_native_catalog_changed");
  const projects = readdirSync(root, { withFileTypes: true }); requireThat(projects.length <= 4096, "claude_native_catalog_limit");
  const matches: string[] = [];
  for (const entry of projects) if (entry.isDirectory()) {
    const path = join(root, entry.name, `${sessionId}.jsonl`);
    if (existsSync(path)) { requireThat(realpathSync(path) === path && lstatSync(path).isFile(), "claude_native_catalog_changed"); matches.push(path); }
  }
  requireThat(matches.length <= 1, "claude_native_session_ambiguous");
  return matches.length ? new ClaudeSessionStore(matches[0], deviceId) : null;
}

/** Literal file capability comes from trusted registration plus the current portable task grant. */
export function claudeTaskScope(config: ClaudeTaskConfiguration, task: LegacyTask, afterPublication = false, containerSource?: ClaudeContainerProbeRunner): {
  reads: string[]; required: string[]; roots: string[]; tools: (typeof nativeWorkspaceTools)[number][];
  communication?: { peer_tasks: string[]; parent_task: string | null };
} {
  requireThat(task.provider === "claude" && task.model === config.model && typeof task.repo_root === "string"
    && realpathSync(task.repo_root) === config.workspace && directoryIdentity(config.workspace).path === config.workspace, "claude_task_registration_mismatch");
  if (containerSource) requireThat(config.container && containerSource.runtimeDigest() === new ClaudeContainerProbeRunner(claudeContainerProfile(config)).runtimeDigest(), "claude_container_source_mismatch");
  enforceNativeReadSource(task.execution_context, containerSource ?? {});
  WorkspaceStage.assertLocation(config.state_home, config.workspace);
  const grant = decodeToolGrant(task.tool_grant); enforceProviderConfirmation("claude", grant);
  requireThat(grant.network_policy === "sandbox_default", "no_network_unenforceable");
  const roots = config.write_roots.length ? writeRoots(config.workspace, { roots: config.write_roots, ...(config.workflow_binding ? { workflow_binding: config.workflow_binding } : {}) }) : [];
  const reads = registeredReads(config.workspace, config.read_files, roots, afterPublication);
  const required = registeredReads(config.workspace, config.required_reads, roots, afterPublication);
  const completion = decodeTaskCompletion(task.completion_requirements);
  if (completion) for (const file of completion.files) {
    const path = join(config.workspace, file.path);
    requireThat(file.mode === "write" ? roots.some(root => contains(root, path)) : reads.includes(path), "completion_exceeds_file_grant");
  }
  requireThat(required.every(path => reads.includes(path)), "required_read_not_granted");
  const allows = grant.tool_allow.map(tool => tool.toLowerCase()), denies = grant.tool_deny.map(tool => tool.toLowerCase());
  if (config.communication) {
    decodeNativeAgentScope({ schema_version: "controlmesh.native_agent_scope.v1", ...config.communication, task_id: task.task_id,
      episode_id: "profile-validation", fence: 1, client_digest: "0".repeat(64) });
    requireThat(nativeAgentTools.every(tool => !denies.includes(tool) && (!allows.length || allows.includes(tool))), "communication_conflicts_task_grant");
  }
  const allowed = (operation: string) => !denies.includes(operation) && !denies.includes(`controlmesh_${operation}_file`)
    && (!allows.length || allows.includes(operation) || allows.includes(`controlmesh_${operation}_file`));
  const tools = nativeWorkspaceTools.filter(tool => allowed(tool.slice("controlmesh_".length, -"_file".length)) && (tool === "controlmesh_read_file" || roots.length > 0));
  if (completion) for (const file of completion.files) requireThat(file.mode === "read"
    ? tools.includes("controlmesh_read_file") : tools.includes("controlmesh_write_file") || tools.includes("controlmesh_edit_file"), "completion_exceeds_file_grant");
  requireThat(tools.length > 0 && (!required.length || tools.includes("controlmesh_read_file")), "claude_file_tools_not_granted");
  if (roots.length && grant.writable_roots.length) requireThat(roots.every(root => grant.writable_roots.some(path =>
    contains(realpathSync(isAbsolute(path) ? path : join(config.workspace, path)), root))), "native_write_roots_exceed_grant");
  if (!afterPublication) {
    const pages = required.reduce((sum, path) => sum + Math.max(1, Math.ceil(statSync(path).size / 2045)), 0);
    requireThat(pages <= 256 && (!roots.length || pages < 256), "claude_required_read_budget_exhausted");
  }
  return { reads, required, roots, tools, ...(config.communication ? { communication: structuredClone(config.communication) } : {}) };
}
export function validateClaudeTaskSession(config: ClaudeTaskConfiguration, deviceId: string, reference: ClaudeSessionRef): ClaudeSessionStore {
  const store = findClaudeSession(config, deviceId, reference.session_id);
  requireThat(store && reference.directory === config.workspace && reference.model === config.model, "claude_native_registration_mismatch");
  store.validate(reference); return store;
}
