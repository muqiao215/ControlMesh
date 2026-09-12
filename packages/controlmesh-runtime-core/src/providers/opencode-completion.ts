import { join } from "node:path";
import { decodeTaskCompletion } from "../task-completion";
import { contains } from "../containers/plan";
import { digest, requireThat } from "../value";
import { snapshotReads } from "./native-manifest";
import type { WorkspaceStage } from "../workspace-stage";

export function openCodeCompletionPrompt(prompt: string, value: unknown): string {
  const contract = decodeTaskCompletion(value);
  return contract ? `${prompt}\n\nRequired task artifacts (must be evidenced by this turn's file tools):\n${JSON.stringify(contract)}` : prompt;
}
export function assertOpenCodeCompletionScope(value: unknown, workspace: string, reads: readonly string[], roots: readonly string[]): void {
  const contract = decodeTaskCompletion(value);
  for (const item of contract?.files ?? []) {
    const path = join(workspace, item.path);
    requireThat(roots.some(root => contains(root, path)) || (item.mode === "read" && reads.includes(path)), "task_completion_path_not_granted");
  }
}
export function verifyOpenCodeCompletion(value: unknown, workspace: string,
  proof: { read_files: string[]; written_files: string[] }, stage?: WorkspaceStage): Record<string, unknown> | undefined {
  const contract = decodeTaskCompletion(value); if (!contract) return undefined;
  const scope = stage?.fileScope();
  const files = contract.files.map(item => {
    const path = join(workspace, item.path);
    requireThat((item.mode === "write" ? proof.written_files : proof.read_files).includes(path), "task_completion_evidence_missing");
    const root = scope?.roots.some(root => contains(root, path)) ? scope.tree : workspace;
    const observed = snapshotReads(root, [join(root, item.path)])[0];
    requireThat(item.sha256 === undefined || observed.sha256 === item.sha256, "task_completion_content_mismatch");
    return { path: item.path, mode: item.mode, sha256: observed.sha256 };
  });
  return { requirements_digest: digest(contract), files };
}
