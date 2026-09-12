import { expect, test } from "bun:test";
import { resolve } from "node:path";
import { startTopology } from "../src/team-topology";
import { applyPipelineResult, dispatchPipelineWorker, resumePipeline } from "../src/team-pipeline";
import { decodeTeamResult } from "../src/team-result-validation";

test("pipeline worker/review/repair decisions and interruption match the real Python runtime", () => {
  const statuses = ["completed", "failed", "blocked", "needs_parent_input", "needs_repair"];
  const sequences: string[][] = [];
  for (const worker of statuses) for (const review of statuses) for (const repair of statuses) sequences.push([worker, review, repair]);
  sequences.push(["completed", "needs_repair", "completed", "completed"], ["completed", "needs_parent_input", "resume", "completed"]);
  const value = (status: string, stage: string) => ({ topology: "pipeline", substage: stage, worker_role: stage === "review_running" ? "reviewer" : "worker",
    status, summary: `  ${"🙂 ".repeat(60)}result  `, evidence: [{ ref: "event:one" }], artifacts: [], next_action: " next ",
    needs_parent_input: status === "needs_parent_input", repair_hint: status === "needs_repair" ? " fix " : null });
  const script = `import json,sys\nfrom datetime import datetime\nfrom controlmesh.team.execution import TeamPipelineRuntime,TeamTopologyExecutionSpine\nfrom controlmesh.team.models import TeamStructuredResult\nclass Hub:\n def __init__(self):self.state=None\n def read_topology_state(self,task):return self.state\n def write_topology_state(self,task,payload):self.state=payload\nrows=[]\nat=datetime.fromisoformat('2026-09-12T01:02:03+00:00')\nfor sequence in json.load(sys.stdin):\n p=TeamPipelineRuntime(TeamTopologyExecutionSpine(Hub()));p.start('parent',planning_summary='plan',at=at);state=p.dispatch_worker('parent',at=at);states=[state.model_dump(mode='json')];ok=True\n for status in sequence:\n  try:\n   if status=='resume':state=p.resume_from_parent('parent',parent_input='answer',at=at)\n   else:\n    stage=state.current_checkpoint.substage\n    r=TeamStructuredResult(topology='pipeline',substage=stage,worker_role='reviewer' if stage=='review_running' else 'worker',status=status,summary='  '+'🙂 '*60+'result  ',evidence=[{'ref':'event:one'}],artifacts=[],next_action=' next ',needs_parent_input=status=='needs_parent_input',repair_hint=' fix ' if status=='needs_repair' else None)\n    if stage=='worker_running':state=p.record_worker_result('parent',r,at=at)\n    elif stage=='review_running':state=p.record_review_result('parent',r,parent_question='question',waiting_on='user',at=at)\n    elif stage=='repairing':state=p.record_repair_result('parent',r,at=at)\n    else:raise ValueError('terminal')\n   states.append(state.model_dump(mode='json'))\n  except ValueError:ok=False;break\n rows.append({'ok':ok,'states':states})\nprint(json.dumps(rows))`;
  const child = Bun.spawnSync(["uv", "run", "python", "-c", script], { cwd: resolve(import.meta.dir, "../../.."), stdin: Buffer.from(JSON.stringify(sequences)), stdout: "pipe", stderr: "pipe", timeout: 30_000 });
  expect({ code: child.exitCode, stderr: child.stderr.toString() }).toEqual({ code: 0, stderr: "" });
  const oracle = JSON.parse(child.stdout.toString()), at = new Date("2026-09-12T01:02:03Z");
  for (const [index, sequence] of sequences.entries()) {
    let state = dispatchPipelineWorker(startTopology("parent", "pipeline", { active_roles: ["planner"], latest_summary: "plan" }, at), "worker", undefined, at);
    const states = [state]; let ok = true;
    for (const status of sequence) {
      try {
        state = status === "resume" ? resumePipeline(state, "answer", undefined, at)
          : applyPipelineResult(state, decodeTeamResult(value(status, state.checkpoints.at(-1)!.substage)), { parent_question: "question", waiting_on: "user" }, at);
        states.push(state);
      } catch { ok = false; break; }
    }
    expect({ sequence, result: { ok, states } }).toEqual({ sequence, result: oracle[index] });
  }
});
