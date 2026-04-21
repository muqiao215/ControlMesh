# Execution Plan

## Goal

在已完成的 Step 1-5 基线上，继续推进两个延后拓扑：

- `director_worker`
- `debate_judge`

本次计划更新的重点不是再排一个线性 Step 6-10，而是把下一波工作改造成：

- 先串行冻结共享合同
- 再并行推进可独立分支
- 最后串行收口回归

不重开第一条已批准实现线，不引入新的抽象层。

## Current Reference

- primary extension reference: `architecture_v3.md`
- primary architecture reference: `architecture_v2.md`
- historical context only: `architecture_v1.md`

## Historical Baseline

以下步骤已完成，作为历史基线保留：

### Step 1: Contract Pass `[completed]`

- topology identifiers
- `pipeline` / `fanout_merge` topology-local substages
- schema-versioned result models
- neutral result item taxonomy
- reduced result / progress summary boundaries

### Step 2: Execution Spine Pass `[completed]`

- `TaskHub`-backed topology execution seam
- interruption / resume base behavior
- `controlmesh/team/execution.py`

### Step 3: `pipeline` Pass `[completed]`

- ordered worker dispatch
- reviewer / reducer transitions
- compressed progress summaries

### Step 4: `fanout_merge` Pass `[completed]`

- bounded parallel dispatch
- collecting / reducing substages
- partial-failure policy

### Step 5: Presentation Pass `[completed]`

- explicit topology ingress
- topology-aware compact progress rendering
- task selector integration

## Stage 6: Shared Contract Freeze `[serial]`

这是下一波工作的唯一强制串行起点。
在该阶段结束前，不开启 runtime 分支开发。

### Step 6.1: Freeze topology ids and substages

Files:

- `controlmesh/team/contracts.py`
- `controlmesh/team/models.py`

Add:

- topology identifiers for `director_worker` / `debate_judge`
- topology-local substages for both deferred topologies

Verification:

- contract/model validation tests
- invalid topology / invalid substage tests

### Step 6.2: Freeze loop-aware checkpoint contract

Files:

- `controlmesh/team/models.py`
- `controlmesh/team/execution.py`

Add:

- optional `round_index` / `round_limit` on checkpoints
- optional `round_index` / `round_limit` on progress summaries

Hard constraints:

- `round_index` is 1-based
- `round_limit` is frozen per run
- runtime may not infer round state from free text
- `round_index > round_limit` is invalid, not auto-corrected

Verification:

- round-aware checkpoint validation tests
- progress-summary projection tests
- invalid round transition tests

### Step 6.3: Freeze control decision contracts

Files:

- `controlmesh/team/models.py`

Add:

- `TeamDirectorDecision`
- `TeamJudgeDecision`

Hard constraints:

- dispatch / winner / next-round targets live in typed fields
- runtime branches on `decision`, not on `summary` or `next_action`
- free-text orchestration is rejected

Verification:

- contract validation tests
- missing typed-field negative tests
- “summary contains instructions but typed field missing” rejection tests

### Step 6.4: Freeze boundary guardrails

Files:

- `controlmesh/team/models.py`
- tests under `tests/team/`

Freeze:

- worker/candidate cannot directly ask parent in day one cuts
- director/judge are the only parent-input boundary
- final-round judge tie escalates to parent instead of auto-resolving
- reducer/director/judge control remains transcript-free

Verification:

- invalid worker-parent boundary tests
- invalid candidate-parent boundary tests
- final-round tie escalation tests
- transcript-leak negative tests

### Stage 6 Exit Gate

Only proceed when all of the following are true:

- topology ids / substages are frozen
- round metadata placement and invariants are frozen
- director/judge typed decision contracts are frozen
- negative guardrail matrix exists

## Stage 7: Parallel Delivery Wave `[parallel after Stage 6]`

Stage 7 分支可以并行推进，但都必须建立在 Stage 6 已冻结的 shared seam 之上。

### Step 7A: `director_worker` Runtime Pass `[parallel branch]`

Files:

- `controlmesh/team/execution.py`
- tests under `tests/team/`

Add:

- `TeamDirectorWorkerRuntime`
- bounded planning / dispatch / collect / decide loop
- director-only ask-parent boundary
- director-owned terminal reduction onto `TeamReducedTopologyResult`

Must enforce:

- one typed director decision per control step
- no hidden re-dispatch inside one runtime transition
- explicit budget closure on rounds / repairs / parent interruptions / total dispatches

