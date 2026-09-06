# Findings

## Baseline

- 2026-09-07，本地最近提交 `3417ae0`（Unit A）。
- 已有未提交修改：`plans/feishu-bind-existing/progress.md`、`uv.lock`；本次保持原样。
- 2026-09-07 已 fetch 确认本地与 origin/main 同为 3417ae0；CI 34041126119 的 headSha
  精确匹配且 success。用户报告的本地 848 / 5646 测试结果本轮未重跑。

## Confirmed code observations

- `execution_grants.py:_map_claude` 将 no_network 映射为 WebFetch/WebSearch deny；
  该映射本身没有约束 Bash、MCP 或其他子进程网络，所以不能证明整体无网络。
- 生产 `controlmesh/` 搜索 `issue_tool_grant(` 只有定义，没有可信入口调用点。
- `ToolGrantSnapshot.restrictive` 包含工具、网络和 writable_roots，不包含 confirmation_policy。
  `map_tool_grant` 对非 restrictive grant 直接 floor 返回。
- registry 保存 submit.tool_grant，hub 构造 AgentRequest 时带 entry.tool_grant，service
  传入 CLIConfig；这是传播基础，不能单独证明执行身份、批准与回复目标被验证。
- Unit A 测试已有命令映射、持久化往返和非法字段拒绝；后续需调用真实 owner/执行/投递边界。

## Design cautions

- no_network 的控制连接例外必须明确。若模型和工具共享不可隔离的连接环境，应拒绝该请求。
- 快照冻结、版本解析和摘要都不验证签发者身份；授权信任应来自现有 runtime ownership。
- controller_required 不能悄然解释为 provider 自行确认，也不能仅通过字段存在表示完成批准。
- 修复不应迫使所有 legacy 任务携带新 grant；但新受限任务缺失 grant 的降级必须可识别。
- 不能用矩阵里的固定 flags 输出代替实际网络/确认/跨任务拒绝行为证据。

## Scope decision

优先补 A.1 的安全语义和生产接线；provider 新 surface 能力和 B 跨节点诊断继续排队。
Terminal Product v1 保持原产品优先级。
