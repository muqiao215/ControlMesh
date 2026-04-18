from __future__ import annotations

from collections.abc import Iterable

from controlmesh.case_pack.models import CasePack, LiftedItem, TimelineEntry, TurningPoint


def render_timeline_markdown(case_pack: CasePack) -> str:
    lines = [
        f"# {case_pack.title}",
        f"`case_id`: {case_pack.case_id}",
        "",
        "## Summary",
        case_pack.summary,
        "",
        "## Timeline",
    ]
    lines.extend(_render_timeline_entries(case_pack.timeline))
    lines.extend(["", "## Turning Points"])
    lines.extend(_render_turning_points(case_pack.turning_points))
    return "\n".join(lines) + "\n"


def render_lifted_markdown(case_pack: CasePack) -> str:
    lines = [
        f"# {case_pack.title}",
        f"`case_id`: {case_pack.case_id}",
        "",
        "## Summary",
        case_pack.summary,
        "",
        "## Questions",
    ]
    lines.extend(_render_lifted_items(case_pack.lifted_view.questions))
    lines.extend(["", "## Misconceptions"])
    lines.extend(_render_lifted_items(case_pack.lifted_view.misconceptions))
    lines.extend(["", "## Resolutions"])
    lines.extend(_render_lifted_items(case_pack.lifted_view.resolutions))
    return "\n".join(lines) + "\n"


def _render_timeline_entries(entries: Iterable[TimelineEntry]) -> list[str]:
    lines: list[str] = []
    for entry in entries:
        lines.extend(
            [
                f"{entry.order}. **{entry.title}** (`{_timeline_anchor(entry)}`)",
                f"   - Summary: {entry.summary}",
                f"   - Evidence: {_format_refs(entry.evidence_refs)}",
            ]
        )
    return lines or ["- No timeline entries."]


def _render_turning_points(items: Iterable[TurningPoint]) -> list[str]:
    lines: list[str] = []
    for item in items:
        lines.extend(
            [
                f"- **{item.title}** (`turning_point:{item.id}`)",
                f"  - Summary: {item.summary}",
                f"  - Events: {_format_refs(f'event:{event_id}' for event_id in item.event_ids)}",
                "  - Tool events: "
                + _format_refs(f"tool:{tool_event_id}" for tool_event_id in item.tool_event_ids),
                f"  - Evidence: {_format_refs(item.evidence_refs)}",
            ]
        )
    return lines or ["- No turning points."]


def _render_lifted_items(items: Iterable[LiftedItem]) -> list[str]:
    lines: list[str] = []
    for item in items:
        lines.extend(
            [
                f"- **{item.title}**",
                f"  - Summary: {item.summary}",
                f"  - Timeline refs: {_format_refs(item.timeline_refs)}",
                f"  - Turning points: {_format_refs(item.turning_point_refs)}",
                f"  - Evidence: {_format_refs(item.evidence_refs)}",
            ]
        )
    return lines or ["- None."]


def _format_refs(refs: Iterable[str]) -> str:
    values = list(refs)
    return ", ".join(f"`{value}`" for value in values) if values else "-"


def _timeline_anchor(entry: TimelineEntry) -> str:
    prefix = "event" if entry.kind == "event" else "tool"
    return f"{prefix}:{entry.ref_id}"
