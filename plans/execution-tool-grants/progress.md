# Progress

## Current

2026-09-06：Unit A 前置复核完成——provider 强制力矩阵、持久化/恢复通道、契约设计均已记录于
`findings.md`，待用户批准后进入实现（独立代码单元）。

## Done

- 读取 `execution_policy.py`、`bus/envelope.py`、`tasks/models.py`、四个 provider
  adapter、tasks 恢复链路；确认现有 tool_policy 为描述性字符串、flag 由静态全局配置驱动。
- 用本机安装的 claude 2.1.263 / codex 0.153.2 / gemini 0.43.0 / opencode 1.18.29 的
  `--help` 作为权威证据，产出逐 provider 强制力矩阵。
- 发现并记录两个反直觉事实：gemini `--allowed-tools` 是免确认清单而非硬门禁（已弃用）；
  codex 无按工具名 allowlist，强制力在沙箱/审批粒度。
- 确认 ExecutionContext 持久化与恢复链路（submit 绑定、task JSON 往返、recovery 还原）
  可复用为 grant 载体；契约设计为独立 additive 字段。
- 撰写最小持久化与恢复契约（签发、enforcement 点、恢复重绑、回滚、验证路径六条）。

## Remaining

实现按 findings.md §5 契约执行：grant 对象与签发 → 各 adapter enforcement 映射 →
拒绝路径 → 恢复重绑 → golden/drift gate。claw/openai_agents 属第二波同程序审计。

## Issues

无。

## Next

等用户批准契约后，按独立代码单元开始实现；实现前先复核 opencode run 面是否接受
per-invocation 配置覆盖与 claw_provider 的 allowedTools 是否为硬门禁。
