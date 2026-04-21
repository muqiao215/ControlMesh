# Orchestration Topology Pack v3

## Status

用于 Step 1-5 已完成后的下一条规划参考。

`architecture_v3.md` 不重做第一条已批准实现线，而是在既有实现基线上，为以下两个延后拓扑给出可安全开工的增量设计：

- `director_worker`
- `debate_judge`

这版 v3 的目标不是再证明方向，而是把“容易做偏”的地方写成硬约束，并把下一波实施顺序改写成可冻结接口、可并行推进、可最终收口的执行形状。

## 已冻结的基线

以下内容已经实现并批准，v3 不重设计：

- Step 1 contract pass
- Step 2 TaskHub-backed execution spine
- Step 3 `pipeline` runtime
- Step 4 `fanout_merge` runtime
- Step 5 ingress / presentation wiring

这意味着：

- ControlMesh 继续是唯一 runtime owner
- `TaskHub` 继续是长任务、中断、恢复的执行脊柱
- `controlmesh/team/execution.py` 是唯一允许扩展的 topology runtime seam
- `TeamStructuredResult` / `TeamReducedTopologyResult` / `TeamTopologyExecutionState` 继续作为主合同
- `multiagent/` 仍然只是 plumbing，不进入产品拓扑抽象

## v3 的决定性结论

### 1. 下一条线只做两种显式拓扑

只扩展：

- `director_worker`
- `debate_judge`

明确不做：

- auto topology selection
- generic router / meta-framework
- topology marketplace
- transcript-first 协作
- dashboard / 可视化放大

### 2. 两种新拓扑都必须建立在现有 structured-result 哲学上

保持不变的基础协议：

- `summary`
- `evidence`
- `confidence`
- `artifacts`
- `next_action`

worker / candidate / reducer / judge / director 的输入都必须是 typed result 或 typed decision。
任何需要靠解析 transcript 自由文本来继续流程的方案都不进入 v3。

### 3. `director` 不是 reducer 的别名，而是独立控制角色

`director_worker` 里，director 的职责不是只做一次归并，而是：

- 初始分解
- 每轮 dispatch 决策
- 停止条件判断
- ask-parent 唯一外露边界
- 终局压缩总结

所以 day one 必须把 director 建模为 distinct control role，而不是“会继续派工的 reducer”。

### 4. `debate_judge` day one 不是自由辩论，而是受控的候选轮次

`debate_judge` 的 day one cut 不是 agent 之间互相聊天。
它是：

- 多个 candidate 并行产出 typed candidate result
- judge 基于 typed candidate result 做裁决或推进下一轮
- 父聊天只看到压缩后的 phase state 和 judge summary

也就是说，“debate” 在 v3 里是受控的 candidate rounds，不是 transcript battle。

## 复用与扩展边界

### 可以直接复用、无需改语义的部分

- `TeamTopologyExecutionSpine`
  - checkpoint 持久化
  - `waiting_parent` interruption state
  - `resume_from_parent()` 语义
- `TeamStructuredResult`
  - worker / candidate 结果信封
- `TeamReducedTopologyResult`
  - terminal reduced result
- `TeamTopologyProgressSummary`
  - 压缩展示方向不变
- `render_topology_progress_lines()`
  - 继续只展示 phase state，不展示 agent chatter
- `/tasks topology ...`
  - 继续显式选择，不走自动选择

### 必须做的最小扩展

#### A. 拓扑枚举与 substage 扩展

在 `contracts.py` 中新增：

- `director_worker`
- `debate_judge`

并新增 topology-local substages。

#### B. loop-aware 进度元信息

Step 1-5 的状态模型适合单轮 `pipeline` / `fanout_merge`，但不够表达多轮决策。
v3 需要对 checkpoint / progress summary 做最小增强：

- `round_index: int | None`
- `round_limit: int | None`

只加这两个字段，不引入通用 graph / DAG / router metadata。

#### C. 新增 topology-local typed decision contracts

`next_action: str` 不能承担“继续派工/进入下一轮/请求父输入/失败闭环”的控制语义。
因此 v3 需要两个新合同：

- `TeamDirectorDecision`
- `TeamJudgeDecision`

它们是 control decision，不是 worker transcript。

