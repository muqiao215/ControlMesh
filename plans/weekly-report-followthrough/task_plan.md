# Weekly Report Follow-through

## Goal

将历史周报和同类架构雷达的未完成建议整理成有代码依据、依赖关系和验收条件的开发队列。
本次交付审计与 SpecMesh 计划；后续实现状态独立记录，不因计划写完而标作功能完成。

## Context

2026-09-06 审计，基线 main `ac830ae`。Terminal Product v1 仍是产品最高优先级。
历史方案详见 [原评估](../operational-proof-v1-assessment/task_plan.md)，当前证据见
[findings.md](findings.md)。已完成的 golden、沙箱拒绝降级与长连接工作不重新立项。

## Requirements

- Python 继续拥有授权、执行、持久化、恢复、结果写回和 controller promotion。
- 复用 ExecutionContext、现有 task/episode 与 packet_id + task_id + line + plan_id；
  trace 是关联信息，不替代执行身份或授权证明。
- 授权只能收窄；群消息和自动执行仍遵守沙箱强制要求。
- 公共 OpenAPI、SDK、Web 保持只读，Mutation API Admission 继续 Deferred。
- 观察结果无正文、凭据与绝对路径；保留兼容读取和可验证的回滚边界。

## Plan

- [x] 读取周报完整分页，核对最新设计与历史建议。
- [x] 审计当前实现、相关测试、现有计划和未决边界。
- [x] 建立不重复的实施队列、验收条件和项目索引。
- [x] A v1：execution-tool-grants，提供快照、映射/拒绝、持久化和 golden（3417ae0）。
- [ ] A.1：execution-tool-grants-enforcement-closure，完成真实入口和安全语义闭环。
- [ ] B：cross-node-trace-diagnose，形成持久化诊断链。
- [ ] C：process-recovery-fault-matrix，验证强杀与恢复。
- [ ] D：fleet-readiness-canary，节点一致性与两节点实测。
- [ ] E：三条业务闭环真实执行验收。

### A — Tool grants（下一个安全代码单元）

先审计 `bus/envelope.py`、`execution_policy.py`、`tasks/models.py`、`cli/types.py`、
`orchestrator/core.py` 及各 provider adapter 的工具参数与恢复入口。
在可信 Python ingress 生成最小权限快照，跟随现有执行身份持久化；使用现有 transport、
chat/topic/thread 归属建立回复约束，避免另建一套与实际投递不一致的 target 模型。

实现前确定：哪些工具限制能由各 CLI 强制落实，哪些需要 CM 工具边界或沙箱执行。
不支持限制的 provider 必须拒绝受限任务或选择可执行的受限路径，不能仅把白名单放进 prompt。
网络、写入目录与确认级别必须分别有实际 enforcement；现有描述字段不是权限门禁。

验收：正常跨 provider、后台恢复权限一致、篡改、跨 task/episode 重放、越权请求、
无秘密序列化、旧记录兼容七组；再覆盖原回复线程、缓存隔离和不支持限制的 provider。
fingerprint 只证明内容一致，不能作为签发者真实性证明；恢复由 owner 验证旧身份，
为新 episode 重新绑定不扩大权限的快照，不能直接复用旧 episode grant。

迁移：优先任务 JSON 可选字段与严格版本解析；旧记录缺失不能自动获得高风险权限。
回滚：验证旧读取器行为；有新增受限任务时禁止回到会忽略 grant 的旧执行路径，必要时隔离任务。
先覆盖生产 enforcement，再生成规范化 golden 和 drift gate；不采用周报的行数估计作为承诺。

### B — Cross-node trace / diagnose

复用 ExecutionContext 和现有事件存储，贯通 ingress、路由、task/episode、provider、
result、promotion。先定稳定 reason codes、保留期限与查询权限，再提供消息查询入口。
各节点可以有不同本地 trace；通过 transport 范围内规范化消息关联键建立父子关系，
不能假设两个节点随机生成的 trace_id 相同。优先受控只读导出/已有 fleet 通道，避免新增远程服务。

验收：同一消息在两个节点的接收/静默/拒绝/执行链可合并；缺失节点明确 unknown；
重启后仍可查询；恢复 lineage 可追溯；不同会话无数据串读；不依赖日志文本抓取。

### C — Process recovery fault matrix

依赖 B 的持久化观测。在真实 Python 子进程的 provider 启动、结果持久化、投递确认、
promotion 提交前后设置确定性屏障，强杀进程并以同一临时工作区重启。
复用现有 production golden runner 的身份和规范化模式。

验收：每个当前 episode 最多一个 canonical result、每个候选一次 promotion；
错误 owner/旧 episode 不得回写；中途 canonical 写入具有明确的恢复结果。
外部回复发生在远端接受与本地确认之间时，要证明平台幂等/对账机制，或明确标记投递结果未知；
不能从本地去重推导出用户只收到一条回复。矩阵检查缺失、额外案例和字段漂移并进入 CI。

### D — Fleet readiness / Feishu canary

复用现有 provider fleet inventory/doctor；增加非敏感节点版本、commit、能力、沙箱、
配置摘要、local_bot_agent/coordinator 与心跳观察。明确过期阈值与 not-ready reason。
重复机器人身份、coordinator 冲突、版本/策略不兼容和离线节点都可诊断。
按已有飞书 canary 文档跑普通消息、精准 @、/all、bot 交接、循环预算和原线程回复；
保留两个真实节点的关联证据，再决定扩散。真实身份和凭据只留在运行环境。

### E — 三闭环验收

- test_execution：真实 Docker + 官方 CLI 派发、执行、回写、恢复；代码目录保持只读约束。
- code_review：真实 review_fanout → merge，冲突可见，证据可追溯。
- patch_candidate：生成 proposed_*、验证命令和审计，controller 接受/拒绝，拒绝 canonical 不变。

每条链路绑定确定提交和脱敏证据，分别标记自动测试、真机执行与外部投递结果。

## Deferred / Secondary

- Mutation 操作与权限 UI：沿用现有 Admission Review，不能因 A–E 完成自动开放。
- lark-cli/MCP 业务工具：A 后按最小能力接入；绑定机器人功能不等于业务工具后端。
- provider endpoint 保留：先审计认证切换是否存在同类缺陷，再决定补测试/修复。
- 自更新候选 staging/canary/回滚、远程 Web 与浏览器凭据：保留为独立边界，当前不实施。
- 旧周报的 daily-note snippet 归因：需定向复核当前兼容分支，不能据历史措辞认定仍缺失。

## Verification

本次仅修改文档：核对文件/链接与 diff，执行相关已有 focused tests 核验历史缺口。
每个后续代码单元执行 focused、修改范围 Ruff 与全 Python；涉及协议/TS 再跑生成漂移、
typecheck、SDK/Web build 和公开只读门禁。真机条件缺失时不得把该项记为完成。

## Status

审计及计划交付完成。A v1 已落地于 `3417ae0`，完整安全验收继续由
[A.1 enforcement closure](../execution-tool-grants-enforcement-closure/task_plan.md) 收口；
B–E 尚未实施。Terminal Product v1 保持主线。

## Next Step

执行 A.1 Phase 0，确定网络、确认与真实入口签发契约，再推进 B。
