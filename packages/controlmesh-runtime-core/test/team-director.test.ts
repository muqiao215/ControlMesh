import { expect, test } from "bun:test";
import { resolve } from "node:path";
import { DirectorPolicy, type DirectorOptions } from "../src/team-director";
import { decodeDirectorDecision } from "../src/team-control-decision";
import { decodeTeamResult } from "../src/team-result-validation";

test("director policy matches Python rounds, all four budgets, collection and terminal evidence", () => {
  type Step = { op: "decide"; decision: string; round_index: number; dispatch_roles?: string[] } | { op: "collect" } | { op: "resume" };
  const dispatch = (round_index: number): Step => ({ op: "decide", decision: "dispatch_workers", round_index, dispatch_roles: ["a", "b"] });
  const decide = (decision: string, round_index: number): Step => ({ op: "decide", decision, round_index });
  const collect: Step = { op: "collect" }, resume: Step = { op: "resume" };
  const flows: Step[][] = [
    [dispatch(1), collect, decide("complete", 1)],
    [dispatch(1), collect, dispatch(2), collect, dispatch(3), collect, dispatch(4)],
    [decide("needs_parent_input", 1), resume, decide("needs_parent_input", 1)],
    [dispatch(1), collect, decide("needs_repair", 1), dispatch(2), collect, decide("needs_repair", 2)],
    [dispatch(1), collect, decide("failed", 1)],
    [decide("needs_repair", 1)], [dispatch(3)], [decide("complete", 1)],
  ];
  const options: DirectorOptions[] = [{}, { max_rounds: 1 }, { max_total_worker_dispatches: 2 }, { max_parallel_workers_per_round: 1 },
    { max_parent_interruptions: 0 }, { max_repair_cycles_per_run: 0 }, { max_rounds: 2, max_total_worker_dispatches: 3 },
    { max_parallel_workers_per_round: 0, max_total_worker_dispatches: 0 }];
  const cases = options.flatMap(options => flows.map(steps => ({ options, steps })));
  const script = `import json,sys\nfrom datetime import datetime\nfrom types import SimpleNamespace\nfrom controlmesh.team.execution import TeamDirectorWorkerRuntime,TeamTopologyExecutionSpine\nfrom controlmesh.team.models import TeamDirectorDecision,TeamStructuredResult\nclass Hub:\n def __init__(self):self.state=None;self._config=SimpleNamespace(max_parallel=2)\n def read_topology_state(self,task):return self.state\n def write_topology_state(self,task,payload):self.state=payload\nat=datetime.fromisoformat('2026-09-12T01:02:03+00:00');rows=[]\nfor case in json.load(sys.stdin):\n p=TeamDirectorWorkerRuntime(TeamTopologyExecutionSpine(Hub()),**case['options']);state=p.start('parent',planning_summary='plan',at=at);states=[state.model_dump(mode='json')];ok=True\n for step in case['steps']:\n  try:\n   if step['op']=='resume':state=p.resume_from_parent('parent',parent_input='answer',at=at)\n   elif step['op']=='collect':state=p.record_worker_results('parent',[TeamStructuredResult(topology='director_worker',substage='collecting',worker_role=role,status=status,summary=role+' result',evidence=[{'ref':'event:'+role}],artifacts=[{'ref':'file:'+role}]) for role,status in [('a','completed'),('b','failed')]],at=at)\n   else:\n    action=step['decision'];d=TeamDirectorDecision(round_index=step['round_index'],decision=action,dispatch_roles=step.get('dispatch_roles',[]),summary=action+' summary',repair_hint='fix' if action=='needs_repair' else None,stop_reason='parent_decision_required' if action=='needs_parent_input' else 'no_viable_path' if action=='failed' else None)\n    state=p.record_director_decision('parent',d,parent_question='question',waiting_on='user',at=at)\n   states.append(state.model_dump(mode='json'))\n  except ValueError:ok=False;break\n rows.append({'ok':ok,'states':states})\nprint(json.dumps(rows))`;
  const child = Bun.spawnSync(["uv", "run", "python", "-c", script], { cwd: resolve(import.meta.dir, "../../.."), stdin: Buffer.from(JSON.stringify(cases)), stdout: "pipe", stderr: "pipe", timeout: 30_000 });
  expect({ code: child.exitCode, stderr: child.stderr.toString() }).toEqual({ code: 0, stderr: "" });
  const oracle = JSON.parse(child.stdout.toString()), at = new Date("2026-09-12T01:02:03Z");
  for (const [i, input] of cases.entries()) {
    const policy = new DirectorPolicy(2, input.options); let state = policy.start("parent", "plan", "director", undefined, at);
    const states = [state]; let ok = true;
    for (const step of input.steps) {
      try {
        if (step.op === "resume") state = policy.resume(state, "answer", undefined, at);
        else if (step.op === "collect") state = policy.collect(state, [["a", "completed"], ["b", "failed"]].map(([role, status]) => decodeTeamResult({ topology: "director_worker", substage: "collecting", worker_role: role, status, summary: `${role} result`, evidence: [{ ref: `event:${role}` }], artifacts: [{ ref: `file:${role}` }] })), undefined, at);
        else {
          const value = step, action = value.decision;
          state = policy.decide(state, decodeDirectorDecision({ round_index: value.round_index, decision: action, dispatch_roles: value.dispatch_roles ?? [], summary: `${action} summary`,
            repair_hint: action === "needs_repair" ? "fix" : null, stop_reason: action === "needs_parent_input" ? "parent_decision_required" : action === "failed" ? "no_viable_path" : null }), { question: "question", waiting_on: "user" }, at);
        }
        states.push(state);
      } catch { ok = false; break; }
    }
    expect({ input, actual: { ok, states } }).toEqual({ input, actual: oracle[i] });
  }
});
