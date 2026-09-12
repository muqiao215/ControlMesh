import { dirname, join } from "node:path";
import type { ContainerConfiguration } from "../containers/plan";
import type { ProcessOutcome } from "../process-supervisor";
import type { ContainerOutcome } from "../containers/process";
import { privateFile } from "../private-runtime-file";
import { digest, object, requireThat } from "../value";
import { directoryIdentity } from "./native-manifest";
import type { ClaudeContainerExecution } from "./claude-container";

export function decodeClaudeContainerExecution(value: unknown): ClaudeContainerExecution {
  requireThat(object(value) && value.schema_version === "controlmesh.claude_container_execution.v1"
    && typeof value.runtime_digest === "string" && /^[a-f0-9]{64}$/.test(value.runtime_digest)
    && object(value.state) && typeof value.state.path === "string"
    && object(value.helper) && typeof value.helper.path === "string" && typeof value.helper.revision === "string"
    && typeof value.version_execution === "string" && /^claude-version-[a-f0-9-]{36}$/.test(value.version_execution)
    && typeof value.task_execution === "string" && /^claude-task-[a-f0-9-]{36}$/.test(value.task_execution), "invalid_claude_container_execution");
  return value as unknown as ClaudeContainerExecution;
}

/** Retained supervisor evidence only. No Docker/model command, helper build or current source lookup. */
export function verifyClaudeContainerExecution(value: ClaudeContainerExecution, configuration: ContainerConfiguration,
  executionDirectory: string, outcome: ProcessOutcome): Record<string, unknown> {
  const reference = decodeClaudeContainerExecution(value);
  requireThat(reference.state.path === configuration.state_root && digest(directoryIdentity(reference.state.path)) === digest(reference.state)
    && dirname(reference.helper.path) === join(executionDirectory, "assets")
    && privateFile(reference.helper.path).revision === reference.helper.revision, "claude_container_retained_profile_changed");
  const records = [reference.version_execution, reference.task_execution].map(id => {
    const saved = privateFile(join(configuration.state_root, digest(id), "record.json"), 12 * 1024 * 1024);
    const record: unknown = JSON.parse(saved.bytes.toString());
    requireThat(object(record) && record.schema_version === "controlmesh.container_execution.v1" && record.execution === digest(id)
      && record.owner === digest(configuration.state_root) && record.image === configuration.image_id && record.socket === configuration.socket
      && record.state === "removed" && record.creation_uncertain === false && typeof record.container_id === "string"
      && /^[a-f0-9]{64}$/.test(record.container_id) && typeof record.engine_id === "string" && record.engine_id.length > 0
      && typeof record.input_digest === "string" && /^[a-f0-9]{64}$/.test(record.input_digest)
      && typeof record.isolation_digest === "string" && /^[a-f0-9]{64}$/.test(record.isolation_digest)
      && object(record.outcome), "claude_container_completion_unproven");
    return { record, revision: saved.revision };
  });
  const version = records[0].record.outcome as Record<string, unknown>;
  requireThat(version.reason === "exited" && version.exit_code === 0 && typeof version.stdout === "string"
    && version.stdout.trim() === "2.1.263 (Claude Code)", "claude_container_version_unproven");
  const { container_id, cleanup, ...plain } = outcome as Partial<ContainerOutcome> & ProcessOutcome;
  requireThat(cleanup === "removed" && container_id === records[1].record.container_id
    && records[0].record.container_id !== container_id && digest(records[1].record.outcome) === digest(plain), "claude_container_outcome_mismatch");
  return { runtime_digest: reference.runtime_digest, image_id: configuration.image_id,
    container_id, cleanup, records_digest: digest(records.map(row => row.revision)) };
}
