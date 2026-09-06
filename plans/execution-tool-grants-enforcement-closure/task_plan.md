# Execution Tool Grants Enforcement Closure — Unit A.1

## Goal

补齐 Unit A 的实际执行约束：真实入口签发、所有启动路径传播、网络与确认策略执行、
恢复与回复身份校验。只有限制被实际执行，或在无法执行时于副作用前明确拒绝，才算完成。

## Context

2026-09-07，本地基线 `3417ae0`。Unit A 已提供快照、adapter 映射、任务持久化与 golden。
代码审计发现 Claude 的 no_network 目前仅映射 WebFetch/WebSearch 拒绝；签发函数未有
生产调用点；仅 confirmation_policy 的快照被视为 floor。相关证据见 [findings.md](findings.md)。

这是 [周报实施队列](../weekly-report-followthrough/task_plan.md) A 的补充工作，先于 B
跨节点诊断完成安全语义收口。Terminal Product v1 仍为产品主线。

## Requirements

- R1：可信 Python 入口依据明确的本地配置和来源策略签发 grant；用户消息、provider 输出、
  webhook body 不得自行声明授权。请求限制只能收窄已有权限。
- R2：一份快照沿任务提交、持久化、后台执行、恢复、provider 构造和 one-shot 路径传播。
  明确记录每条路径的 owner 和执行门禁，任何未支持的受限路径在启动前拒绝。
- R3：no_network 表示执行工作负载的出网限制，不能降格为禁止两个内置工具。
  模型服务的控制连接与工具/子进程数据连接必须有明确边界；若无法隔离，拒绝任务。
- R4：controller_required 必须对应真实 controller 批准证据与校验点，不能仅存字段。
  尚无可复用批准机制的路径返回稳定拒绝原因，不新增公开审批 API。
- R5：回复 transport/chat/topic/thread 必须与任务可信投递归属一致；摘要和 provider 输出
  不能改写目标。缺失 legacy 字段使用既有可信归属，不从自由文本恢复。
- R6：恢复先验证 task、owner、episode/lineage，再携带权限进入当前执行。复用现有统一身份；
  不把快照反序列化成功或 fingerprint 相等当成授权来源可信。
- R7：缺失旧字段保持已确认的 legacy 行为与来源沙箱底线；新受限任务不能通过删除字段
  悄然转成 legacy。需要明确可信存储边界及受限任务的可识别状态。
- R8：Python 保持 runtime、持久化和 promotion 所有权；公共 OpenAPI/SDK/Web 保持只读。

## Non-goals

- 不迁移 TypeScript runtime、不新增 create/tell/resume/cancel 或通用授权 API。
- 不引入完整 RBAC、OAuth 存储、远程 Web、全新 provider 或审批界面。
- 不同时扩展所有 provider 的限制能力；未证明的 surface 继续 fail closed。
- 不把本阶段扩大为 B 的跨服务器诊断或 C 的全进程故障矩阵。
- 不追求防御拥有宿主机管理权限的攻击者；持久化真实性必须明确依赖的信任边界。

## Implementation Map

下列是审计入口；以真实调用关系决定最终文件，不机械修改全部文件。

| 层 | 现有入口 | 需要落实 |
|---|---|---|
| 授权契约 | controlmesh/execution_grants.py、execution_policy.py | 区分描述与约束，稳定 reason code，逐字段支持判定 |
| 可信签发 | bus/envelope.py、orchestrator/core.py、实际 TaskSubmit 构造点 | 策略来源、收窄合并、可信身份与原回复目标 |
| 任务所有权 | tasks/models.py、registry.py、hub.py | 新旧记录识别、恢复 lineage 与投递一致性 |
| 常规执行 | cli/types.py、service.py、各 provider adapter | 最终有效配置验证，禁止 overrides/bypass 扩权 |
| 自动执行 | infra/task_runner.py、infra/base_task_observer.py、cron/execution.py 与 webhook 调用方 | one-shot grant 传播或明确拒绝 |
| 沙箱边界 | 实际 Docker/process wrapper 与 provider sandbox 参数 | 网络约束证据，控制连接与工具网络的边界 |
| 验证 | tests/test_execution_tool_grants.py、tests/golden/runners/tool_grant_mapping.py | 复用现有矩阵，补行为级证据和 drift gate |

## Plan

### Phase 0 — 基线与最终契约

Status: pending

- [ ] 检查工作区、分支、远端、近期提交与现有 CI；保护未提交文件。
- [ ] 读取本目录及 Unit A 发现，画出正常/后台/恢复/cron/webhook 启动调用清单。
- [ ] 逐项确认 network、confirmation、reply、task identity 是否由已有 owner 强制执行。
- [ ] 用已安装 CLI 行为与必要的官方资料确认 provider 能力，不只看参数名字。
- [ ] 决定最小本地策略来源和兼容契约；记录 unsupported 路径与 reason codes。

完成条件：每项限制都有可信来源、校验点、拒绝点和可运行验收；不能表达的策略明确拒绝。

### Phase 1 — 修复限制语义

Status: pending

- [ ] no_network 无可靠隔离证明时拒绝；不能以 WebFetch/WebSearch deny 视为成功。
- [ ] confirmation 限制参与执行决策；区分 provider 默认确认与 controller 批准。
- [ ] 合并静态配置和 grant 只收窄；校验最后生效的 CLI 参数与覆盖顺序。
- [ ] 若拆分“禁止 Web 工具”和“禁止网络”词汇，提供版本兼容且不放宽原 no_network。

完成条件：所有被接受的限制有执行依据，unsupported 状态不会返回 accepted/floor。

### Phase 2 — 生产签发与全启动路径接线

Status: pending