## `director_worker` 的最小产品切口

### 使用场景

仅用于：

- 任务需要先做分解，再按轮次派工
- 每一轮的下一步是否继续，必须由一个中心角色决定
- `fanout_merge` 的单轮 reducer 已经不够

不用于：

- 任意深度的自主规划
- 多级经理链
- worker 自主再派 worker

### day one 角色模型

- `director`
- `worker[n]`

day one 不引入独立 verifier。
终局总结由 director 输出，仍然落成 `TeamReducedTopologyResult`。

### day one substage

- `planning`
- `dispatching`
- `collecting`
- `director_deciding`
- `waiting_parent`
- `repairing`
- `completed`
- `failed`

说明：

- `planning` 只用于首轮前的 director 分解
- 之后每轮都回到 `director_deciding`
- 不新增 `review_running`
- 不做独立 `final_reducing`

### day one 结果与决策合同

#### worker 结果

继续复用 `TeamStructuredResult`，不新造 worker envelope。

要求：

- `topology == "director_worker"`
- worker 终结于 `substage == "collecting"`
- 允许状态：
  - `completed`
  - `failed`
  - `needs_repair`

day one 不允许 worker 直接触发 `needs_parent_input`。
worker 缺信息时，只能通过 `needs_repair` 把缺口抬回 director。

#### director 决策

新增：

```python
class TeamDirectorDecision(BaseModel):
    schema_version: int
    topology: Literal["director_worker"]
    round_index: int
    decision: Literal[
        "dispatch_workers",
        "complete",
        "needs_parent_input",
        "needs_repair",
        "failed",
    ]
    dispatch_roles: list[str] = []
    summary: str
    evidence: list[TeamEvidenceRef] = []
    confidence: float | None = None
    artifacts: list[TeamArtifactRef] = []
    next_action: str | None = None
    repair_hint: str | None = None
    stop_reason: str | None = None
```

最关键的点：

- `dispatch_roles` 必须是 typed list，不能藏在文本里
- `complete` / `failed` 是 director 的终局控制决定
- `needs_parent_input` 只允许 director 发出

### director 的停止条件

day one 强制以下停止条件：

- director 明确给出 `decision == "complete"`
- director 明确给出 `decision == "failed"`
- 已达到 `max_rounds`
- 已达到 `max_total_worker_dispatches`
- 当前轮没有任何成功结果且没有可接受 repair path

预算耗尽时不允许 silent loop。
必须终结为：

- `failed`
- 或 `needs_parent_input`

### repair / ask-parent 边界

day one 规则必须非常硬：

- worker 不能直接 ask-parent
- director 是唯一允许 ask-parent 的角色
- worker 只能：
  - 成功返回
  - 失败返回
  - 请求 repair
- director 收到 repair 信号后，决定：
  - 重新派工
  - 终止失败
  - 请求父输入

### interruption / resume 的 day one 要求

必须支持：

- `planning -> waiting_parent -> planning`
- `director_deciding -> waiting_parent -> director_deciding`
- `repairing -> waiting_parent -> repairing`

不支持：

- 恢复到某个半完成 worker transcript
- 从未记录 checkpoint 的中间态恢复

resume 永远回到最近的 typed checkpoint，而不是自由文本上下文。

### 显式预算

day one 默认预算：

- `max_rounds = 3`
- `max_parallel_workers_per_round <= TaskHub.parallel_limit`
- `max_parent_interruptions = 1`
- `max_repair_cycles_per_run = 1`

实现层可以再加一个更硬的总量保护：

- `max_total_worker_dispatches <= max_rounds * max_parallel_workers_per_round`

### 明确延期

以下全部延期：

- director 自主创建新角色
- nested director
- worker-to-worker direct routing
- director 自动改写 topology
- 动态并发自适应
- director 外挂 verifier

## `debate_judge` 的最小产品切口

### 使用场景

仅用于：

- 需要两个或少数几个 competing candidates
- 需要 judge 基于 typed evidence 做裁决
- 任务价值在“高风险选择”而不是“大规模搜索”

不用于：

- 多方自由辩论聊天室
- transcript-based rebuttal
- 加权投票系统

### day one 角色模型

- `candidate_a`
- `candidate_b`
- `judge`

