import { assertProtocolSchema, type NativeTaskFailure } from "@controlmesh/protocol";
import { isAbsolute, relative, resolve, sep } from "node:path";
import { object, requireThat } from "./value";

/** Called only after native identity, terminal output, source and every tool receipt are verified. */
export function missingRequiredReads(workspace: string, required: readonly string[], proof: { read_files: string[]; written_files: string[] }, readOnly: boolean): NativeTaskFailure | undefined {
  const read = new Set(proof.read_files);
  const missing = required.map(path => resolve(workspace, path)).filter(path => !read.has(path));
  if (!missing.length) return undefined;
  requireThat(readOnly && proof.written_files.length === 0, "workspace_tool_required_read_missing");
  const failure: NativeTaskFailure = { schema_version: "controlmesh.native_task_failure.v1", code: "workspace_tool_required_read_missing",
    scope: "read_only_without_communication", missing_files: [...new Set(missing.map(path => relative(workspace, path).split(sep).join("/")))].sort() };
  validateFailure(failure); return failure;
}
function validateFailure(value: unknown): asserts value is NativeTaskFailure {
  assertProtocolSchema<NativeTaskFailure>("native-task-failure.schema.json", value);
  requireThat(value.missing_files.every(path => !isAbsolute(path) && !/[\\\x00\r\n]/.test(path)
    && !path.split("/").some(part => !part || part === "." || part === "..")), "native_failure_path_invalid");
}
/** A failure cannot be mislabeled done or carry unverified artifact/publication evidence. */
export function nativeTaskOutcome(result: Record<string, unknown>): "done" | "failed" {
  if (result.task_failure === undefined) return "done";
  validateFailure(result.task_failure);
  requireThat(object(result.native_session) && result.workspace_write === undefined && result.communication === undefined
    && result.completion === undefined, "native_failure_scope_unproven");
  if (result.workspace_tools !== undefined) requireThat(object(result.workspace_tools) && Array.isArray(result.workspace_tools.written_files)
    && result.workspace_tools.written_files.length === 0, "native_failure_scope_unproven");
  return "failed";
}
export function assertNativeFailureManifest(manifest: Record<string, unknown>, result: Record<string, unknown>): void {
  if (nativeTaskOutcome(result) === "failed") requireThat(manifest.workspace_write === undefined && manifest.communication === undefined,
    "native_failure_scope_unproven");
}
