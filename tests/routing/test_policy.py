"""Tests for WorkUnit detection policy."""

from __future__ import annotations

from controlmesh.routing.policy import detect_workunit_kind, normalize_topology
from controlmesh.routing.workunit import WorkUnitKind


def test_detects_pytest_command_as_test_execution() -> None:
    assert (
        detect_workunit_kind(command="uv run pytest tests/test_x.py -q")
        is WorkUnitKind.TEST_EXECUTION
    )


def test_detects_review_prompt_as_code_review() -> None:
    assert detect_workunit_kind(prompt="Please 审查 this diff") is WorkUnitKind.CODE_REVIEW


def test_detects_patch_prompt_as_patch_candidate() -> None:
    assert detect_workunit_kind(prompt="修复 failing test") is WorkUnitKind.PATCH_CANDIDATE


def test_normalizes_review_fanout_alias() -> None:
    assert normalize_topology("review_fanout") == "fanout_merge"