day one 固定为两名 candidate。
不做 3+ candidates，不做 judge panel。

### day one substage

- `planning`
- `candidate_round`
- `collecting`
- `judging`
- `waiting_parent`
- `repairing`
- `completed`
- `failed`

这里的“round”是 judge 驱动的下一轮候选生成，不是 agent 间自由对话。

### day one 结果与裁决合同

#### candidate 结果

继续复用 `TeamStructuredResult`。

要求：

- `topology == "debate_judge"`
- `substage == "collecting"`
- candidate 之间不共享 transcript
- judge 读取的是 candidate envelope，不是对话历史

允许状态：

- `completed`
- `failed`
- `needs_repair`

day one 也不允许 candidate 直接 ask-parent。

#### judge 决策

新增：

```python
class TeamJudgeDecision(BaseModel):
    schema_version: int
    topology: Literal["debate_judge"]
    round_index: int
    decision: Literal[
        "select_winner",
        "advance_round",
        "needs_parent_input",
        "needs_repair",
        "failed",
    ]
    winner_role: str | None = None
    next_candidate_roles: list[str] = []
    summary: str
    evidence: list[TeamEvidenceRef] = []
    confidence: float | None = None
    artifacts: list[TeamArtifactRef] = []
    next_action: str | None = None
    repair_hint: str | None = None
    stop_reason: str | None = None
```

关键限制：

- `advance_round` 必须显式给出 `next_candidate_roles`
- `select_winner` 必须显式给出 `winner_role`
- tie / inconclusive 不能只写在自由文本里

### tie / inconclusive / repair 政策

day one 采用保守政策：

- 非最终轮出现 tie
  - judge 发出 `advance_round`
  - 给出更窄的比较焦点
- 最终轮仍然 tie
  - judge 发出 `needs_parent_input`
  - 父聊天只看到压缩 tradeoff summary，不看到候选 transcript
- 证据不足或候选都没有达到可裁决门槛
  - judge 发出 `needs_repair`
  - repair 重新进入候选轮，而不是进入自由聊天

这意味着：

- day one 不做“强行自动选一个”
- day one 不做“平票时按模型置信度硬裁”

### evidence aggregation 与 transcript leakage

judge 的输入只能是：

- candidate 的 `summary`
- `evidence`
- `confidence`
- `artifacts`
- `next_action`

judge 不读取：

- candidate 间私聊 transcript
- 原始 prompt chain
- 冗长 reasoning dump

父聊天也只能看到：

- 当前 round
- 当前 substage
- judge summary
- 是否需要父输入 / repair

### 收敛与轮数上限

day one 收敛规则：

- 任何一轮 judge 可以直接 `select_winner`
- 否则最多再推进一轮
- 达到轮数上限后仍未收敛，只允许：
  - `needs_parent_input`
  - 或 `failed`

day one 默认预算：

- `candidate_count = 2`
- `max_rounds = 2`
- `max_parent_interruptions = 1`
- `max_repair_cycles_per_run = 1`

### interruption / resume 的 day one 要求

必须支持：

- `judging -> waiting_parent -> judging`
- `repairing -> waiting_parent -> repairing`

可以不支持：

- 从某个 candidate 的未完成中间 chatter 恢复
- judge panel 内部多角色恢复

### 明确延期

以下全部延期：

- 3+ candidates
- judge ensemble
- transcript rebuttal
- 交叉质询
- 置信度投票系统
- 自动 tie-break

## 风险加固与架构护栏

本节把已经识别的风险，收紧成设计时和实现时都不能绕开的 guardrail。

### 1. `round_index` / `round_limit` 放置不稳，导致恢复点和预算语义漂移

为什么危险：

- 多轮拓扑如果只把轮次写进 `latest_summary`，恢复时没有单一可信事实源
- `director_worker` 和 `debate_judge` 会在 checkpoint、progress、runtime 本地计数之间出现三份真相
- 预算耗尽、最终轮判断、progress 展示都会变成推断，而不是合同

显式 guardrail：

