# Findings

- `cli_commands/feishu.py` 只有创建/完成/诊断别名，没有绑定已有应用入口。
- `auth.py` 文案错误地将 native 与创建新应用绑定，已有应用只推荐 bridge。
- native 配置接受 app_id/app_secret；绑定已有应用不需要新身份模型或 runtime。
- 现有 register probe 使用环境变量传递凭据，可复用；配置持久化原子写入为 0600。
- 用户报告的飞书 CLI 交互是需求来源，不作为已验证的上游 API 行为。
- 当前 config 只支持 brand=feishu；不宣称本次支持 Lark。
