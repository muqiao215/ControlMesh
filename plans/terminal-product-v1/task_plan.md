# Terminal Product v1

## Goal

把 `cm` 做成可日常使用的终端 Agent 工作台：启动后能看懂当前项目、模型和会话，
无需记命令即可开始工作，执行过程可见、可中断、可恢复。以用户要求的 Codex 式
终端体验作为质量目标；功能测试通过与交互体验达标分别验收。

## Context

2026-09-06 用户明确否定当前截图中的粗糙终端体验，要求先按 SpecMesh 写计划。
最初交付是计划与项目记忆；交互界面的下列实现阶段尚未完成。
基线 `main@1d62506`。已有 `README.md`、`pyproject.toml` 的 cm 入口改动需保留。
实际代码证据、截图与版本差异见 [findings.md](findings.md)。

2026-09-13 范围更新：用户已授权完整 TypeScript 运行时迁移，统一归
[runtime-convergence](../runtime-convergence/task_plan.md)。当前先接通该 TS runtime 的
独立后台服务和可重连命令入口，再承接本计划的界面要求。下面保留完整 UX 验收，
不把新命令入口当成交互终端完成，也不再按旧候选方向另建 Python 交互实现。

## Requirements

- `cm` 与 `controlmesh` 进入同一产品；安装版、源码版能辨认版本与来源。
- 首屏简洁：项目/目录、provider/model、会话、执行权限/隔离状态、帮助提示。
  不以大段 banner 或启动日志挤占对话；状态必须来自真实 runtime。
- 输入区支持中文编辑、多行、粘贴、历史、草稿保留；流式输出和后台通知不抢焦点。
- 输入 `/` 即出现可筛选命令菜单，显示名称、说明、参数/快捷键；上下键选择、
  Tab 补全、Enter 选择、Esc 关闭。需要参数的命令先填入草稿，不直接执行。
- 空闲时 Enter 提交，Alt+Enter 换行；支持 Shift+Enter 的终端可提供同等绑定，
  不支持时明确提示 Alt+Enter。多行粘贴不得自动提交。
- 对话区区分用户、助手、工具、系统通知；正确显示 Markdown、代码和差异。
  长工具输出默认收起，可展开；禁止把 provider 文本当 Rich markup/终端控制码执行。
- 显示准备、执行、工具运行、等待输入、完成、失败、中断；只展示已有事件能证明的
  状态，不伪造思考内容、进度百分比、费用或 token 用量。
- 执行中 Ctrl+C 中断当前回合并等待确认，不退出工作台；空闲有草稿时先清空草稿，
  空闲无草稿时提示再次 Ctrl+C 退出。Esc 优先关闭菜单/详情，不含糊取消任务。
- 模型和会话选择可发现；切换模型失败时保留原值，执行中禁用切换或明确排队。
  会话恢复显示真实历史和状态，不以重放旧 prompt 伪装恢复。
- tasks/inbox 显示后台任务状态、待回答问题与结果；操作调用统一运行时能力。
  patch acceptance 不得绕过 controller 的 identity/freshness/promotion 检查。
- 可选服务失败使用非阻塞状态提示，并说明影响和诊断入口；核心 provider 不可用时
  给出可操作的错误。详细日志与聊天区分开，不能只打印 “API failed to start”。
- native 模式借用终端后，返回必须恢复焦点、草稿、终端尺寸、输入模式和显示。
- 默认支持 Linux 交互终端、中文与 SSH；窄屏、无色模式、非 TTY 有明确降级行为。
  macOS/Windows 在各自实际验证前不得宣称相同体验已支持。

## Non-goals

- 本阶段不重做 Web Dashboard，不建立桌面 Electron 应用。
- 运行时迁移统一归 runtime-convergence；本计划不另建任务、provider 或恢复数据库。
- 不开放公开 mutation API，不改 localhost/Bearer 边界，不添加任务类型。
- 不复制 Codex 品牌或声称与其全部功能等价。
- 不把工具白名单、隔离状态、审批按钮做成没有后端约束的装饰。

## Interaction Layout

自上而下为：紧凑项目/模型/会话栏 → 可滚动对话与工具结果 → 持续可见的输入区 →
上下文相关快捷键/执行状态。`/` 菜单贴近输入区，tasks/session/model 使用同一选择器
风格。正常输出可选择复制；后台通知进入状态栏/inbox，不混入用户输入。

默认中文文案，保留命令与技术标识；颜色表达辅助信息，状态还需文字标记。
80×24 是首发最低可用尺寸，120×36 是主要验收尺寸；更窄时折叠次要状态。

## Technical Direction

交互层接入 runtime-convergence 的现有 TS runtime 与私有后台控制服务；UI 生命周期
与任务执行分开。输入/布局依赖仍需原型验证中文、多行、菜单、流式输出、resize 和
native 终端交接后选择。旧 Python Rich/prompt_toolkit 方向作为历史候选保留在 Git；
不得复制另一套 runtime、直接写 SQLite 或用转发 Python 冒充迁移完成。

以下 Python 文件仍是现有生产行为的迁移与对照来源；新入口和后台服务的运行方式见
[local-control-service](../runtime-convergence/local-control-service.md)。

