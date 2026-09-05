# Findings

- `cli_commands/feishu.py` 只有创建/完成/诊断别名，没有绑定已有应用入口。
- `auth.py` 文案错误地将 native 与创建新应用绑定，已有应用只推荐 bridge。
- native 配置接受 app_id/app_secret；绑定已有应用不需要新身份模型或 runtime。
- 现有 register probe 会执行 AI Agent 注册动作，不适合只读绑定验证；新入口改用
  tenant token 加官方 bot info 读取，并在写入前显示非敏感机器人身份。
- 配置持久化沿用 `atomic_json_save`，结果权限为 0600。
- 用户报告的飞书 CLI 交互是需求来源，不作为已验证的上游 API 行为。
- 当前 config 只支持 brand=feishu；不宣称本次支持 Lark。
- native/bridge 是运行方式，创建/绑定是凭据来源；两者不能再被文案绑定为同一选择。
- `cm` console script 加入后，品牌契约也必须同时固定长短两个入口。
