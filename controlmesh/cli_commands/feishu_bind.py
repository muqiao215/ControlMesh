"""Bind an existing self-built Feishu app without app registration."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import re
import sys
from collections.abc import Sequence

import aiohttp
from rich.console import Console

from controlmesh.config import AgentConfig
from controlmesh.infra.json_store import atomic_json_save
from controlmesh.workspace.paths import resolve_paths

_BASE = "https://open.feishu.cn/open-apis"


async def verify_bot(app_id: str, secret: str) -> None:
    """Authenticate the app and verify that it has an accessible bot identity."""
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
        async with session.post(
            f"{_BASE}/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": secret},
            allow_redirects=False,
        ) as response:
            if response.status != 200:
                raise ValueError("credential_http_error")
            payload = await response.json()
        if not isinstance(payload, dict) or payload.get("code") != 0:
            raise ValueError("credentials_rejected")
        token = payload.get("tenant_access_token")
        if not isinstance(token, str) or not token:
            raise ValueError("token_missing")
        async with session.get(
            f"{_BASE}/bot/v3/info",
            headers={"Authorization": f"Bearer {token}"},
            allow_redirects=False,
        ) as response:
            if response.status != 200:
                raise ValueError("bot_http_error")
            payload = await response.json()
        if not isinstance(payload, dict) or payload.get("code") != 0:
            raise ValueError("bot_unavailable")
        bot = payload.get("bot")
        if (
            not isinstance(bot, dict)
            or not isinstance(bot.get("open_id"), str)
            or not bot["open_id"]
        ):
            raise ValueError("bot_identity_missing")


def cmd_bind(args: Sequence[str]) -> None:
    """Verify credentials before atomically merging them into local config."""
    from controlmesh.cli_commands.auth import _enable_primary_transport, load_config

    parser = argparse.ArgumentParser(
        prog="controlmesh feishu bind",
        description="绑定已有飞书自建应用机器人到 native runtime（不创建新应用）。",
    )
    parser.add_argument("--app-id", help="已有应用的 App ID")
    parser.add_argument("--secret-env", help="包含 App Secret 的环境变量名；默认隐藏输入")
    parser.add_argument("--replace", action="store_true", help="允许替换当前不同的 App ID")
    options = parser.parse_args(list(args))
    console = Console()
    config = load_config()
    path = resolve_paths(controlmesh_home=config.controlmesh_home).config_path
    before = path.read_bytes() if path.exists() else None
    try:
        raw = json.loads(before) if before is not None else config.model_dump(mode="json")
        if not isinstance(raw, dict) or not isinstance(raw.get("feishu", {}), dict):
            raise ValueError
    except (ValueError, TypeError):
        console.print("配置格式无效；未写入。")
        raise SystemExit(1) from None
    pending = path.parent / "feishu_registration_pending.json"
    if pending.exists():
        console.print("存在待完成的新应用注册；请先处理该流程，避免异步回写覆盖绑定。")
        raise SystemExit(1)
    app_id = options.app_id
    if not app_id:
        if not sys.stdin.isatty():
            parser.error("非交互模式需要 --app-id 和 --secret-env")
        app_id = input("已有机器人 App ID: ").strip()
    if not re.fullmatch(r"cli_[A-Za-z0-9]+", app_id):
        parser.error("App ID 应为 cli_ 开头的应用标识，不是群 ID 或 webhook 地址")
    feishu = dict(raw.get("feishu", {}))
    if feishu.get("app_id") and feishu["app_id"] != app_id and not options.replace:
        console.print("当前已绑定其他应用；确认替换时添加 --replace。配置未改变。")
        raise SystemExit(1)
    if options.secret_env:
        secret = os.environ.get(options.secret_env, "").strip()
    else:
        if not sys.stdin.isatty():
            parser.error("非交互模式需要 --secret-env；不要在参数中传递密钥")
        secret = getpass.getpass("App Secret（隐藏输入）: ").strip()
    if not secret:
        parser.error("App Secret 不能为空")
    try:
        asyncio.run(verify_bot(app_id, secret))
    except (aiohttp.ClientError, TimeoutError, ValueError, TypeError):
        console.print("验证失败；检查 App ID/Secret、机器人能力和网络。配置未改变。")
        raise SystemExit(1) from None
    feishu.update(
        app_id=app_id,
        app_secret=secret,
        runtime_mode="native",
        brand="feishu",
        domain="https://open.feishu.cn",
    )
    # Preserve existing delivery and authorization choices; CardKit needs separate readiness.
    raw["feishu"] = feishu
    _enable_primary_transport(raw, "feishu")
    try:
        AgentConfig.model_validate(raw)
    except ValueError:
        console.print("合并后的配置无效；配置未改变。")
        raise SystemExit(1) from None
    if (path.read_bytes() if path.exists() else None) != before or pending.exists():
        console.print("验证期间配置或注册流程已变化；请重新运行绑定。未写入。")
        raise SystemExit(1)
    atomic_json_save(path, raw)
    console.print("已有机器人凭据已验证，已绑定到 CM native runtime。")
    console.print("群策略与白名单已保留；绑定不代表消息接收或 CardKit 权限已就绪。")
    console.print(
        "下一步：确认应用发布、消息事件订阅和权限，运行 controlmesh feishu native doctor。"
    )
    console.print("配置应用于下次启动；运行 controlmesh bot，已有服务请安排重启。")
    console.print("若同一机器人仍由其他程序接收消息，请先明确连接归属再启动 CM。")
