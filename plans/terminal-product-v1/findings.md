# Findings

## 用户纠偏与截图

用户要求 Codex 式成熟终端体验，并明确当前界面不能被当作完成的产品。
截图显示简单 `cm>` 行提示、未分层的聊天文本、`/` 输入，以及顶部
“API failed to start” 文本。截图不能证明错误根因或精确安装版本。
这属于交互质量与工作流要求，不应解读为仅更换颜色或增加 banner。

## 当前代码证据（2026-09-06）

- 基线 `main@1d62506`。现有未提交 `README.md`、`pyproject.toml` 为上一请求的
  cm alias 改动；本次只新增计划和更新项目记忆。
- `terminal/enhanced_shell.py` 使用 `asyncio.to_thread(input, ...)`，等待整行输入，
  没有输入菜单/多行编辑组件；流式回调直接 `Console.print(delta, end="")`。
- `terminal/command_router.py` 已有 commands 和参数处理；裸 `/` 不属于命令集合，
  shell 会进入一般消息路径。应复用路由并为菜单建立同一命令描述来源。
- `terminal/rendering.py` 直接输出 result.text，不存在对话/工具分层视图。
- `terminal/runtime.py` 的 `handle_user_message` 已接受 on_tool_activity，shell
  目前只传文本回调；模型概览/切换、inbox 和 memory 能力可以复用。
- `terminal/app.py` 先启动 runtime 再进入 shell；需检查启动耗时、健康信息与可选
  服务失败的展示。optional background runtime 已有降级逻辑，不应再造平行 runtime。
- 现有 tests/terminal 覆盖入口、路由、runtime、native 模式、inbox、memory 等；
  这些证明功能行为，尚不能证明菜单、编辑焦点、屏幕布局与 resize 的产品验收。
- 上一轮本机全局 cm 指向已安装 0.41.5；源码 uv run cm 为 0.42.0a1。
  截图文字与当前源码首屏不同，实现前应记录实际启动版本，不能把截图直接等同 HEAD。

## 边界与未决项

- Codex 在此作为用户的体验参照；本计划未核实其当前实现或逐项功能，不声称完全 parity。
- Python TUI 是优先评估方向；依赖选型需原型验证，尚未决定引入 prompt_toolkit。
- 截图 API 失败的端口、组件与根因未复现；先辨别可选组件或核心故障，不预判冲突。
- 启动目录与 runtime workspace 的关系需核实；不能通过 UI 标签冒充已切换 workspace。
- session/task native 交接能力、取消确认与后台持久性需要从相关代码继续审计。
- 工具输出的 ANSI/Rich 转义、中文字符宽度、菜单焦点和控制键需独立验收。

## 本次检查

只读审计终端入口、shell、router、rendering、runtime、测试目录及项目所有权索引。
本次是计划交付，不运行 provider，不复用旧测试数量声称新的 UX 已通过。