- `round_index` 与 `round_limit` 只允许进入 `TeamTopologyCheckpoint` 和 `TeamTopologyProgressSummary`
- runtime 可以持有局部变量，但写 checkpoint 时必须以合同字段为准，不允许只存在内存里
- `round_index` 必须是 1-based
- `round_limit` 必须在 run 开始时冻结，执行中不可漂移
- `round_index` 只能在“新一轮正式开始”时推进，不能在 collecting / judging / director_deciding 内偷偷自增
- `round_index > round_limit` 必须直接判为合同错误，而不是 runtime 自行修正

guardrail 落点：

- contract:
  - `TeamTopologyCheckpoint`
  - `TeamTopologyProgressSummary`
- runtime:
  - `TeamTopologyExecutionSpine.record_checkpoint()`
  - 两个新 runtime 的轮次推进入口
- presentation:
  - round-aware compact renderer 只能读取 summary contract，不自行推断轮次
- tests:
  - checkpoint / progress invariant tests
  - invalid round transition tests

验证必须证明：

- start 后第一条多轮 checkpoint 的 `round_index == 1`
- 同一轮内部的 collecting / deciding 不会错误推进轮次
- resume 后 round 信息与中断前一致
- 任意 `round_index > round_limit` 的 payload 直接校验失败

### 2. `TeamDirectorDecision` / `TeamJudgeDecision` 被弱化成自由文本 orchestration

为什么危险：

- 一旦继续靠 `summary` / `next_action` 解析下一步，v3 会立刻退回 prompt 路由器
- runtime 会被迫做字符串解析，后续预算、停机、重试、回归测试都不可判定
- “typed topology” 名义保留了，但真正控制面已经变回 free-text

显式 guardrail：

- `dispatch_roles`、`winner_role`、`next_candidate_roles` 必须是强类型字段，不能从 `summary` 推断
- `decision` 必须是有限枚举
- 不允许通过 `next_action` 表达控制分支；`next_action` 只保留给人类读的下一步说明
- runtime 只消费 decision model，不消费自由文本控制命令
- presentation 只展示 decision summary，不回显内部控制字段为自然语言 prompt

guardrail 落点：

- contract:
  - `TeamDirectorDecision`
  - `TeamJudgeDecision`
- runtime:
  - `TeamDirectorWorkerRuntime`
  - `TeamDebateJudgeRuntime`
- tests:
  - invalid decision-shape tests
  - “summary 有指令但 typed field 缺失” 的拒收测试

验证必须证明：

- `dispatch_workers` 缺 `dispatch_roles` 时校验失败
- `select_winner` 缺 `winner_role` 时校验失败
- 仅修改 `summary` 文案不会改变 runtime 分支
- runtime 不包含“从 summary 提取下一步”的实现路径

### 3. `debate_judge` 最终轮平票被 silent auto-resolve

为什么危险：

- 这是 day one 最容易被工程实现“顺手优化掉”的风险
- 一旦最终轮 tie 被自动选择，父聊天失去真正需要参与的高风险分歧
- judge 会在没有授权的情况下替父层做价值判断，直接破坏 ask-parent 边界

显式 guardrail：

- 非最终轮 tie 只能 `advance_round`
- 最终轮 tie 只能 `needs_parent_input`
- day one 禁止任何自动 tie-break，包括：
  - 按 `confidence` 取高者
  - 按固定候选顺序取胜
  - judge 自由文本解释后自动选边
- 如果已经达到 `round_limit` 且仍无 winner，judge 只能：
  - `needs_parent_input`
  - 或显式 `failed`

guardrail 落点：

- contract:
  - `TeamJudgeDecision.decision`
- runtime:
  - `TeamDebateJudgeRuntime` 的 final-round 判定分支
- presentation:
  - 父聊天看到的是 tradeoff summary + waiting_parent，不是伪装成已完成
- tests:
  - final-round tie escalation tests
  - auto tie-break negative tests

验证必须证明：

- round 1 tie 且 `round_limit=2` 时进入下一轮
- final-round tie 时当前 checkpoint 进入 `waiting_parent`
- final-round tie 不会产出 `completed` 的 `TeamReducedTopologyResult`
- “更高 confidence 自动胜出” 的输入在 day one 不成立

### 4. `director_worker` 漂移成无界循环或隐藏再派工

为什么危险：

