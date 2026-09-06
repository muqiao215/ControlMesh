# Progress

## Current

2026-09-07：本地/远端 main 统一为 `3417ae0`，Unit A v1 已落地且对应 CI 成功。
A.1 计划就绪、尚未实施；B–E 仍排队。旧日期的基线和测试数仅代表当时核验。

## Landing

2026-09-06：计划文件与 PROJECT.md 索引已提交推送（docs(plan) 提交）。独立复核：
56 项核验测试重跑通过；uv.lock 与 feishu-bind-existing 的工作区改动属于发布流/
绑定流，未混入本提交。

## Done

- 读取周报全部分页，覆盖 08-07 历史至 09-06 架构设计。
- 对照源码、现有计划、focused tests，区分已完成、部分完成、待核验与 Deferred。
- 记录本地 ac830ae / 远端 a8f88a4 差异，保留其他提交原样。
- 建立 A 工具授权 → B 诊断 → C 强杀恢复 → D fleet/canary → E 真机闭环队列。
- 明确 fingerprint、episode 恢复、旧记录/回滚与外部回复幂等的验收约束。
- 相关已有测试：56 passed；本次只修改文档，不重复完整代码 gate。

## Remaining

先完成 execution-tool-grants-enforcement-closure（A.1），再按 B–E 执行。
终端体验仍由 terminal-product-v1 原计划负责。

## Issues

- 无两节点现场执行证据，不能宣称飞书 canary 已验收。
- 外部报告的 endpoint 问题、旧 daily-note 归因尚待对应生产路径的定向复核。
- 前期读取输出过大曾被截断，改用按条目提取完整最新设计并继续历史分页。
- 一次错误的多参数 rev-parse 已改为分别读取 HEAD 与 origin/main。

## Next

执行 A.1 Phase 0：真实入口、网络/确认强制契约、恢复与回复归属。
