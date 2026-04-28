"""Render provider-native command snapshots for chat surfaces."""

from __future__ import annotations

from controlmesh.cli.introspection import ProviderIntrospection


def render_native_command_registry(snapshot: ProviderIntrospection) -> str:
    """Render the main `/cm` native command registry view."""
    lines = [
        "**Native Commands**",
        "",
        f"Provider: `{snapshot.provider or 'unknown'}`",
        f"Target model: `{snapshot.model or 'default'}`",
        f"Health: `{'ok' if snapshot.healthy else 'warning'}`",
        f"Installed: `{snapshot.installed}`",
        f"Auth: `{snapshot.auth_status}`",
    ]
    if snapshot.version:
        lines.append(f"Version: `{snapshot.version}`")
    lines.extend(
        [
            f"Registry source: `{snapshot.command_source}`",
            "",
            "**Commands**",
        ]
    )

    visible = [command for command in snapshot.native_commands if command.visible]
    if not visible:
        lines.append("- 当前 provider 没有返回可展示的 native command 列表。")
    else:
        for command in visible:
            extras: list[str] = []
            if command.shadowed_by_controlmesh:
                extras.append("ControlMesh 优先")
            if command.source.value != "provider":
                extras.append(command.source.value)
            suffix = f" _({' | '.join(extras)})_" if extras else ""
            desc = f" — {command.description}" if command.description else ""
            lines.append(f"- `{command.slash}`{desc}{suffix}")

    lines.extend(
        [
            "",
            "- `/back` 返回 ControlMesh 命令",
            "",
            "规则：ControlMesh owned / reserved 命令优先；只有未注册的 `/xxx` 才透传给当前 CLI。",
        ]
    )
    if snapshot.errors:
        lines.extend(["", "**Probe warnings**", *[f"- {error}" for error in snapshot.errors]])
    return "\n".join(lines)


def render_native_runtime_summary(snapshot: ProviderIntrospection) -> str:
    """Render a compact native-runtime summary for `/status`."""
    command_count = len([command for command in snapshot.native_commands if command.visible])
    lines = [
        "Native runtime:",
        f"  provider={snapshot.provider}",
        f"  model={snapshot.model or 'default'}",
        f"  installed={snapshot.installed}",
        f"  auth={snapshot.auth_status}",
        f"  registry={snapshot.command_source}",
        f"  commands={command_count}",
    ]
    if snapshot.version:
        lines.append(f"  version={snapshot.version}")
    return "\n".join(lines)
