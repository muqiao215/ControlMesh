import { requireThat } from "./value";
const titles: Record<string, string> = {
  test_execution: "Run test execution", long_shell: "Run long shell command", release_validation: "Run release validation", uv_build: "Build package",
  git_write: "Run git write command", repo_write: "Run repository write command", repo_publish: "Run repository publish command",
  github_release: "Run GitHub release command", publish: "Run publish command", release_publish: "Run release publish command",
};
const sideEffects = new Set(["git_write", "repo_write", "repo_publish", "github_release", "publish", "release_publish"]);
export interface HostExecutionDecision { route_to_host: boolean; job_kind: string; step_id: string; step_title: string; side_effect: boolean; reason: string }
/** Python task workunit policy port; never inspect prompt text for executable commands. */
export function classifyHostExecution(task: { workunit_kind?: unknown; command?: unknown }): HostExecutionDecision {
  requireThat((task.workunit_kind == null || typeof task.workunit_kind === "string") && (task.command == null || typeof task.command === "string"), "invalid_host_routing_fields");
  const kind = String(task.workunit_kind ?? "").trim(), command = String(task.command ?? "").trim().toLowerCase();
  const explicit = Object.hasOwn(titles, kind), heuristic = ["pytest", "uv build", "git push", "gh release create", "twine upload", "uv publish"].some(token => command.includes(token));
  if (!explicit && !heuristic) return { route_to_host: false, job_kind: "", step_id: "", step_title: "", side_effect: false, reason: "" };
  const selected = kind || "long_shell";
  return { route_to_host: true, job_kind: selected, step_id: selected, step_title: titles[selected] ?? "Run host execution",
    side_effect: explicit ? sideEffects.has(kind) : ["git push", "gh release create", "publish", "upload"].some(token => command.includes(token)),
    reason: explicit ? `workunit=${kind}` : "command heuristic" };
}
