import type { NativeTaskFailure } from "@controlmesh/protocol";
import { expect, test } from "bun:test";
import { assertNativeFailureManifest, missingRequiredReads, nativeTaskOutcome } from "../src/native-task-failure";
const failure = (): NativeTaskFailure => ({ schema_version: "controlmesh.native_task_failure.v1", code: "workspace_tool_required_read_missing",
  scope: "read_only_without_communication", missing_files: ["PROJECT.md"] });
const result = () => ({ native_session: {}, task_failure: failure() });
test("failure requires bounded relative paths and cannot include artifact, completion or communication claims", () => {
  expect(nativeTaskOutcome(result())).toBe("failed");
  for (const path of ["/private/project.md", "../project.md", "a/../project.md", "a\\project.md", "a//b", "a/./b", "a\n"]) {
    expect(() => nativeTaskOutcome({ ...result(), task_failure: { ...failure(), missing_files: [path] } })).toThrow();
  }
  for (const field of ["workspace_write", "communication", "completion"]) {
    expect(() => nativeTaskOutcome({ ...result(), [field]: {} })).toThrow("native_failure_scope_unproven");
  }
  for (const field of ["workspace_write", "communication"]) {
    expect(() => assertNativeFailureManifest({ [field]: {} }, result())).toThrow("native_failure_scope_unproven");
  }
  expect(() => nativeTaskOutcome({ ...result(), workspace_tools: { written_files: ["output.md"] } })).toThrow("native_failure_scope_unproven");
  expect(() => nativeTaskOutcome({ task_failure: failure() })).toThrow("native_failure_scope_unproven");
});
test("required-read classification uses verified read coverage and refuses any write authority", () => {
  expect(missingRequiredReads("/project", ["PROJECT.md"], { read_files: ["/project/PROJECT.md"], written_files: [] }, false)).toBeUndefined();
  expect(missingRequiredReads("/project", ["PROJECT.md", "PROJECT.md"], { read_files: [], written_files: [] }, true)).toEqual(failure());
  expect(() => missingRequiredReads("/project", ["PROJECT.md"], { read_files: [], written_files: [] }, false)).toThrow("workspace_tool_required_read_missing");
  expect(() => missingRequiredReads("/project", ["PROJECT.md"], { read_files: [], written_files: ["output.md"] }, true)).toThrow("workspace_tool_required_read_missing");
});
