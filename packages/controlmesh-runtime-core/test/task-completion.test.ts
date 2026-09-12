import { expect, test } from "bun:test";
import { decodeTaskCompletion, deviceCompletionProof, verifyDeviceCompletion } from "../src/task-completion";
import { nativeTaskDigest } from "../src/providers/native-manifest";
import { digest } from "../src/value";

test("completion binding preserves undeclared historical native task identity", () => {
 const task = { task_id: "task", chat_id: "chat", status: "waiting" as const, provider: "claude", model: "model", prompt: "work", repo_root: "/project" };
 const old = digest({ provider: task.provider, model: task.model, repo_root: task.repo_root, prompt: task.prompt, native_session: null, tool_grant: null, execution_context: null });
 expect(nativeTaskDigest(task)).toBe(old);
 const contract = { schema_version: "controlmesh.task_completion.v1", files: [{ path: "result.txt", mode: "write" }] };
 const bound = nativeTaskDigest({ ...task, completion_requirements: contract }); expect(bound).not.toBe(old);
 expect(nativeTaskDigest({ ...task, completion_requirements: { ...contract, files: [{ path: "result.txt", mode: "read" }] } })).not.toBe(bound);
 expect(nativeTaskDigest({ ...task, completion_requirements: { ...contract, files: [{ path: "result.txt", mode: "write", sha256: "a".repeat(64) }] } })).not.toBe(bound);
 expect(() => decodeTaskCompletion({ ...contract, files: [contract.files[0], contract.files[0]] })).toThrow("duplicate_completion_path");
 expect(() => decodeTaskCompletion(null)).toThrow();
});

test("device completion proof binds requirements and hashes without exporting paths", () => {
 const contract = { schema_version: "controlmesh.task_completion.v1", files: [{ path: "private/result.txt", mode: "write", sha256: "a".repeat(64) }] };
 const evidence = { requirements_digest: digest(contract), files: [{ path: "private/result.txt", mode: "write", sha256: "a".repeat(64) }] };
 const proof = deviceCompletionProof(contract, evidence)!;
 expect(JSON.stringify(proof)).not.toContain("private");
 expect(() => verifyDeviceCompletion(contract, proof)).not.toThrow();
 for (const changed of [undefined, { ...proof, requirements_digest: "0".repeat(64) }, { ...proof, sha256: ["b".repeat(64)] }, { ...proof, sha256: [] }]) {
  expect(() => verifyDeviceCompletion(contract, changed)).toThrow();
 }
 expect(() => verifyDeviceCompletion(undefined, proof)).toThrow("device_completion_proof_required");
 expect(() => deviceCompletionProof(contract, { ...evidence, files: [{ ...evidence.files[0], mode: "read" }] })).toThrow("device_completion_evidence_mismatch");
});
