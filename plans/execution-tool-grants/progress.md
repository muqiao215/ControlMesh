# Progress

## Current

2026-09-06：Unit A v1 实现完成——签发、六 adapter 映射/拒绝、任务持久化、恢复重绑、
golden/drift gate 全部落地；全量验证进行中，通过后提交推送。

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
- 验收测试 `tests/test_execution_tool_grants.py` 26 项覆盖七组：跨 provider 映射、恢复
  往返、篡改 fail-closed、跨任务重放（严格解析+verbatim 重绑）、越权（allowlist/bypass/
  full-access 拒绝 + 不放宽静态配置）、无秘密字段集、旧记录兼容。
- golden：`tests/golden/runners/tool_grant_mapping.py` 14 案例 + fixture + JSON Schema +
  漂移测试 + `scripts/generate_tool_grant_golden.py --check` + `check:tool-grant-golden`
  接入 `pnpm test:golden` 链。
- 修复三个实现缺陷：`_bounded_token` 空串误拒、floor/None 判定反转导致 opencode/claw/
  openai_agents 既有路径误拒、claude deny 断言切片。

## Remaining

- opencode 配置覆盖、gemini policy-engine 配置、claw/openai_agents 硬门禁证明、
  one-shot cron/webhook grant 接线（按 findings §5 后续波次）。
- 请求侧（如何为任务指定限制）属下一波产品化决策。

## Issues

- 首版 floor 判定反转使 52 个既有测试失败（None grant 误入 handler）；已修复并全绿。

## Next

全量套件确认后提交推送并盯 CI。
