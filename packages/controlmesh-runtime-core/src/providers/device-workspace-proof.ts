import { assertProtocolSchema, type DeviceWorkspaceBinding, type DeviceWorkspaceProof } from "@controlmesh/protocol";
import { digest, object, requireThat } from "../value";
import { decodeNativeManifest } from "./native-manifest";
import { assertSharedEditGrant } from "./opencode-profile";
import { decodeClaudeDispatch } from "./claude-task-evidence";

/** Only bounded digests leave the device; paths, staged files and native records stay local. */
export function deviceWorkspaceBinding(manifest: unknown): DeviceWorkspaceBinding | undefined {
  if (object(manifest) && manifest.schema_version === "controlmesh.claude_dispatch.v1") {
    const selected = decodeClaudeDispatch(manifest);
    if (!selected.stage) return undefined;
    requireThat(selected.workflow_binding !== undefined, "claude_workflow_binding_required");
    return { profile_digest: digest({ stage: selected.stage.reference, scope: selected.scope, configuration: selected.configuration_digest }),
      workflow_binding: selected.workflow_binding };
  }
  if (!object(manifest) || manifest.workspace_write === undefined) return undefined;
  const write = decodeNativeManifest(manifest).workspace_write!;
  return { profile_digest: digest(write), workflow_binding: write.workflow_binding };
}

export function deviceWorkspaceProof(binding: DeviceWorkspaceBinding | undefined, result: Record<string, unknown>): DeviceWorkspaceProof | undefined {
  requireThat(Boolean(binding) === Boolean(result.workspace_write), "device_workspace_proof_required");
  if (!binding) return undefined;
  const receipt = result.workspace_write;
  requireThat(object(receipt) && Array.isArray(receipt.changed_paths), "device_workspace_result_invalid");
  const proof = { profile_digest: binding.profile_digest, proposal_digest: receipt.proposal_digest,
    changed_count: receipt.changed_paths.length, ...(binding.workflow_binding ? { specmesh: result.specmesh } : {}) };
  verifyDeviceWorkspaceProof(binding, proof);
  return proof as DeviceWorkspaceProof;
}

export function verifyDeviceWorkspaceProof(binding: unknown, proof: unknown): void {
  requireThat(Boolean(binding) === Boolean(proof), "device_workspace_proof_required");
  if (!binding) return;
  assertProtocolSchema<DeviceWorkspaceBinding>("device-workspace-binding.schema.json", binding);
  assertProtocolSchema<DeviceWorkspaceProof>("device-workspace-proof.schema.json", proof);
  requireThat(proof.profile_digest === binding.profile_digest && Boolean(proof.specmesh) === Boolean(binding.workflow_binding), "device_workspace_binding_changed");
}

export function assertDeviceWorkspaceGrant(binding: unknown, grant: unknown): void {
  if (binding === undefined) return;
  assertProtocolSchema("device-workspace-binding.schema.json", binding);
  assertSharedEditGrant(grant);
}