Verification:

- happy path with early completion
- second-round dispatch path
- repair path
- ask-parent / resume returning to `planning`, `director_deciding`, or `repairing`
- budget exhaustion closes to `failed` or `needs_parent_input`
- hidden re-dispatch negative tests

### Step 7B: `debate_judge` Runtime Pass `[parallel branch]`

Files:

- `controlmesh/team/execution.py`
- tests under `tests/team/`

Add:

- `TeamDebateJudgeRuntime`
- bounded candidate-round handling
- typed judge decision intake
- tie / inconclusive / repair policy
- terminal reduction onto `TeamReducedTopologyResult`

Must enforce:

- judge reads typed candidate envelopes only
- non-final tie advances round
- final-round tie escalates to parent
- no confidence-based auto tie-break in day one

Verification:

- happy path with winner in round 1
- tie in round 1 advances to round 2
- final-round tie escalates to `needs_parent_input`
- insufficient evidence goes to repair
- judge interruption / resume returns to `judging`
- auto tie-break negative tests

### Step 7C: Round-Aware Presentation / Ingress Pass `[parallel branch]`

Files:

- topology-aware renderer / selector surfaces under `controlmesh/orchestrator/`
- any presentation helpers already used by Step 5

Add:

- explicit topology selection ingress for `director_worker` / `debate_judge`
- task selector / compact renderer support for `round_index` / `round_limit`
- usage/help text expansion for all approved topologies

Must enforce:

- parent-facing output stays compressed
- no transcript leakage
- round display is read from contract fields, not inferred from prose

Verification:

- `/tasks topology status` shows all four approved topologies
- `/tasks topology director_worker` and `/tasks topology debate_judge` ingress succeed
- selector rendering shows round-aware compact progress without agent chatter

### Step 7D: Negative / Regression Matrix Pass `[parallel branch]`

Files:

- tests under `tests/team/`
- topology line planning artifacts if a test matrix file is needed

Add:

- contract negative matrix
- invalid parent-boundary matrix
- invalid round-state matrix
- transcript-leak matrix
- cross-topology interruption/resume matrix skeleton

Notes:

- This branch can begin as soon as Stage 6 freezes the contract
- Final execution still waits for 7A / 7B / 7C to land

Verification:

- negative matrices are runnable, not just listed
- each Stage 6 guardrail has a corresponding failing-case assertion

## Stage 8: Serial Convergence and Regression `[serial]`

Stage 8 is the mandatory收口阶段。
Even if Stage 7 branches were developed in parallel, completion is only declared here.

### Step 8.1: Merge runtime branches on the shared seam

Files:

- `controlmesh/team/execution.py`

Tasks:

- reconcile `director_worker` and `debate_judge` implementations on one execution seam
- ensure both respect the same checkpoint / interruption / progress contracts

Verification:

- no contract drift between the two runtimes
- no shared helper silently reintroduces transcript parsing

### Step 8.2: Align presentation with actual runtime behavior

Files:

- `controlmesh/orchestrator/` presentation surfaces
- any shared topology summary helpers

Tasks:

- ensure rendered round state matches actual checkpoint fields
- ensure waiting / repair / completed states are consistent across all four topologies

Verification:

- manual/automated rendering checks across four topologies
- no topology-specific fallback formatting path

### Step 8.3: Run the four-topology regression matrix

Run:

- full regression on `pipeline` / `fanout_merge`
- interruption/resume matrix across all four topologies
- progress rendering regression across all four topologies
- invalid-topology / invalid-substage / invalid-decision contract coverage

Exit criteria:

- old topologies remain behaviorally stable
- new topologies satisfy all Stage 6 guardrails
- no parent-boundary leakage
- no silent final-round tie resolution

## Explicit Non-Sequence

Do not start with:

- auto-topology selection
- generic router layer
- dashboard work
- generic planner graph

## Ready-To-Code Checklist

- [x] comparative review absorbed
- [x] architecture v2 written
- [x] architecture v3 rewritten with hardened guardrails
- [x] Step 1-5 historical baseline frozen
- [x] serial contract-freeze stage defined
- [x] parallel delivery wave defined
- [x] serial convergence stage defined
- [x] TaskHub-first execution spine acknowledged
- [x] interruption/resume kept as base contract
- [x] director_worker minimum product cut frozen
- [x] debate_judge minimum product cut frozen
- [ ] implementation branch/code work started
