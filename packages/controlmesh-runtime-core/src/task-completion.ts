import { assertProtocolSchema } from "@controlmesh/protocol";
import { isAbsolute } from "node:path";
import { digest, object, requireThat } from "./value";

export interface TaskCompletion {
  schema_version: "controlmesh.task_completion.v1";
  files: { path: string; mode: "read" | "write"; sha256?: string }[];
}
export function decodeTaskCompletion(value: unknown): TaskCompletion | undefined {
  if (value === undefined) return undefined;
  assertProtocolSchema<TaskCompletion>("task-completion.schema.json", value);
  requireThat(new Set(value.files.map(file => file.path)).size === value.files.length, "duplicate_completion_path");
  for (const file of value.files) requireThat(!isAbsolute(file.path) && !/[\\\x00-\x1f]/.test(file.path)
    && file.path.split("/").every(part => part && part !== "." && part !== ".." && part !== ".git"), "invalid_completion_path");
  return value;
}

export interface DeviceCompletion { requirements_digest: string; sha256: string[] }
export function verifyDeviceCompletion(value: unknown, proof: unknown): void {
  const contract = decodeTaskCompletion(value);
  requireThat(Boolean(contract) === (proof !== undefined), "device_completion_proof_required");
  if (!contract) return;
  assertProtocolSchema<DeviceCompletion>("device-completion-proof.schema.json", proof);
  requireThat(proof.requirements_digest === digest(contract) && proof.sha256.length === contract.files.length
    && contract.files.every((file, index) => file.sha256 === undefined || file.sha256 === proof.sha256[index]), "device_completion_proof_mismatch");
}
export function deviceCompletionProof(value: unknown, evidence: unknown): DeviceCompletion | undefined {
  const contract = decodeTaskCompletion(value);
  requireThat(Boolean(contract) === (evidence !== undefined), "device_completion_proof_required");
  if (!contract) return undefined;
  requireThat(object(evidence) && evidence.requirements_digest === digest(contract) && Array.isArray(evidence.files)
    && evidence.files.length === contract.files.length, "device_completion_evidence_mismatch");
  const hashes = evidence.files.map((file, index) => {
    requireThat(object(file) && file.path === contract.files[index].path && file.mode === contract.files[index].mode, "device_completion_evidence_mismatch");
    return file.sha256 as string;
  });
  const proof = { requirements_digest: digest(contract), sha256: hashes }; verifyDeviceCompletion(contract, proof); return proof;
}
