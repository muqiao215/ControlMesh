# Progress

## Current

2026-09-06：SpecMesh 计划交付完成，Terminal Product v1 实现未开始。

## Done

- 记录用户对终端产品质量的明确纠偏。
- 审计真实入口、逐行输入、渲染、路由及 runtime 复用点。
- 建立分阶段计划与 UX-01 至 UX-12 可观察验收标准。
- 将终端体验提升写入 PROJECT 用户意图、当前缺口和最高优先级。
- 将功能门禁与用户体验分别验收的决定沉淀至 DECISIONS。
- 检查三份任务文件与 PROJECT 索引目标存在，PROJECT 为 171 行；
  `git diff --check` 通过。本次仅文档变更，无新增运行时测试结果。

## Remaining

Phase 1 至 Phase 4：交互原型、前台执行闭环、持续工作视图、真实终端验收与发布。

## Issues

截图中的 API 启动失败根因与运行版本尚待核实。输入库选型尚待原型验证。
`cm` alias 已落地并由品牌契约覆盖；它只解决可发现入口，不代表终端产品改造完成。

## Next

从 Phase 1 开始做可操作终端原型，优先首屏、中文多行、slash 菜单、流式输出。

## 2026-09-13 — TS socket terminal prototype

Implemented explicit `cm-runtime --socket ABS ui`, dynamically loaded OpenTUI 0.5.11 on Bun 1.3.11. Header reads service registration; scrollable task/event view, fixed multiline composer and filtered slash menu. New task uses acknowledged submit revision for enqueue. Lost acknowledgement retains target, request ID and draft; no automatic mutation replay. Explicit resume registers new input; enqueue remains explicit. Ctrl+C reads current revision and requests cancellation while preserving draft; cancellation acknowledgement does not assert process exit. Non-TTY exits before renderer loading.

Validation: typecheck passed. Focused CLI + terminal: 10 pass, 0 fail, 80 assertions (10.90s), `/tmp/cm-terminal-focused-authorized.log`. Renderer tests cover Chinese/emoji bracketed paste, resize, menu selection without mutation, ambiguous submit, current-revision enqueue/cancel and non-TTY. Initial service tests failed in restricted environment; after network permission and configured UV cache, passed without service implementation changes. Actual PTY command `/quit` exited 0, echo and ICANON restored. No real provider invoked.

Still pending: native borrowing, actual provider streaming, inbox selection/reply UX, richer session/model selection, NO_COLOR validation, full visual/real-model acceptance and packaging/cutover. This is a prototype, not UX-01..12 completion.
