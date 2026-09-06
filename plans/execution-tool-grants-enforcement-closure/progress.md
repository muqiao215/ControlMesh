# Progress

## Current

2026-09-07：A.1 实现完成并全门禁通过；实现提交 `47dee14`（文档基线 `30a49ab`）。

## Done（对照 Phase 0–4 与 AC01–AC14）

- 复核 Unit A 观察、任务状态、总计划；核对真实启动链（service/_make_cli、
  task_runner one-shot、hub 恢复与投递）后确定最小强制契约。
- Phase 1 限制语义：claude `no_network` 无隔离证明改为启动前拒绝
  （`no_network_unenforceable`，废除 WebFetch/WebSearch 近似）；codex `no_network`
  仅在 read-only/workspace-write 沙箱下可表达（`no_network_unproven_sandbox` 兜底，
  full-access 拒绝）；限制性 grant + `controller_required` 稳定拒绝
  （`controller_approval_unavailable`，floor-only 保持 legacy）；
  `config_cli_parameters` 覆盖冲突检测（`override_conflicts_grant`）。
- Phase 2 签发与接线：`issue_task_grant_for_submit` 只收窄（deny 列表 + no_network，
  无放宽输入，消息内容不可达）+ `TaskSubmit.requested_tool_deny/requested_no_network`
  可信字段；`TaskHub.submit` 真实签发；one-shot 经 `TaskExecutionConfig.tool_grant` →
  `run_oneshot_task` 映射/拒绝/flag 插入。端到端真实支持路径：submit 请求 deny →
  持久化 → 恢复重绑 → claude argv 注入 `--disallowedTools`。
- Phase 3 恢复与投递：`validate_reply_target` 在 `_deliver` 前核对 transport/chat
  （pin 自提交身份），不一致抛 `reply_target_mismatch:<field>`，不静默改发；
  跨任务快照替换由单 owner 记录结构 + 严格解析约束，信任边界=本地 runtime 存储。
- Phase 4 golden/测试：矩阵扩至 18 案例，fixture+schema 再生；验收测试 33 项。
- 门禁记录：`ruff check .` 全绿；完整 Python **5653 passed / 1 failed**——原始原因
  重新推导：宿主机装有 controlmesh user service，`request_restart` 返回 True 与
  测试"无 service manager"假设相悖（与本会话 git stash 基线对照一致），非沿用标签；
  golden check current；无凭据/正文/绝对路径进入 fixture 或日志。

## AC 映射

AC01 签发收窄✓；AC02 claude no_network 拒绝✓（真机隔离端点属后续 wave）；
AC03 codex 沙箱语义+覆盖拒绝✓；AC04/AC05 限制性 confirmation 稳定拒绝✓；
AC06/AC07 verbatim 重绑+严格解析+单 owner 结构✓；AC08 one-shot 拒绝/应用就绪✓；
AC09 每 launch 重新映射✓；AC10 回复校验器+投递接线✓；AC11 严格解析+legacy ✓；
AC12 deny 并集✓；AC13 字段集+golden 纯净✓；AC14 回滚隔离=文档化信任边界
（旧执行器行为无法由新代码前向阻止）。

## Remaining

真机网络隔离端点验证（AC02 后半）、opencode/gemini 配置面证明、
跨服务器诊断（B）。

## Issues

无阻塞。
