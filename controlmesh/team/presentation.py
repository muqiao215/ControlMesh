"""User-facing formatting helpers for topology progress surfaces."""

from __future__ import annotations

from controlmesh.team.models import TeamTopologyProgressSummary

_DETAIL_LIMIT = 96
_SUMMARY_LIMIT = 140


def _compress(value: str, *, limit: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3].rstrip()}..."


def _render_roles(label: str, roles: list[str]) -> str | None:
    if not roles:
        return None
    return f"{label}: {', '.join(roles)}"


def _render_round(summary: TeamTopologyProgressSummary) -> str | None:
    if summary.round_index is None or summary.round_limit is None:
        return None
    return f"round {summary.round_index}/{summary.round_limit}"


def render_topology_progress_lines(summary: TeamTopologyProgressSummary) -> list[str]:
    """Render a shared compact topology progress block."""
    header_parts = [f"topology: {summary.topology}", summary.substage, summary.phase_status]
    round_text = _render_round(summary)
    if round_text is not None:
        header_parts.append(round_text)
    lines = [" · ".join(header_parts)]

    detail_parts = [
        part
        for part in (
            _render_roles("active", summary.active_roles),
            _render_roles("done", summary.completed_roles),
            f"artifacts: {summary.artifact_count}" if summary.artifact_count else None,
        )
        if part is not None
    ]
    if detail_parts:
        lines.append(" | ".join(detail_parts))

    state_parts = []
    if summary.waiting_on:
        state_parts.append(f"waiting: {_compress(summary.waiting_on, limit=_DETAIL_LIMIT)}")
    if summary.repair_state:
        state_parts.append(f"repair: {_compress(summary.repair_state, limit=_DETAIL_LIMIT)}")
    if state_parts:
        lines.append(" | ".join(state_parts))

    if summary.latest_summary:
        lines.append(f"summary: {_compress(summary.latest_summary, limit=_SUMMARY_LIMIT)}")

    return lines
