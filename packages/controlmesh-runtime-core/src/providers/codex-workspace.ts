import { mkdirSync } from "node:fs";
import { join } from "node:path";
import type { Lease } from "../kernel";
import { digest, object, requireThat } from "../value";
import { NativeAgentChannel } from "./native-agent-broker";
import { prepareNativeAgentConfiguration } from "./native-agent-profile";
import type { WorkspaceStage } from "../workspace-stage";
import { nativeWorkspaceTools, NativeWorkspaceFiles } from "./native-workspace-files";
import { codexWorkspaceTools } from "./codex-communication";

export interface CodexWorkspaceConfiguration { node_executable: string; read_files: string[]; required_reads: string[] }
export function createCodexWorkspace(config: CodexWorkspaceConfiguration, workspace: string, directory: string, binding: string,
  lease: Lease, current: () => void, assertDispatched: () => void, stage?: WorkspaceStage) {
  const journal = join(directory, "receipts"); mkdirSync(journal, { mode: 0o700 });
  const tools = stage ? nativeWorkspaceTools : ["controlmesh_read_file"] as const;
  const files = new NativeWorkspaceFiles({ workspace, read_files: config.read_files, tools, journal_directory: journal, binding_digest: binding, stage },
    operation => { current(); return operation(); }, current);
  const profile = prepareNativeAgentConfiguration(join(directory, "ipc"), config.node_executable, lease.task_id, [], null, "workspace.v1");
  const channel = new NativeAgentChannel(lease, profile, current, { assertDispatched, call: async (tool, input) => files.call(tool, input) });
  return { channel, scope: files.scope, tools };
}
export function verifyCodexWorkspace(config: CodexWorkspaceConfiguration, workspace: string, scope: Record<string, unknown>, binding: string,
  stdout: string, current: () => void, completion: unknown, stage?: WorkspaceStage) {
  requireThat(scope.binding_digest === binding && object(scope.journal) && typeof scope.journal.path === "string", "codex_workspace_binding_changed");
  const files = new NativeWorkspaceFiles({ workspace, read_files: config.read_files, tools: stage ? nativeWorkspaceTools : ["controlmesh_read_file"], journal_directory: scope.journal.path, stage,
    binding_digest: binding, retained_scope: scope }, operation => { current(); return operation(); }, current);
  const proof = files.verify(codexWorkspaceTools(stdout, stage ? nativeWorkspaceTools : undefined), config.required_reads);
  const taskCompletion = files.verifyCompletion(completion, proof);
  return { workspace_receipts: proof, ...(taskCompletion ? { task_completion: taskCompletion } : {}) };
}
export function codexWorkspaceBinding(configuration: unknown, taskDigest: string, episode: string): string {
  return digest({ configuration, taskDigest, episode });
}
