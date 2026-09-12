import { closeSync, constants, fsyncSync, openSync, writeFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import type { ProcessOutcome } from "../process-supervisor";
import { privateFile } from "../private-runtime-file";
import { canonical, digest, object, requireThat, RuntimeConflict, type LegacyTask } from "../value";
import { WorkspaceStage, type WorkspaceAuthority } from "../workspace-stage";
import { observeClaudeControl, validateClaudeControlInput, type ClaudeControlInput } from "./claude-control";
import type { ClaudeNativeBaseline } from "./claude-session";
import { claudeTaskScope, claudeProbeBinding, findClaudeSession, type ClaudeTaskConfiguration } from "./claude-task-profile";
import { directoryIdentity, nativeTaskDigest, type DirectoryIdentity } from "./native-manifest";
import { NativeWorkspaceFiles } from "./native-workspace-files";
import { decodeNativeMailbox, nativeInput, nativeMailboxEvidence, type NativeMailboxBatch } from "./native-mailbox-input";
import type { ProbeBinding } from "./preflight-cache";

export interface ClaudeDispatch extends Record<string, unknown> {
  schema_version: "controlmesh.claude_dispatch.v1";
  task_digest: string;
  configuration_digest: string;
  binding: ProbeBinding;
  input: ClaudeControlInput;
  native_directory: DirectoryIdentity;
  native_path: string | null;
  baseline: ClaudeNativeBaseline | null;
  execution_directory: DirectoryIdentity;
  scope: ReturnType<typeof claudeTaskScope>;
  workspace_tools: Record<string, unknown>;
  stage: { path: string; reference: ReturnType<WorkspaceStage["reference"]> } | null;
  mailbox_delivery?: NativeMailboxBatch;
}
export function claudeTaskPrompt(task: LegacyTask, scope: ReturnType<typeof claudeTaskScope>): string {
  requireThat(typeof task.prompt === "string" && task.prompt.length > 0, "invalid_native_task");
  return task.prompt + "\n\nControlMesh workspace requirements: use the workspace file tools for current files. Read the complete current contents of every required file before finishing, and read it again if you modify it: "
    + canonical(scope.required.map(path => relative(String(task.repo_root), path))) + ". Writes stay staged until ControlMesh accepts and publishes them. Tool receipts do not by themselves establish that the user's task is complete.";
}
export function decodeClaudeDispatch(value: unknown): ClaudeDispatch {
  requireThat(object(value) && value.schema_version === "controlmesh.claude_dispatch.v1" && object(value.binding) && object(value.native_directory)
    && object(value.execution_directory) && object(value.scope) && object(value.workspace_tools)
    && (value.stage === null || (object(value.stage) && typeof value.stage.path === "string" && object(value.stage.reference)))
    && (value.native_path === null || typeof value.native_path === "string")
    && (value.baseline === null || object(value.baseline)), "invalid_claude_dispatch");
  validateClaudeControlInput(value.input);
  if (value.mailbox_delivery !== undefined) decodeNativeMailbox(value.mailbox_delivery);
  return value as unknown as ClaudeDispatch;
}
const recordPath = (manifest: ClaudeDispatch) => join(manifest.execution_directory.path, "outcome.json");
export function retainClaudeOutcome(manifest: ClaudeDispatch, outcome: ProcessOutcome): Record<string, unknown> {
  const path = recordPath(manifest), bytes = canonical({ schema_version: "controlmesh.claude_outcome.v1", manifest_digest: digest(manifest), outcome });
  requireThat(Buffer.byteLength(bytes) <= 12 * 1024 * 1024, "claude_outcome_record_limit");
  const fd = openSync(path, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600);
  try { writeFileSync(fd, bytes); fsyncSync(fd); } finally { closeSync(fd); }
  const directory = openSync(dirname(path), constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
  try { fsyncSync(directory); } finally { closeSync(directory); }
  return readClaudeOutcome(manifest).observation;
}
export function readClaudeOutcome(manifest: ClaudeDispatch): { outcome: ProcessOutcome; observation: Record<string, unknown> } {
  requireThat(digest(directoryIdentity(manifest.execution_directory.path)) === digest(manifest.execution_directory), "claude_execution_directory_changed");
  const file = privateFile(recordPath(manifest), 12 * 1024 * 1024), value: unknown = JSON.parse(file.bytes.toString());
  requireThat(object(value) && value.schema_version === "controlmesh.claude_outcome.v1" && value.manifest_digest === digest(manifest)
    && object(value.outcome) && typeof value.outcome.stdout === "string" && typeof value.outcome.stderr === "string", "claude_outcome_binding_changed");
  return { outcome: value.outcome as unknown as ProcessOutcome, observation: { schema_version: "controlmesh.claude_observation.v1", process_digest: digest(value.outcome), record_revision: file.revision } };
}

/** One verifier for normal completion and recovery. It cannot start a provider process or replay tools. */
export class ClaudeTaskEvidence {
  readonly manifest: ClaudeDispatch;
  readonly stage?: WorkspaceStage;
  constructor(private readonly config: ClaudeTaskConfiguration, private readonly deviceId: string, private readonly task: LegacyTask,
    value: unknown, private readonly observation: Record<string, unknown>, private readonly current: () => void) {
    this.manifest = decodeClaudeDispatch(value);
    if (this.manifest.stage) this.stage = WorkspaceStage.open(this.manifest.stage.path, this.manifest.stage.reference);
  }
  verify(): Record<string, unknown> {
    this.current();
    const m = this.manifest, scope = claudeTaskScope(this.config, this.task, true);
    requireThat(m.task_digest === nativeTaskDigest(this.task) && m.configuration_digest === digest(this.config)
      && digest(m.binding) === digest(claudeProbeBinding(this.config, this.deviceId)) && digest(m.scope) === digest(scope)
      && m.native_directory.path === this.config.environment.config_directory && digest(directoryIdentity(m.native_directory.path)) === digest(m.native_directory)
      && m.input.executable === this.config.executable && m.input.workspace === this.config.workspace && m.input.model === this.config.model,
    "claude_dispatch_binding_changed");
    requireThat(dirname(m.execution_directory.path) === join(this.config.state_home, "claude-runs")
      && Boolean(this.stage) === (scope.roots.length > 0)
      && (!this.stage || (dirname(this.stage.path) === m.execution_directory.path && digest(this.stage.fileScope().roots) === digest(scope.roots)))
      && m.input.workspace_command[0] === this.config.node_executable
      && m.input.workspace_command[1] === join(m.execution_directory.path, "ipc/client.mjs")
      && dirname(m.input.workspace_command[2]) === join(m.execution_directory.path, "ipc"), "claude_capability_binding_changed");
    requireThat(m.baseline ? digest(m.baseline.reference) === digest(this.task.native_session)
      && m.input.session_id === m.baseline.reference.session_id : !this.task.native_session, "claude_original_session_changed");
    requireThat(m.input.resume === Boolean(m.baseline) && m.input.prompt === nativeInput(claudeTaskPrompt(this.task, scope), m.mailbox_delivery), "claude_native_input_changed");
    const retained = readClaudeOutcome(m); requireThat(digest(retained.observation) === digest(this.observation), "claude_observation_changed");
    const observed = observeClaudeControl(retained.outcome, m.input);
    requireThat(observed.terminal, observed.failure?.code ?? observed.invalid_reason ?? "claude_completion_unproven");
    const store = findClaudeSession(this.config, this.deviceId, m.input.session_id);
    requireThat(store && (m.native_path === null || store.path === m.native_path), "claude_native_source_changed");
    const native = store.verifyTurn(m.input.session_id, m.baseline, m.input.prompt, observed.text, m.input.model);
    requireThat(native.reference.directory === this.config.workspace, "claude_native_workspace_changed");
    const files = new NativeWorkspaceFiles({ workspace: this.config.workspace, read_files: scope.reads, tools: scope.tools,
      journal_directory: join(m.execution_directory.path, "receipts"), binding_digest: String(m.workspace_tools.binding_digest),
      ...(this.stage ? { stage: this.stage } : {}), retained_scope: m.workspace_tools }, run => run(), this.current);
    const proof = files.verify(native.tools.map(tool => {
      requireThat(tool.name.startsWith("mcp__workspace__"), "claude_native_tool_ungranted");
      return { tool: "controlmesh_" + tool.name.slice("mcp__workspace__".length), input: tool.input, output: tool.output };
    }), scope.required);
    const result: Record<string, unknown> = { native_session: native.reference, user_message_id: native.user_message_id,
      assistant_message_ids: native.assistant_message_ids, text: observed.text, output_digest: digest(observed.text), workspace_tools: proof,
      read_files: proof.read_files, ...(m.mailbox_delivery ? { mailbox_delivery: nativeMailboxEvidence(m.mailbox_delivery, native.user_message_id) } : {}) };
    if (this.stage) {
      let receipt: ReturnType<WorkspaceStage["proposalReceipt"]> | undefined;
      try { receipt = this.stage.proposalReceipt(); }
      catch (error) { requireThat(error instanceof RuntimeConflict && error.code === "workspace_stage_not_sealed", "claude_stage_unavailable"); }
      if (receipt) {
        this.stage.assertProposal(receipt.proposal_digest);
        requireThat(receipt.changed_paths.every(path => proof.written_files.includes(join(this.config.workspace, path))), "native_write_tool_evidence_missing");
        result.workspace_write = receipt;
      }
    }
    this.current(); return result;
  }
  publish(authority: WorkspaceAuthority): Record<string, unknown> {
    this.verify();
    if (this.stage) {
      try { this.stage.proposalReceipt(); }
      catch (error) {
        requireThat(error instanceof RuntimeConflict && error.code === "workspace_stage_not_sealed", "claude_stage_unavailable");
        this.stage.seal(authority);
      }
      this.verify(); const proposal = this.stage.proposalReceipt();
      this.stage.promote(authority, proposal.proposal_digest); this.stage.assertApplied(proposal.proposal_digest);
    }
    return this.verify();
  }
  assertPublished(): void {
    this.verify(); if (this.stage) this.stage.assertApplied(this.stage.proposalReceipt().proposal_digest);
  }
}