- `director_worker` 天然接近 planner loop，最容易被实现成“直到做好为止”
- 一旦允许隐藏 re-dispatch，TaskHub 的 bounded execution guarantee 会被绕开
- debugging、resume、预算耗尽都会变成不可解释的隐式行为

显式 guardrail：

- 每轮派工必须显式落 checkpoint，不能在一个 runtime step 内偷偷做多轮 dispatch
- `dispatch_workers` 一次只代表一轮 worker batch
- 轮次推进、repair 重试、父输入中断都必须写 checkpoint
- 强制预算：
  - `max_rounds`
  - `max_parallel_workers_per_round`
  - `max_total_worker_dispatches`
  - `max_parent_interruptions`
  - `max_repair_cycles_per_run`
- 预算耗尽时只能显式终止为：
  - `failed`
  - 或 `needs_parent_input`

guardrail 落点：

- contract:
  - round metadata
  - director decision enums
- runtime:
  - `TeamDirectorWorkerRuntime`
  - `TeamTopologyExecutionSpine.parallel_limit`
- tests:
  - budget exhaustion tests
  - hidden re-dispatch negative tests

验证必须证明：

- director 一次 decision 最多触发一轮 batch
- 超出 `max_total_worker_dispatches` 后不会继续 collect/dispatch
- repair 轮数和 parent interruption 次数都会被计入预算
- 无可行 repair path 时直接终止，不会继续空转

### 5. worker / candidate 直接 ask-parent 泄漏进 day one cut

为什么危险：

- 父聊天会从 phase-level control 退化成 agent chatter inbox
- director / judge 失去控制面意义
- resume 会落在 worker/candidate 层而不是 topology 层，破坏当前 seam

显式 guardrail：

- day one 只有 director / judge 能发起 `needs_parent_input`
- worker / candidate 缺信息时只能：
  - `needs_repair`
  - 或 `failed`
- runtime 对 worker / candidate 的 `needs_parent_input` 视为合同错误，而不是透传

guardrail 落点：

- contract:
  - `TeamStructuredResult` 在这两个 topology 下的 allowed status 约束
- runtime:
  - `TeamDirectorWorkerRuntime`
  - `TeamDebateJudgeRuntime`
- tests:
  - invalid worker-parent boundary tests
  - invalid candidate-parent boundary tests

验证必须证明：

- `director_worker` worker 返回 `needs_parent_input` 时校验失败或被 runtime 拒绝
- `debate_judge` candidate 返回 `needs_parent_input` 时校验失败或被 runtime 拒绝
- 只有 `waiting_parent` checkpoint 对应 director/judge 发起的 interruption

### 6. reducer / judge / director 控制决策重新暴露 transcript

为什么危险：

- 一旦控制角色开始依赖 transcript，progress 面和 reduced result 面都会失真
- 中断恢复会要求保留长对话上下文，直接抬高实现复杂度
- day one 的可测试性会被 prompt 噪音吞掉

显式 guardrail：

- director / judge 只消费 typed result envelope，不读 agent 间 transcript
- 父聊天只消费：
  - `TeamTopologyProgressSummary`
  - `TeamReducedTopologyResult`
  - 压缩 summary
- progress renderer 不展示 worker/candidate 原始对话
- reducer/judge/director 的控制输入必须来自已验证结构化字段：
  - `summary`
  - `evidence`
  - `confidence`
  - `artifacts`
  - `next_action`

guardrail 落点：

- contract:
  - `TeamStructuredResult`
  - `TeamReducedTopologyResult`
  - `TeamTopologyProgressSummary`
- runtime:
  - 两个 topology runtime 的 collect / decide 边界
- presentation:
  - compact progress renderer
  - ingress/status help text
- tests:
  - transcript-free rendering tests
  - reducer input-shape tests

验证必须证明：

- progress 输出只包含阶段信息和压缩摘要
- 完成态输出仍统一落在 `TeamReducedTopologyResult`
- director/judge runtime 分支不依赖 transcript 文本解析

## 对现有 seam 的精确增量

### 需要新增的 runtime class

在 `controlmesh/team/execution.py` 中新增：

- `TeamDirectorWorkerRuntime`
- `TeamDebateJudgeRuntime`

不新增新的 execution root。

### 需要扩展的 models / contracts

在 `controlmesh/team/contracts.py` 中扩展：

