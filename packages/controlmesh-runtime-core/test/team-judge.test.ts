import { expect, test } from "bun:test";
import { resolve } from "node:path";
import { JudgePolicy } from "../src/team-judge";
import { decodeJudgeDecision } from "../src/team-control-decision";
import { decodeTeamResult } from "../src/team-result-validation";

test("judge matches Python rounds, repairs, current-batch winners and final-tie escalation", () => {
  const flows = [["winner"], ["advance", "collect", "winner"], ["advance", "collect", "advance"], ["repair", "candidates", "collect", "winner"],
    ["parent", "resume", "winner"], ["tie"], ["failed"], ["advance", "collect", "old_winner"]];
  const cases = [1, 2].flatMap(limit => ["completed", "failed", "needs_repair"].flatMap(status => flows.map(steps => ({ limit, status, steps }))));
  const script = `import json,sys\nfrom datetime import datetime\nfrom types import SimpleNamespace\nfrom controlmesh.team.execution import TeamDebateJudgeRuntime,TeamTopologyExecutionSpine\nfrom controlmesh.team.models import TeamJudgeDecision,TeamStructuredResult\nclass Hub:\n def __init__(self):self.state=None;self._config=SimpleNamespace(max_parallel=2)\n def read_topology_state(self,task):return self.state\n def write_topology_state(self,task,payload):self.state=payload\nat=datetime.fromisoformat('2026-09-12T01:02:03+00:00');rows=[]\nfor case in json.load(sys.stdin):\n p=TeamDebateJudgeRuntime(TeamTopologyExecutionSpine(Hub()));p.start('parent',planning_summary='plan',round_limit=case['limit'],at=at);state=p.start_candidate_round('parent',candidate_roles=['a','b'],at=at);states=[state.model_dump(mode='json')];ok=True;generation=0;last_roles=['a','b']\n for step in ['collect']+case['steps']:\n  try:\n   if step=='collect':\n    generation+=1;last_roles=list(state.current_checkpoint.active_roles);state=p.record_candidate_results('parent',[TeamStructuredResult(topology='debate_judge',substage='collecting',worker_role=role,status=case['status'] if i==0 else 'completed',summary=role+' result',repair_hint='fix' if case['status']=='needs_repair' and i==0 else None,evidence=[{'ref':str(generation)+':'+role}],artifacts=[{'ref':'file:'+role}]) for i,role in enumerate(last_roles)],at=at)\n   elif step=='candidates':state=p.start_candidate_round('parent',candidate_roles=last_roles,at=at)\n   elif step=='resume':state=p.resume_from_parent('parent',parent_input='answer',at=at)\n   else:\n    action={'winner':'select_winner','old_winner':'select_winner','advance':'advance_round','repair':'needs_repair','parent':'needs_parent_input','tie':'needs_parent_input','failed':'failed'}[step]\n    d=TeamJudgeDecision(round_index=state.current_checkpoint.round_index,decision=action,summary=step+' summary',winner_role=('a' if step=='old_winner' else last_roles[0]) if action=='select_winner' else None,next_candidate_roles=['c','d'] if step=='advance' else [],repair_hint='fix' if step=='repair' else None,stop_reason='final_round_tie' if step=='tie' else 'parent_decision_required' if step=='parent' else 'no_viable_candidate' if step=='failed' else None)\n    state=p.record_judge_decision('parent',d,parent_question='question',waiting_on='user',at=at)\n   states.append(state.model_dump(mode='json'))\n  except ValueError:ok=False;break\n rows.append({'ok':ok,'states':states})\nprint(json.dumps(rows))`;
  const child = Bun.spawnSync(["uv", "run", "python", "-c", script], { cwd: resolve(import.meta.dir, "../../.."), stdin: Buffer.from(JSON.stringify(cases)), stdout: "pipe", stderr: "pipe", timeout: 30_000 });
  expect({ code: child.exitCode, stderr: child.stderr.toString() }).toEqual({ code: 0, stderr: "" });
  const oracle = JSON.parse(child.stdout.toString()), at = new Date("2026-09-12T01:02:03Z");
  for (const [i, input] of cases.entries()) {
    const policy = new JudgePolicy(2); let state = policy.candidates(policy.start("parent", "plan", input.limit, "judge", at), ["a", "b"], undefined, at);
    const states = [state]; let ok = true, generation = 0, lastRoles = ["a", "b"];
    for (const step of ["collect", ...input.steps]) {
      try {
        if (step === "collect") {
          generation++; lastRoles = [...state.checkpoints.at(-1)!.active_roles];
          state = policy.collect(state, lastRoles.map((role, index) => decodeTeamResult({ topology: "debate_judge", substage: "collecting", worker_role: role,
            status: index === 0 ? input.status : "completed", summary: `${role} result`, repair_hint: input.status === "needs_repair" && index === 0 ? "fix" : null,
            evidence: [{ ref: `${generation}:${role}` }], artifacts: [{ ref: `file:${role}` }] })), "judge", at);
        } else if (step === "candidates") state = policy.candidates(state, lastRoles, undefined, at);
        else if (step === "resume") state = policy.resume(state, "answer", undefined, at);
        else {
          const action = ({ winner: "select_winner", old_winner: "select_winner", advance: "advance_round", repair: "needs_repair", parent: "needs_parent_input", tie: "needs_parent_input", failed: "failed" } as Record<string, string>)[step];
          state = policy.decide(state, decodeJudgeDecision({ round_index: state.checkpoints.at(-1)!.round_index, decision: action, summary: `${step} summary`,
            winner_role: action === "select_winner" ? step === "old_winner" ? "a" : lastRoles[0] : null, next_candidate_roles: step === "advance" ? ["c", "d"] : [],
            repair_hint: step === "repair" ? "fix" : null, stop_reason: step === "tie" ? "final_round_tie" : step === "parent" ? "parent_decision_required" : step === "failed" ? "no_viable_candidate" : null }), { question: "question", waiting_on: "user" }, at);
        }
        states.push(state);
      } catch { ok = false; break; }
    }
    expect({ input, actual: { ok, states } }).toEqual({ input, actual: oracle[i] });
    if (input.steps[0] === "repair") expect(state.checkpoints.at(-1)!.reduced_result!.selected_evidence[0]!.ref).toBe("2:a");
  }
});
