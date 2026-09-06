# Findings

## Source and baseline

- 来源：[ControlMesh 周报自动任务](chatgpt-conversation://6a74e11c-3330-83ea-abf8-408108975afc)。
  已读完两页到 2026-08-07 的历史及 2026-09-06 最新设计；报告作为待核验数据。
- 本地 main `ac830ae`，开始时工作区干净。fetch 后 origin/main 为 `a8f88a4`，
  多出 Telegram polling/backoff/spool、OpenCode preflight、cron subprocess 清理四个提交。
  这些提交没有新增 grants、跨节点诊断或本计划的进程重启矩阵。
- 测试执行基线是本地 `ac830ae`，不是最新远端；本次不合并其他工作、不修改自动任务。
- 外部项目的设计比较仅沿用周报来源，未在本次重新审计其 commit；本计划的缺口判断依据 CM。

## Reconciled recommendations

| 周报建议 | 当前判定 | 当前依据 / 下一步 |
|---|---|---|
| lifecycle parity / 只读 Alpha | 已有实现与既有 gate | PROJECT、tasks lifecycle fixture；不重立项目 |
| writeback / promotion 故障矩阵 | 已落地 | tests/golden/runners/result_writeback_promotion.py；本轮对应测试通过 |
| 来源沙箱拒绝宿主机 fallback | 已落地 | execution_policy.py、provenance golden；本轮对应测试通过 |
| 工具、网络、写入、确认完整风险策略 | 部分完成 | tool_policy=request_bound、network_policy=container_default、configured_container_mounts 是当前策略描述，不能证明最小授权；计划 A |
| 飞书长连接取消与代际隔离 | 已落地 | test_long_connection.py 本轮通过；无需重做 09-05 设计 |
| ToolGrantContext 跨 provider / recovery | 尚未落地 | 当前 ExecutionContext 和 tasks 序列化存在；生产代码未找到 grant/fingerprint 契约；计划 A |
| 跨服务器 message diagnose | 尚未落地 | orchestrator/commands.py 的 cmd_diagnose 忽略输入文本，展示本地健康与日志；计划 B |
| kill/restart 持久化与投递故障矩阵 | 尚无该端到端矩阵证据 | 单进程 golden 与 cron process-group 清理不等同于 runtime kill/restart；计划 C |
| fleet manifest / 漂移 | 部分基础已有 | cli_commands/status.py 已有 provider fleet doctor；扩展而非新造 inventory；计划 D |
| 飞书多机器人 | 代码已落地，双节点验收未完成 | plans/feishu-multi-bot-coordination/progress.md Remaining 仍要求真实 open IDs 与双节点 checklist；计划 D |
| 三条闭环生产证据 | 仍缺统一真机记录 | 已有局部执行/聚合/promotion，不宣称只有规格；计划 E |
| 窄 mutation / 权限 UI | Deferred | docs/typescript-migration/MUTATION_API_REVIEW.md 明确无公开 mutation 批准 |
| 飞书业务 CLI / MCP | 尚缺本建议的受限接入验收 | 已有 bind/native transport 不等于文档、日历等工具权限层；A 后单独选最小能力 |
| auth 切换保留 endpoint | 待定向复核 | 外部 bug 不能证明 CM 同样有问题；不得直接生成镜像测试 |
| 升级前 staging/canary | Deferred | 当前不扩展为自更新 runtime 项目 |
| webhook 测试截断 | 当前本地未复现 | tests/webhook/test_auth.py 可执行且本轮通过；旧临时工作树诊断不继承为当前缺陷 |
| 旧 Promotion Candidates scope / daily-note snippet | 历史细项仍需精确映射 | 当前 result identity golden 已覆盖错误身份晋级；不能拿它替代另一套记忆候选归因的审计 |

## Corrections to the latest design

- fingerprint 是一致性摘要，不是授权签名；必须依据可信签发与持久化所有权判断有效性。
- 恢复会产生新 episode；应验证旧 lineage 并重新绑定不扩权的 grant，不能既禁止跨 episode
  又要求直接沿用旧 episode 对象。
- 添加任务 JSON 字段仍然属于持久化契约变化，即使没有数据库 schema migration。
- 回滚直接删除 gate 会使旧执行器忽略受限任务的权限；必须验证兼容或隔离这些任务。
- provider 工具名、MCP 工具和 CLI flag 不天然等价，必须逐 adapter 证明 enforcement。
- 对外投递的一次性语义依赖远端幂等/对账；仅有本地 canonical result 唯一不足以证明。

## Local verification

`uv run pytest -q tests/golden/test_execution_provenance_sandbox.py tests/golden/test_result_writeback_promotion_golden.py tests/messenger/feishu/test_long_connection.py tests/webhook/test_auth.py`

结果：56 passed in 1.54s。本轮为文档任务，没有重跑完整 Python，也未声称远端 CI 或真机通过。
