from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from controlmesh.case_pack.io import load_case_pack
from controlmesh.case_pack.models import CasePack, EvidenceBackedModel, TimelineEntry

_ANCHOR_PREFIXES = {
    "msg": "messages",
    "event": "events",
    "tool": "tool_events",
    "artifact": "artifacts",
    "link": "links",
}


class CasePackLintError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("\n".join(errors))


def lint_case_pack_path(path: Path, *, raise_on_error: bool = False) -> list[str]:
    case_pack = load_case_pack(path)
    errors = lint_case_pack(case_pack)
    if errors and raise_on_error:
        raise CasePackLintError(errors)
    return errors


def lint_case_pack(case_pack: CasePack) -> list[str]:
    errors: list[str] = []
    anchor_index = _build_anchor_index(case_pack, errors)
    timeline_ids = {entry.id for entry in case_pack.timeline}
    turning_point_ids = {item.id for item in case_pack.turning_points}

    for label, item in _iter_evidence_backed(case_pack):
        errors.extend(_lint_evidence_refs(label, item, anchor_index))

    errors.extend(_lint_tool_events(case_pack))
    errors.extend(_lint_timeline(case_pack))
    errors.extend(_lint_turning_points(case_pack))
    errors.extend(_lint_lifted_items(case_pack, timeline_ids, turning_point_ids))
    return errors


def _iter_evidence_backed(case_pack: CasePack) -> Iterable[tuple[str, EvidenceBackedModel]]:
    collections: list[tuple[str, Iterable[EvidenceBackedModel]]] = [
        ("messages", case_pack.messages),
        ("artifacts", case_pack.artifacts),
        ("events", case_pack.events),
        ("tool_events", case_pack.tool_events),
        ("timeline", case_pack.timeline),
        ("turning_points", case_pack.turning_points),
        ("lifted_view.questions", case_pack.lifted_view.questions),
        ("lifted_view.misconceptions", case_pack.lifted_view.misconceptions),
        ("lifted_view.resolutions", case_pack.lifted_view.resolutions),
    ]
    for collection_label, items in collections:
        for item in items:
            yield f"{collection_label}.{item.id}", item


def _build_anchor_index(case_pack: CasePack, errors: list[str]) -> dict[str, object]:
    anchor_index: dict[str, object] = {}
    mapping = {
        "msg": case_pack.messages,
        "event": case_pack.events,
        "tool": case_pack.tool_events,
        "artifact": case_pack.artifacts,
        "link": case_pack.links,
    }
    for prefix, items in mapping.items():
        for item in items:
            anchor = f"{prefix}:{item.id}"
            if anchor in anchor_index:
                errors.append(f"duplicate anchor detected: {anchor}")
            anchor_index[anchor] = item
    return anchor_index


def _lint_evidence_refs(
    label: str, item: EvidenceBackedModel, anchor_index: dict[str, object]
) -> list[str]:
    errors: list[str] = []
    for ref in item.evidence_refs:
        prefix, _, _anchor_id = ref.partition(":")
        if prefix not in _ANCHOR_PREFIXES:
            errors.append(f"{label}: unsupported evidence ref prefix `{ref}`")
            continue
        if ref not in anchor_index:
            errors.append(f"{label}: unknown evidence ref `{ref}`")
    return errors


def _lint_tool_events(case_pack: CasePack) -> list[str]:
    event_ids = {event.id for event in case_pack.events}
    errors: list[str] = []
    for item in case_pack.tool_events:
        errors.extend(
            f"tool_events.{item.id}: linked_event_ids contains unknown event `{event_id}`"
            for event_id in item.linked_event_ids
            if event_id not in event_ids
        )
        if item.kept and not (item.why_it_matters and item.why_it_matters.strip()):
            errors.append(f"tool_events.{item.id}: kept=true requires why_it_matters")
    return errors


def _lint_timeline(case_pack: CasePack) -> list[str]:
    event_ids = {event.id for event in case_pack.events}
    tool_ids = {item.id for item in case_pack.tool_events}
    errors: list[str] = []
    expected_order = 1
    seen_timeline_ids: set[str] = set()
    for entry in case_pack.timeline:
        if entry.id in seen_timeline_ids:
            errors.append(f"timeline.{entry.id}: duplicate timeline id")
        seen_timeline_ids.add(entry.id)
        if entry.order != expected_order:
            errors.append(
                f"timeline.{entry.id}: order must be continuous starting at 1; "
                f"expected {expected_order}, got {entry.order}"
            )
            expected_order = entry.order + 1
        else:
            expected_order += 1
        errors.extend(_lint_timeline_ref(entry, event_ids, tool_ids))
    return errors


def _lint_timeline_ref(
    entry: TimelineEntry, event_ids: set[str], tool_ids: set[str]
) -> list[str]:
    if entry.kind == "event" and entry.ref_id not in event_ids:
        return [f"timeline.{entry.id}: ref_id points to unknown event `{entry.ref_id}`"]
    if entry.kind == "tool_event" and entry.ref_id not in tool_ids:
        return [f"timeline.{entry.id}: ref_id points to unknown tool_event `{entry.ref_id}`"]
    return []


def _lint_turning_points(case_pack: CasePack) -> list[str]:
    event_ids = {event.id for event in case_pack.events}
    tool_ids = {item.id for item in case_pack.tool_events}
    errors: list[str] = []
    for item in case_pack.turning_points:
        if not item.event_ids and not item.tool_event_ids:
            errors.append(
                f"turning point `{item.id}` must reference at least one event or tool_event"
            )
        errors.extend(
            f"turning_points.{item.id}: unknown event `{event_id}`"
            for event_id in item.event_ids
            if event_id not in event_ids
        )
        errors.extend(
            f"turning_points.{item.id}: unknown tool_event `{tool_event_id}`"
            for tool_event_id in item.tool_event_ids
            if tool_event_id not in tool_ids
        )
    return errors


def _lint_lifted_items(
    case_pack: CasePack, timeline_ids: set[str], turning_point_ids: set[str]
) -> list[str]:
    errors: list[str] = []
    collections = (
        ("questions", case_pack.lifted_view.questions),
        ("misconceptions", case_pack.lifted_view.misconceptions),
        ("resolutions", case_pack.lifted_view.resolutions),
    )
    for collection_name, items in collections:
        for item in items:
            if not item.timeline_refs and not item.turning_point_refs:
                errors.append(
                    f"lifted_view.{collection_name}.{item.id}: requires timeline_refs or "
                    "turning_point_refs"
                )
            errors.extend(
                f"lifted_view.{collection_name}.{item.id}: unknown timeline ref `{timeline_ref}`"
                for timeline_ref in item.timeline_refs
                if timeline_ref not in timeline_ids
            )
            errors.extend(
                f"lifted_view.{collection_name}.{item.id}: unknown turning point ref "
                f"`{turning_ref}`"
                for turning_ref in item.turning_point_refs
                if turning_ref not in turning_point_ids
            )
    return errors