- [ ] 可信入口调用签发器，从既有来源策略和本地配置生成限制，避免新增任意授权输入。
- [ ] TaskSubmit → TaskEntry → AgentRequest → CLIConfig 传播；确认 clone/retry 分支。
- [ ] 接通 cron/webhook/one-shot；不支持时进程创建前拒绝并保留稳定诊断。
- [ ] 取消、失败或验证未完成时不触发 provider/tool 副作用。

完成条件：至少一个真实支持的限制从真实入口到实际执行通过；所有其他受限入口有拒绝证据。

### Phase 3 — 恢复、确认与投递归属

Status: pending

- [ ] 复用 runtime owner 的 task/episode 校验，证明跨任务快照替换和旧 episode 重放拒绝。
- [ ] 正常恢复允许当前 owner 延续相同或更窄策略；换 provider 必须重新判断可执行性。
- [ ] controller 批准与当前任务、修订/episode、限制和动作绑定，过期或重放拒绝。
- [ ] 投递前核对实际 transport/chat/topic/thread；不一致拒绝，不静默改发到新目标。
- [ ] 旧记录兼容、新受限记录降级保护、损坏字段拒绝均有明确可执行契约。

完成条件：测试真实 owner/投递路径，不能仅以 JSON round-trip 替代身份或审批验证。

### Phase 4 — Golden、行为测试与状态同步

Status: pending

- [ ] 复用已有 14 案例，修正语义不实的期望，只补缺失案例。
- [ ] 生产 Python 生成规范化 evidence；检查缺失、额外、字段漂移，无正文/凭据/绝对路径。
- [ ] 执行下述验收矩阵与 gate；环境缺失记录为未验证，不作为成功。
- [ ] 更新架构不变量、必要决策、Unit A 与总计划，区分 v1 落地和 A.1 完成。

## Acceptance Matrix

| ID | 场景 | 必须观察到的结果 |
|---|---|---|
| AC01 | 可信入口请求更窄权限 | 签发、持久化与执行一致；消息自带授权字段无效 |
| AC02 | Claude no_network + Bash/其他网络能力 | 无隔离时启动前拒绝；有隔离时工作负载无法访问受控外部测试端点 |
| AC03 | Codex 网络策略与配置覆盖 | 最终 sandbox 生效；full-access/bypass/覆盖冲突拒绝 |
| AC04 | 仅 controller_required | 无匹配批准不执行；不能走 floor 视为已授权 |
| AC05 | 正常批准、旧批准或批准后修订改变 | 仅当前有效批准执行；重放/陈旧批准拒绝 |
| AC06 | 正常后台与恢复 | 权限不扩大、目标不变，当前 owner 验证通过 |
| AC07 | 不同 task/旧 episode/不同 owner | 在执行或投递前拒绝；仅反序列化成功不足以通过 |
| AC08 | cron/webhook/one-shot | 限制到达真实启动边界或启动前拒绝，无宿主机 fallback |
| AC09 | provider 切换或不支持 surface | 重评估；不能表达的限制拒绝 |
| AC10 | 回复目标任一字段不一致 | 原目标和错误目标均无意外投递，留下 reason code |
| AC11 | legacy、损坏与新受限记录丢失字段 | legacy 保持来源底线；损坏/降级尝试明确拒绝或隔离 |
| AC12 | 静态 deny 与请求限制冲突 | deny 不丢失，最终权限为更严格的组合 |
| AC13 | 序列化、日志与 golden | 不记录秘密/正文/绝对路径；漂移报错可定位 |
| AC14 | 回滚到忽略 grant 的执行器 | 受限任务不会被该执行器接管运行 |

网络行为验证使用可控测试端点和子进程，不访问真实业务数据。若实现选择完全拒绝某 surface，
为该 surface 验证真实启动边界拒绝即可；不能据此声称它支持隔离执行。

## Validation Gates

1. focused：现有 tool grants、tasks、CLI、cron/webhook、恢复和投递相关测试；命令及结果记入 progress。
2. `uv run ruff check` 修改范围；可修复项使用 `--fix` 后审查 diff。
3. 完整 Python：记录实际命令、通过/失败/跳过数。若 systemd 环境失败，记录原始复现与
   清理环境后的对照，不能笼统沿用“既有失败”的标签。
4. `pnpm test:golden`，检查工具授权与原 provenance/writeback 门禁。
5. 若修改 Schema/TS/产品构建：协议生成漂移、TypeScript typecheck、SDK/Web build；
   核实公开 API 仍只有批准的读操作。
6. 检查 diff、凭据、绝对路径、缓存和无关修改；提交后以对应 SHA 的 CI 作为远端结果。

## Migration and Rollback

- 持久化变化优先 additive；新字段放 dataclass 字段末尾，保留位置构造兼容性。
- 明确旧记录缺失值与新受限任务缺失值的辨别机制；无法辨别时不得假称具有抗降级能力。
- schema/version 未知或约束损坏 fail closed；禁止恢复时自动丢弃不认识的限制。
- 回滚前停止受限任务接管并隔离待执行任务；验证兼容读取不等于允许旧执行器继续运行。
- 不删除已有 grant/审计证据；恢复执行需重新确认目标版本可以强制这些限制。

## Success

AC01–AC14 每项都有实际通过证据或明确支持范围内的拒绝证据；任何环境阻塞项仍记未完成。
生产链、测试、golden、文档一致，才把 A.1 标记 complete 并将下一安全单元转到 B。

## Status

Plan ready。本次仅完成计划文件；Phase 0–4 未开始实施。

## Next Step

执行 Phase 0：核对真实启动调用链，确定 no_network 与 controller_required 的最小可强制契约。
