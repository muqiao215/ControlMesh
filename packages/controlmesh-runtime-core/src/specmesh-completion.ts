import { decodeTaskCompletion } from "./task-completion";
import { digest, requireThat, type LegacyTask } from "./value";
import type { SpecMeshPort } from "./specmesh-port";

/** Select requirements from the configured local checkout; source metadata grants no authority. */
export async function adoptSpecMeshCompletion(task: LegacyTask, expectedHash: unknown, port?: SpecMeshPort): Promise<{ task: LegacyTask; assertCurrent(): void }> {
  let submitted = structuredClone(task);
  requireThat(!Object.hasOwn(submitted, "specmesh_completion_source"), "task_body_cannot_issue_specmesh_source");
  if (expectedHash === undefined) return { task: submitted, assertCurrent() {} };
  requireThat(port, "specmesh_not_configured");
  requireThat(typeof expectedHash === "string" && /^[a-f0-9]{64}$/.test(expectedHash), "invalid_specmesh_requirements_hash");
  port.assertWorkspace(submitted.repo_root);
  const observation = await port.inspect("check", { assertCurrent: () => port.assertCurrent() });
  const candidate = observation.result.artifact_requirements;
  requireThat(observation.result.status === "pass" && candidate && candidate.sha256 === expectedHash, "specmesh_requirements_changed");
  const completion = decodeTaskCompletion({ schema_version: "controlmesh.task_completion.v1", files: candidate.requirements.files })!;
  requireThat(submitted.completion_requirements === undefined || digest(submitted.completion_requirements) === digest(completion), "specmesh_requirements_conflict");
  submitted = { ...submitted, completion_requirements: structuredClone(completion),
    specmesh_completion_source: { path: candidate.path, sha256: candidate.sha256,
      snapshot_digest: observation.snapshot_digest, authority: "asserted_candidate" } };
  return { task: submitted, assertCurrent: observation.assertCurrent };
}
