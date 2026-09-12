import { expect, test } from "bun:test";
import { resolve } from "node:path";
import { decodeTeamResult } from "../src/team-result-validation";
import { reducePipelineReview } from "../src/team-results";

test("raw team result boundary matches Python for topology, status, parent and repair combinations", () => {
  const inputs: Record<string, unknown>[] = [];
  for (const topology of ["pipeline", "fanout_merge", "director_worker", "debate_judge"])
    for (const substage of ["planning", "worker_running", "review_running", "collecting", "reducing", "repairing", "waiting_parent", "bogus"])
      for (const status of ["completed", "failed", "blocked", "needs_parent_input", "needs_repair"])
        for (const needs_parent_input of [false, true]) for (const repair_hint of [null, " repair "])
          inputs.push({ topology, substage, status, needs_parent_input, repair_hint, worker_role: " worker ", summary: " summary ",
            evidence: [{ ref: " event:one ", ignored: true }], artifacts: [{ ref: " file:one ", label: " label " }], extra: "ignored" });
  const base = { topology: "pipeline", substage: "worker_running", status: "completed", worker_role: "worker", summary: "summary" };
  for (const patch of [{}, { summary: " " }, { confidence: 2 }, { confidence: "0.5" }, { schema_version: "1" }, { schema_version: 2 },
    { evidence: null }, { artifacts: [{ ref: " " }] }, { needs_parent_input: "false" }, { result_items: [{ kind: "bogus", ref: "ref" }] }]) inputs.push({ ...base, ...patch });
  for (const value of [true, false, "1e0", "0x1", "1_0", "1.0", " 1 ", "\u001csummary\u001f", "\ufeffsummary\ufeff"])
    for (const field of ["schema_version", "confidence", "summary"]) inputs.push({ ...base, [field]: value });
  const script = `import json,sys\nfrom controlmesh.team.models import TeamStructuredResult\nrows=[]\nfor item in json.load(sys.stdin):\n try: rows.append({'ok':True,'value':TeamStructuredResult.model_validate(item).model_dump()})\n except ValueError: rows.append({'ok':False})\nprint(json.dumps(rows))`;
  const child = Bun.spawnSync(["uv", "run", "python", "-c", script], { cwd: resolve(import.meta.dir, "../../.."), stdin: Buffer.from(JSON.stringify(inputs)), stdout: "pipe", stderr: "pipe", timeout: 30_000 });
  expect({ code: child.exitCode, stderr: child.stderr.toString() }).toEqual({ code: 0, stderr: "" });
  const oracle = JSON.parse(child.stdout.toString());
  for (const [index, input] of inputs.entries()) {
    let actual: unknown; try { actual = { ok: true, value: decodeTeamResult(input) }; } catch { actual = { ok: false }; }
    expect({ input, result: actual }).toEqual({ input, result: oracle[index] });
  }
  const worker = decodeTeamResult({ ...base, evidence: [{ ref: "event" }] });
  const review = decodeTeamResult({ ...base, substage: "review_running" });
  expect(reducePipelineReview(worker, review).selected_evidence).toEqual(worker.evidence);
});
