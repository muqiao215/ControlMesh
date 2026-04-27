"""Tests for route score event JSONL output."""

from __future__ import annotations

import json
from pathlib import Path

from controlmesh.routing.score_events import RouteScoreEvent, append_score_event


def test_append_score_event_writes_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "routing" / "score_events.jsonl"

    append_score_event(
        path,
        RouteScoreEvent(
            agent_slot="opencode.explore",
            workunit_kind="test_execution",
            success=True,
        ),
    )

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["agent_slot"] == "opencode.explore"