- `TEAM_TOPOLOGIES`
- `TEAM_TOPOLOGY_SUBSTAGES`

在 `controlmesh/team/models.py` 中扩展：

- `TeamTopologyCheckpoint.round_index`
- `TeamTopologyCheckpoint.round_limit`
- `TeamTopologyProgressSummary.round_index`
- `TeamTopologyProgressSummary.round_limit`
- `TeamDirectorDecision`
- `TeamJudgeDecision`

### 可以继续复用的终局输出边界

两种新拓扑的 terminal output 仍然统一落成：

- `TeamReducedTopologyResult`

这样保持：

- 父聊天终局面不分裂
- task selector / transport 渲染不需要再引入第二套终局协议

## 依赖图与并行边界

### 总原则

先冻结唯一共享 seam，再并行推进各分支，最后做一次串行收口。

原因：

- `contracts.py` / `models.py` / 轮次语义 是共享基础，不先冻结就会让各分支各写一套真相
- `execution.py` 是共享 runtime seam，允许并行开发，但不允许并行定义不同合同
- ingress / presentation 可以在合同冻结后提前分支，不必等两个 runtime 都完成

### Stage A: 串行冻结阶段

唯一必须先串行完成的阶段：

- 冻结 topology ids / substages
- 冻结 `round_index` / `round_limit` 放置与 invariant
- 冻结 `TeamDirectorDecision` / `TeamJudgeDecision`
- 冻结 day one ask-parent 边界
- 冻结 transcript-free control boundary

Stage A 的退出条件：

- shared seam 合同不再变化
- 负例测试矩阵已经定义
- 后续并行分支不需要再争论控制协议

### Stage B: 并行实施分支

只要 Stage A 冻结，以下分支可以并行：

#### Branch 1: `director_worker` runtime

负责：

- director planning / dispatch / collect / decide loop
- director-only ask-parent
- bounded repair / stop path

依赖：

- 只依赖 Stage A

共享冲突：

- 会改 `execution.py`
- 必须在 branch 内只实现 `director_worker`，不顺手改 `debate_judge` 语义

#### Branch 2: `debate_judge` runtime

负责：

- candidate round handling
- judge decision intake
- final-round tie escalation
- bounded repair / stop path

依赖：

- 只依赖 Stage A

共享冲突：

- 同样会改 `execution.py`
- 必须遵守已经冻结的 judge decision 合同

#### Branch 3: round-aware presentation / ingress

负责：

- round-aware `progress_summary` 展示
- compact renderer 扩展
- `/tasks topology ...` 帮助文本与显式拓扑入口扩展

依赖：

- 只依赖 Stage A

不依赖：

- 不需要等待两个 runtime 完成后才开始

#### Branch 4: 负例与回归矩阵固化

负责：

- contract negative matrix
- parent-boundary negative matrix
- transcript-leak negative matrix
- four-topology regression 清单

依赖：

- 只依赖 Stage A

说明：

- 该分支可以先搭测试矩阵与 fixture 计划
- 最终执行仍然要等 Branch 1-3 汇合

### Stage C: 串行收口阶段

以下必须回到串行：

- merge `execution.py` 上的两个 runtime 分支
- 统一 round-aware presentation 与实际 runtime 行为
- 执行四拓扑 regression / interruption / resume matrix
- 处理任何 shared seam 漂移

Stage C 结束前不应宣布完成。

## v3 的明确非目标

v3 明确不做：

- 通用 topology DSL
- planner graph / node editor
- worker transcript replay UI
- generic auto-reducer framework
- topology auto-selection
- routing by natural language

## 推荐执行顺序

v3 对应的推荐实施顺序是：

1. 先做 Stage A：shared contract freeze
2. 再开 Stage B 并行分支：
   - `director_worker` runtime
   - `debate_judge` runtime
   - round-aware presentation / ingress
   - negative/regression matrix
3. 最后做 Stage C：串行收口与回归

原因：

- 两个拓扑都依赖 multi-round checkpoint 语义
- 并行应当发生在共享 seam 冻结之后，而不是之前
- `director_worker` 和 `debate_judge` 可以并行开发，但不能并行发明协议
- 最终仍需要一次串行合流来消除 `execution.py` 和 progress surface 的共享冲突
