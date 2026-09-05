# Bind Existing Feishu Bot

## Goal

提供 `cm feishu bind` / `cm feishu native bind`，将已有飞书自建应用机器人接入
CM native runtime，无需重新创建机器人或手工改成 bridge。

## Requirements

- App ID 与隐藏输入的 App Secret（自动化可从指定环境变量读取）。
- 复用现有官方接口探测，验证成功后才写配置；失败不输出凭据、不改配置。
- 已绑定不同应用时要求显式替换；保留群策略、白名单及其他 transport 配置。
- 不自动创建机器人、不更改上游订阅、不启动第二个连接或重启服务。
- 说明本地绑定与发布/权限/订阅就绪的区别；用户 OAuth 不等于应用机器人绑定。

## Plan

- [x] 审计 native aliases、auth-kit probe、配置原子写入与现有测试。
- [x] 实现输入、探测、原子配置合并和 CLI 帮助入口。
- [x] 验证成功、失败、替换、配置保留、凭据输出与帮助。
- [x] 更新用户文档与项目记忆。

## Status

Complete. Terminal Product v1 remains planned separately.

## Next Step

发布后使用真实已有应用完成一次凭据与事件订阅 smoke test；这不阻塞代码 scope 封板。
