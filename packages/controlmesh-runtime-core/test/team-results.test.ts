import { expect, test } from "bun:test";
import { resolve } from "node:path";
import { reducePipelineReview, reducePipelineTerminal, reduceFanoutResult, reduceFailedFanout } from "../src/team-results";

test("pipeline/fanout reductions match live Python including independent fallback and failed batches", () => {
  const script = `
import json
from types import SimpleNamespace
from controlmesh.team.models import TeamStructuredResult
from controlmesh.team.execution import TeamPipelineRuntime, TeamFanoutMergeRuntime
rows=[]
def result(topology, role, evidence, artifacts, status='completed', stage=None):
 return TeamStructuredResult(topology=topology,worker_role=role,status=status,substage=stage or ('review_running' if topology=='pipeline' else 'collecting'),summary=role+' summary',evidence=[{'ref':x} for x in evidence],artifacts=[{'ref':x} for x in artifacts],repair_hint='repair' if status=='needs_repair' else None)
for kind in ['pipeline','fanout_merge']:
 for status in ['completed','failed','needs_repair']:
  for select_e in [False,True]:
   for select_a in [False,True]:
    worker=result(kind,'worker',['worker-e','worker-e'],['worker-a'])
    final=result(kind,'review',['review-e'] if select_e else [],['review-a'] if select_a else [],status)
    if kind=='pipeline':
     runtime=TeamPipelineRuntime(None)
     state=SimpleNamespace(current_checkpoint=SimpleNamespace(result=worker.model_copy(update={'substage':'worker_running'})))
     expected=runtime._reduce_review_result(state,final)
     terminal=runtime._terminal_reduced_result(final).model_dump()
     rows.append({'kind':kind,'worker':worker.model_dump(),'final':final.model_dump(),'expected':expected.model_dump(),'terminal':terminal})
    else:
     failed=result(kind,'failed',['failed-e'],['failed-a'],'failed')
     ignored=result(kind,'ignored',['ignored-e'],['ignored-a'],stage='reducing')
     checkpoints=[None,worker,failed,ignored,worker]
     state=SimpleNamespace(checkpoints=[SimpleNamespace(result=x) for x in checkpoints])
     expected=TeamFanoutMergeRuntime(None)._reduce_reducer_result(state,final)
     rows.append({'kind':kind,'checkpoints':[x.model_dump() if x else None for x in checkpoints],'final':final.model_dump(),'expected':expected.model_dump()})
failed=[result('fanout_merge','one',['one-e'],['one-a'],'failed'),result('fanout_merge','two',[],[],'failed')]
batches=[{'input':[x.model_dump() for x in group],'expected':TeamFanoutMergeRuntime(None)._failed_worker_batch_result(group).model_dump()} for group in [[],failed]]
print(json.dumps({'rows':rows,'batches':batches}))
`;
  const process = Bun.spawnSync(["uv", "run", "python", "-c", script], { cwd: resolve(import.meta.dir, "../../.."), stdout: "pipe", stderr: "pipe", timeout: 30_000 });
  expect({ exit: process.exitCode, stderr: process.stderr.toString() }).toEqual({ exit: 0, stderr: "" });
  const fixtures = JSON.parse(process.stdout.toString());
  for (const row of fixtures.rows) {
    const before = JSON.stringify(row);
    const actual = row.kind === "pipeline" ? reducePipelineReview(row.worker, row.final) : reduceFanoutResult(row.checkpoints, row.final);
    expect(actual).toEqual(row.expected);
    if (row.kind === "pipeline") expect(reducePipelineTerminal(row.final)).toEqual(row.terminal);
    if (actual.selected_evidence.length) actual.selected_evidence[0].ref = "changed consumer copy";
    expect(JSON.stringify(row)).toBe(before);
  }
  for (const row of fixtures.batches) expect(reduceFailedFanout(row.input)).toEqual(row.expected);
  expect(fixtures.rows).toHaveLength(24);
});
