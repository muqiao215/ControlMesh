# Progress

## Current

2026-09-07：Unit A v1 已提交推送至 `3417ae0`，本地 main 与 origin/main 一致。
签发函数、adapter 映射/拒绝、任务持久化、恢复传递和 golden 已落地；完整执行约束由
[A.1](../execution-tool-grants-enforcement-closure/task_plan.md) 继续收口。

## Verification

- 本轮通过 GitHub 查询确认 [CI 34041126119](https://github.com/muqiao215/ControlMesh/actions/runs/34041126119)
  headSha 为 `3417ae0df5d76afb37cb5b19ea2ff6a800126b8e`，结论 success；Python 3.11/3.12、
  Ruff、Mypy、构建、Protocol/SDK/Web、安装 smoke 均成功。
- 用户提供的实现期记录：专项 848 passed；全量 5646 passed、1 项 systemd 环境失败。
  本次未重新执行该本地全量命令，失败归因仍以原实现记录为准，不计作本轮复现。

## Done

- `controlmesh/execution_grants.py`：`ToolGrantSnapshot`（严格版本解析、token/root 校验、
  无正文无凭据字段）、`issue_tool_grant`（可信签发入口）、`map_tool_grant`（逐 provider
  纯映射）、`ToolGrantDenied`（启动前类型化拒绝，复用 ExecutionPolicyDenied 模式）。
- 映射语义：claude=deny 规则并集 + no_network 映射 WebFetch/WebSearch 拒绝 +
  allowlist/bypass 拒绝；codex=no_network 在 workspace-write 下注入
  `sandbox_workspace_write.network_access=false`，bypass/full-access 冲突拒绝，工具粒度
  不支持即拒绝；gemini/opencode/claw/openai_agents 限制性 grant 一律拒绝（面未验证）；
  floor-only 与 None grant 保持既有行为，绝不放宽静态配置。
- 接线：`AgentRequest.tool_grant`、`CLIConfig.tool_grant`、`service._make_cli` 传递；
  `TaskSubmit`/`TaskEntry.tool_grant` 持久化往返（registry 复制）；hub 恢复路径
  `AgentRequest(tool_grant=entry.tool_grant)` 原样重绑。
- 六个 adapter 在命令构造点接入映射（进程创建前拒绝）；既有静态 flag 行为在无 grant
  或 floor grant 下逐字节保留。
- 验收测试 `tests/test_execution_tool_grants.py` 覆盖 provider 映射、持久化往返、非法字段
  拒绝、越权配置拒绝、无秘密字段集与旧记录兼容。严格解析和 verbatim 往返不等同于
  跨任务/episode 重放拒绝；后者需 A.1 的真实 owner 路径证据。
- golden：`tests/golden/runners/tool_grant_mapping.py` 14 案例 + fixture + JSON Schema +
  漂移测试 + `scripts/generate_tool_grant_golden.py --check` + `check:tool-grant-golden`
  接入 `pnpm test:golden` 链。
- 修复三个实现缺陷：`_bounded_token` 空串误拒、floor/None 判定反转导致 opencode/claw/
  openai_agents 既有路径误拒、claude deny 断言切片。

## Remaining

- A.1：可信入口调用签发器、完整网络限制、controller 确认、回复归属和身份恢复证明。
- opencode 配置覆盖、gemini policy-engine 配置、claw/openai_agents 硬门禁证明、
  one-shot cron/webhook grant 接线（按 findings §5 后续波次）。
- 请求侧（如何为任务指定限制）属下一波产品化决策。

## Issues

- 首版 floor 判定反转使 52 个既有测试失败（None grant 误入 handler）；已修复并全绿。

## Next

进入 A.1 Phase 0；B 跨节点诊断排在 A.1 收口之后。终端体验保持产品主线。