- `cli_commands/terminal.py`、`terminal/app.py`：入口、生命周期、终端能力检测。
- `terminal/enhanced_shell.py`：拆分输入/展示与当前串行循环，保留普通文本降级入口。
- `terminal/command_router.py`、`terminal/help.py`：共享命令描述供菜单、帮助与执行使用；
  校验支持能力，不把不存在的命令显示为可用。未知 slash 命令给本地纠错提示。
- `terminal/rendering.py`：消息类型、Markdown/代码/工具视图、输出清理。
- `terminal/runtime.py`：提供展示需要的现有事件与操作适配，不在 UI 持久化任务状态。
- `terminal/session.py`、`inbox.py`、`tasks_view.py`、`native_pty.py`：优先复用并审计实际能力。
- UI 只暂存草稿/选中项；统一 session/TaskHub runtime 拥有历史、任务、结果与恢复。

## Plan

### Phase 0 — 需求与基线（complete）

- [x] 记录用户纠偏、截图事实和实际终端模块。
- [x] 建立计划、findings、progress，更新项目意图与优先级。
- [x] 区分本次计划交付与未来产品验收。

### Phase 1 — 可操作交互原型（pending）

- [ ] 核验实际 `cm` 导入版本、runtime、终端能力及 API 启动失败原因。
- [ ] 完成真实终端原型：首屏、输入区、`/` 菜单、中文多行、流式输出和 resize。
- [ ] 比较候选输入/布局方案，检查依赖与打包，冻结选择并记录理由。
- [ ] 保存启动、菜单、执行、失败四类可复现屏幕证据；以此验收第一增量。

### Phase 2 — 前台执行闭环（pending）

- [ ] 接入真实 runtime 的消息/工具/状态事件，隔离日志输出。
- [ ] 完成取消、错误恢复、草稿保留、模型选择、native 交接。
- [ ] provider 断开/无凭据/超时后 UI 可继续操作；不静默降级隔离策略。

### Phase 3 — 持续工作与任务视图（pending）

- [ ] 接入现有会话列表/恢复、task/inbox/问题应答，明确前台与后台生命周期。
- [ ] 结果有来源和状态；失败或取消不显示成功，重试不重复提交旧工作。
- [ ] 退出说明后台任务如何继续；进程重启后以持久化状态恢复展示。

### Phase 4 — 产品验收与发布（pending）

- [ ] 执行下表 PTY/集成与人工终端验收；截图/录屏去除凭据和个人路径。
- [ ] 跑修改范围 Ruff、terminal/CLI/runtime focused、完整 Python 与既有安全门禁。
- [ ] 若产品协议或 TS 输入发生变化，再执行协议漂移、SDK、typecheck、Web build。
- [ ] 隔离安装产物验证 `cm`/`controlmesh` 入口一致，并验证用户日常 shell 启动。
- [ ] 更新安装/使用文档与实际能力说明，记录验收环境、命令、结果和剩余限制。

## Acceptance

| ID | 场景 | 可观察通过条件 |
|---|---|---|
| UX-01 | 从项目目录运行 cm | 显示实际版本、项目、模型和会话，输入可用；不泄露凭据 |
| UX-02 | 输入 / 并筛选 model | 菜单即时出现；键盘选中；Esc 保留原草稿；未提交不调用 provider |
| UX-03 | 中文/emoji/三行粘贴 | 字符完整、光标正确；显式提交前调用次数为零 |
| UX-04 | 流式回答和工具运行 | 输入区稳定，工具来源/状态可见；最终文本不重复 |
| UX-05 | 执行中 Ctrl+C | 当前回合取消并收到确认，session 保留；下次输入能继续 |
| UX-06 | 模型切换与恢复会话 | 展示与实际 provider/session 一致，历史不被重新执行 |
| UX-07 | 后台问题/结果到达 | 通知不抢焦点，不破坏草稿，inbox 能打开并调用既有应答路径 |
| UX-08 | 可选 API 失败/provider 不可用 | 区分可用/降级/阻断，显示原因与下一操作；无原始 traceback 污染 |
| UX-09 | 80×24 ↔ 120×36，长代码 | 不重叠、截断可理解，滚动/复制可用，resize 不丢输入 |
| UX-10 | native 进入/返回/异常退出 | provider 退出后终端 echo、raw mode、焦点和草稿恢复 |
| UX-11 | NO_COLOR/非 TTY/SSH | 有文字状态；非 TTY 不输出交互控制序列或挂起等待菜单 |
| UX-12 | 恶意 ANSI/Rich 文本 | 作为文本安全展示，不能伪造系统状态或执行终端控制动作 |

测试分三层：状态/命令单测、生产入口与 provider 边界集成、真实 PTY 与人工视觉验收。
自动化可使用受控 provider double；至少一次已配置官方 CLI 的真实端到端 smoke，
记录版本/环境/结果。未具备运行条件的验收标为未验证，不用 mock 结果代替。

## Success

新用户在正常终端中依次完成启动、发现命令、多行提问、查看执行、中断、切换模型、
恢复会话和读取任务结果，无需阅读源码或记住隐藏命令。UX-01 至 UX-12 通过，
并具备可复现的真实终端视觉证据，才可称为 Terminal Product v1 完成。

## Status

计划已建立；实现未开始。原有 runtime 测试与 TypeScript parity 不算本计划 UX 验收。

## Next Step

执行 Phase 1 的可操作交互原型，先打通首屏、中文输入、`/` 菜单与流式输出。
