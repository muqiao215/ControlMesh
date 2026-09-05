# Progress

## Current

2026-09-06：绑定已有机器人 scope 已完成并通过全仓验证。

## Done

- 增加 `cm feishu bind` 与 `cm feishu native bind`。
- 支持隐藏输入或指定密钥环境变量；不接受命令行密钥值。
- 写入前用 tenant token 与 bot info 验证，并显示机器人名称和 `open_id`。
- 保留群策略、白名单、进度模式和其他 transports；不同 App ID 需 `--replace`。
- 对验证失败、并发配置变化、待完成注册和无机器人身份全部 fail closed。
- focused CLI/terminal/branding：136 passed。
- Feishu CLI/messenger/integration：263 passed。
- `uv run ruff check controlmesh tests`：通过。
- 完整 Python：5592 passed in 176.08s。

## Remaining

无代码范围内剩余项。

## Issues

尚未使用用户真实凭据和真实事件订阅做线上 smoke test；自动测试覆盖官方接口契约与
本地持久化行为，不伪装成上游环境验收。

## Next

由操作者运行 `cm feishu bind`，核对打印的机器人身份，再完成应用发布、事件订阅与
`cm feishu native doctor`。
