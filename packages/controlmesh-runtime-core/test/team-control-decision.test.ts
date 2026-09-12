import { expect, test } from "bun:test";
import { resolve } from "node:path";
import { decodeDirectorDecision, decodeJudgeDecision } from "../src/team-control-decision";

test("director and judge decision normalizers match Python field dependencies and coercions", () => {
  const cases: { kind: string; value: Record<string, unknown> }[] = [];
  for (const decision of ["dispatch_workers", "complete", "needs_parent_input", "needs_repair", "failed", "invalid"])
    for (const dispatch_roles of [[], [" worker "], null]) for (const repair_hint of [null, " repair "])
      for (const stop_reason of [null, "budget_exhausted", "no_viable_path", "parent_decision_required", "invalid"])
        cases.push({ kind: "director", value: { round_index: 1, decision, summary: " summary ", dispatch_roles, repair_hint, stop_reason } });
  for (const decision of ["select_winner", "advance_round", "needs_parent_input", "needs_repair", "failed", "invalid"])
    for (const winner_role of [null, " winner ", ""]) for (const next_candidate_roles of [[], [" a "], null])
      for (const repair_hint of [null, " repair "]) for (const stop_reason of [null, "final_round_tie", "insufficient_evidence", "parent_decision_required", "invalid"])
        cases.push({ kind: "judge", value: { round_index: 1, decision, summary: " summary ", winner_role, next_candidate_roles, repair_hint, stop_reason } });
  for (const kind of ["director", "judge"]) {
    const base = { round_index: 1, summary: "summary", decision: kind === "director" ? "complete" : "select_winner", ...(kind === "judge" ? { winner_role: "a" } : {}) };
    for (const field of ["schema_version", "round_index", "confidence", "summary"])
      for (const value of [true, false, "1.0", "1e0", " 1 ", "\u001csummary\u001f", "\ufeffsummary\ufeff"])
        cases.push({ kind, value: { ...base, [field]: value, ignored: "extra", evidence: [{ ref: " event ", ignored: 1 }] } });
    cases.push({ kind, value: { ...base, topology: ` ${kind === "director" ? "director_worker" : "debate_judge"} ` } });
  }
  const script = `import json,sys\nfrom controlmesh.team.models import TeamDirectorDecision,TeamJudgeDecision\nrows=[]\nfor row in json.load(sys.stdin):\n try:rows.append({'ok':True,'value':(TeamDirectorDecision if row['kind']=='director' else TeamJudgeDecision).model_validate(row['value']).model_dump()})\n except ValueError:rows.append({'ok':False})\nprint(json.dumps(rows))`;
  const child = Bun.spawnSync(["uv", "run", "python", "-c", script], { cwd: resolve(import.meta.dir, "../../.."), stdin: Buffer.from(JSON.stringify(cases)), stdout: "pipe", stderr: "pipe", timeout: 30_000 });
  expect({ code: child.exitCode, stderr: child.stderr.toString() }).toEqual({ code: 0, stderr: "" });
  const oracle = JSON.parse(child.stdout.toString());
  for (const [i, entry] of cases.entries()) {
    let actual;
    try { actual = { ok: true, value: entry.kind === "director" ? decodeDirectorDecision(entry.value) : decodeJudgeDecision(entry.value) }; }
    catch { actual = { ok: false }; }
    expect({ entry, actual }).toEqual({ entry, actual: oracle[i] });
  }
});
