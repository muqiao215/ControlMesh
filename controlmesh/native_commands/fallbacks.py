"""Static fallback native command snapshots for provider CLIs."""

from __future__ import annotations

from dataclasses import replace

from controlmesh.cli.introspection import (
    NativeCommandSource,
    NativeCommandSpec,
    ProbeStatus,
)
from controlmesh.command_registry import is_controlmesh_owned_command

_CLAUDE_COMMANDS: tuple[tuple[str, str], ...] = (
    ("add-dir", "添加额外工作目录"),
    ("agents", "管理 Claude 子代理"),
    ("bug", "向 Anthropic 报告问题"),
    ("clear", "清空对话并开始新聊天"),
    ("compact", "压缩当前上下文"),
    ("config", "查看或修改配置"),
    ("cost", "查看 token / 成本统计"),
    ("doctor", "检查 Claude Code 安装健康"),
    ("help", "打开 Claude 帮助"),
    ("init", "生成 CLAUDE.md / 项目指令脚手架"),
    ("login", "切换 Claude 账号"),
    ("logout", "退出 Claude 账号"),
    ("mcp", "管理 MCP 连接"),
    ("memory", "编辑 CLAUDE.md 记忆"),
    ("model", "切换模型"),
    ("permissions", "查看或调整权限"),
    ("pr_comments", "查看 PR 评论"),
    ("remote-control", "管理远程控制服务器"),
    ("rc", "remote-control 简写"),
    ("review", "发起代码审查"),
    ("status", "查看账户和系统状态"),
    ("terminal-setup", "安装终端换行绑定"),
    ("vim", "进入 Vim 模式"),
)

_CODEX_COMMANDS: tuple[tuple[str, str], ...] = (
    ("permissions", "设置无需再次确认的权限"),
    ("sandbox-add-read-dir", "为额外目录授予沙箱只读访问"),
    ("agent", "切换当前 agent thread"),
    ("apps", "浏览并插入 app / connector"),
    ("plugins", "浏览或管理插件"),
    ("clear", "清屏并开始新会话"),
    ("compact", "总结并压缩可见上下文"),
    ("copy", "复制最近一次完成的输出"),
    ("diff", "查看当前工作区 diff"),
    ("exit", "退出 Codex"),
    ("experimental", "切换实验特性"),
    ("feedback", "提交日志和反馈"),
    ("init", "生成 AGENTS.md 脚手架"),
    ("logout", "退出 Codex"),
    ("mcp", "列出 MCP 工具"),
    ("mention", "把文件附加到当前会话"),
    ("model", "切换模型"),
    ("fast", "切换 Fast mode"),
    ("plan", "进入 plan mode"),
    ("personality", "切换回复风格"),
    ("ps", "查看后台终端"),
    ("stop", "停止后台终端"),
    ("fork", "分叉当前会话"),
    ("resume", "恢复已保存会话"),
    ("new", "在当前 CLI 内开始新会话"),
    ("quit", "退出 Codex"),
    ("review", "审查当前 working tree"),
    ("status", "查看会话配置和 token 使用"),
    ("debug-config", "查看配置层与要求诊断"),
    ("statusline", "配置底部状态栏"),
    ("title", "配置终端标题"),
)

_GEMINI_COMMANDS: tuple[tuple[str, str], ...] = (
    ("memory", "管理 Gemini CLI 记忆"),
    ("stats", "查看 Gemini CLI 使用统计"),
    ("tools", "查看工具状态"),
    ("mcp", "查看或管理 MCP 工具"),
)

_OPENCODE_COMMANDS: tuple[tuple[str, str], ...] = (
    ("init", "创建项目初始化命令或上下文"),
    ("undo", "撤销上一项操作"),
    ("redo", "重做上一项操作"),
    ("share", "共享当前会话"),
    ("help", "打开 OpenCode 帮助"),
)

_FALLBACKS: dict[str, tuple[tuple[str, str], ...]] = {
    "claude": _CLAUDE_COMMANDS,
    "codex": _CODEX_COMMANDS,
    "gemini": _GEMINI_COMMANDS,
    "opencode": _OPENCODE_COMMANDS,
    "claw": (),
}


def fallback_native_commands(provider: str) -> tuple[NativeCommandSpec, ...]:
    """Return a static fallback registry for one provider."""
    commands = _FALLBACKS.get(provider, ())
    specs = tuple(
        NativeCommandSpec(
            name=name,
            description=description,
            provider=provider,
            status=ProbeStatus.UNKNOWN,
            source=NativeCommandSource.STATIC_FALLBACK,
            shadowed_by_controlmesh=is_controlmesh_owned_command(name),
        )
        for name, description in commands
    )
    return _dedupe_alias_pairs(specs)


def _dedupe_alias_pairs(commands: tuple[NativeCommandSpec, ...]) -> tuple[NativeCommandSpec, ...]:
    seen: set[str] = set()
    deduped: list[NativeCommandSpec] = []
    for command in commands:
        normalized = command.name.lower().lstrip("/")
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(replace(command, name=normalized))
    return tuple(deduped)
