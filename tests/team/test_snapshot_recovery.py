"""Tests for advisory snapshot recovery/read decisions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from controlmesh.team.models import (
    TeamLeader,
    TeamManifest,
    TeamRuntimeContext,
    TeamSessionRef,
    TeamTask,
    TeamWorker,
)
from controlmesh.team.state import TeamStateStore
from controlmesh.team.state.recovery import (
    DEFAULT_RUNTIME_RECOVERY_SNAPSHOT_MAX_AGE_SECONDS,
    TeamControlSnapshotRecoveryAdvisor,
    default_runtime_recovery_snapshot_max_age_seconds,
)
from controlmesh.team.state.snapshot import TeamControlSnapshotManager
from controlmesh.workspace.paths import ControlMeshPaths


def _paths(tmp_path: Path) -> ControlMeshPaths:
    return ControlMeshPaths(
        controlmesh_home=tmp_path / ".controlmesh",
        home_defaults=Path("/opt/controlmesh/workspace"),
        framework_root=Path("/opt/controlmesh"),
    )


def _seed_store(paths: ControlMeshPaths) -> TeamStateStore:
    store = TeamStateStore(paths.team_state_dir, "alpha-team")
    store.write_manifest(
        TeamManifest(
            team_name="alpha-team",
            task_description="Coordinate snapshot recovery advice",
            leader=TeamLeader(
                agent_name="main",
                session=TeamSessionRef(transport="tg", chat_id=7, topic_id=12),
                runtime=TeamRuntimeContext(cwd="/repo"),
            ),
            workers=[
                TeamWorker(name="worker-1", role="executor", provider="codex"),
                TeamWorker(name="worker-2", role="verifier", provider="codex"),
            ],
        )
    )
    return store


def test_recovery_advisor_returns_usable_when_snapshot_is_fresh(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _seed_store(paths)
    manager = TeamControlSnapshotManager(paths)
    manager.write("alpha-team", generated_at="2026-04-10T00:00:00+00:00")
    advisor = TeamControlSnapshotRecoveryAdvisor(paths)

    advice = advisor.evaluate(
        "alpha-team",
        max_age_seconds=300,
        now=datetime(2026, 4, 10, 0, 4, 59, tzinfo=UTC),
    )

    assert advice.status == "usable"
    assert advice.stale is False
    assert advice.snapshot is not None
    assert advice.snapshot.generated_at == "2026-04-10T00:00:00+00:00"
    assert advice.reason is None


def test_default_runtime_recovery_snapshot_max_age_seconds_matches_expected_value() -> None:
    assert DEFAULT_RUNTIME_RECOVERY_SNAPSHOT_MAX_AGE_SECONDS == 60
    assert default_runtime_recovery_snapshot_max_age_seconds() == 60


def test_recovery_advisor_returns_refresh_required_when_snapshot_is_stale(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _seed_store(paths)
    manager = TeamControlSnapshotManager(paths)
    manager.write("alpha-team", generated_at="2026-04-10T00:00:00+00:00")
    advisor = TeamControlSnapshotRecoveryAdvisor(paths)

    first = advisor.evaluate(
        "alpha-team",
        max_age_seconds=300,
        now=datetime(2026, 4, 10, 0, 5, 1, tzinfo=UTC),
    )
    second = advisor.evaluate(
        "alpha-team",
        max_age_seconds=300,
        now=datetime(2026, 4, 10, 0, 5, 1, tzinfo=UTC),
    )

    assert first.status == "refresh_required"
    assert first.stale is True
    assert first.snapshot is not None
    assert first.snapshot.generated_at == "2026-04-10T00:00:00+00:00"
    assert first == second


def test_recovery_advisor_returns_missing_snapshot_when_snapshot_file_absent(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _seed_store(paths)
    advisor = TeamControlSnapshotRecoveryAdvisor(paths)

    advice = advisor.evaluate(
        "alpha-team",
        max_age_seconds=60,
        now=datetime(2026, 4, 10, 0, 1, 0, tzinfo=UTC),
    )

    assert advice.status == "missing_snapshot"
    assert advice.snapshot is None
    assert advice.stale is None
    assert advice.reason is not None


def test_recovery_advisor_returns_invalid_snapshot_for_naive_generated_at(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _seed_store(paths)
    manager = TeamControlSnapshotManager(paths)
    snapshot = manager.write("alpha-team", generated_at="2026-04-10T00:00:00+00:00")
    payload = snapshot.model_dump(mode="json")
    payload["generated_at"] = "2026-04-10T00:00:00"
    manager.path_for("alpha-team").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    advisor = TeamControlSnapshotRecoveryAdvisor(paths)

    advice = advisor.evaluate(
        "alpha-team",
        max_age_seconds=60,
        now=datetime(2026, 4, 10, 0, 1, 0, tzinfo=UTC),
    )

    assert advice.status == "invalid_snapshot"
    assert advice.snapshot is None
    assert advice.stale is None
    assert advice.reason is not None


def test_recovery_advisor_does_not_mutate_canonical_files_for_fresh_snapshot(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    store = _seed_store(paths)
    store.upsert_task(TeamTask(task_id="task-1", subject="Implement feature", status="pending"))
    manager = TeamControlSnapshotManager(paths)
    manager.write("alpha-team", generated_at="2026-04-10T00:00:00+00:00")
    advisor = TeamControlSnapshotRecoveryAdvisor(paths)
    tasks_before = store.paths.tasks_path.read_text(encoding="utf-8")

    advice = advisor.evaluate(
        "alpha-team",
        max_age_seconds=60,
        now=datetime(2026, 4, 10, 0, 0, 30, tzinfo=UTC),
    )
    tasks_after = store.paths.tasks_path.read_text(encoding="utf-8")

    assert advice.status == "usable"
    assert advice.snapshot is not None
    assert tasks_after == tasks_before


def test_refresh_and_evaluate_builds_missing_snapshot_and_returns_usable(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _seed_store(paths)
    advisor = TeamControlSnapshotRecoveryAdvisor(paths)

    with patch(
        "controlmesh.team.state.snapshot.utc_now",
        return_value="2026-04-10T00:01:00+00:00",
    ):
        advice = advisor.refresh_and_evaluate(
            "alpha-team",
            max_age_seconds=60,
            now=datetime(2026, 4, 10, 0, 1, 30, tzinfo=UTC),
        )

    assert advice.status == "usable"
    assert advice.stale is False
    assert advice.snapshot is not None
    assert advice.snapshot.generated_at == "2026-04-10T00:01:30+00:00"
    assert TeamControlSnapshotManager(paths).path_for("alpha-team").exists() is True


def test_refresh_and_evaluate_rewrites_invalid_snapshot_and_returns_usable(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _seed_store(paths)
    manager = TeamControlSnapshotManager(paths)
    snapshot = manager.write("alpha-team", generated_at="2026-04-10T00:00:00+00:00")
    payload = snapshot.model_dump(mode="json")
    payload["generated_at"] = "2026-04-10T00:00:00"
    manager.path_for("alpha-team").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    advisor = TeamControlSnapshotRecoveryAdvisor(paths)

    with patch(
        "controlmesh.team.state.snapshot.utc_now",
        return_value="2026-04-10T00:02:00+00:00",
    ):
        advice = advisor.refresh_and_evaluate(
            "alpha-team",
            max_age_seconds=60,
            now=datetime(2026, 4, 10, 0, 2, 30, tzinfo=UTC),
        )

    assert advice.status == "usable"
    assert advice.stale is False
    assert advice.snapshot is not None
    assert advice.snapshot.generated_at == "2026-04-10T00:02:30+00:00"


def test_refresh_and_evaluate_rewrites_stale_snapshot_and_returns_usable(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _seed_store(paths)
    manager = TeamControlSnapshotManager(paths)
    manager.write("alpha-team", generated_at="2026-04-10T00:00:00+00:00")
    advisor = TeamControlSnapshotRecoveryAdvisor(paths)

    with patch(
        "controlmesh.team.state.snapshot.utc_now",
        return_value="2026-04-10T00:10:00+00:00",
    ):
        advice = advisor.refresh_and_evaluate(
            "alpha-team",
            max_age_seconds=60,
            now=datetime(2026, 4, 10, 0, 10, 30, tzinfo=UTC),
        )

    assert advice.status == "usable"
    assert advice.stale is False
    assert advice.snapshot is not None
    assert advice.snapshot.generated_at == "2026-04-10T00:10:30+00:00"


def test_refresh_and_evaluate_uses_supplied_now_for_refreshed_generated_at(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _seed_store(paths)
    manager = TeamControlSnapshotManager(paths)
    manager.write("alpha-team", generated_at="2026-04-10T00:00:00+00:00")
    advisor = TeamControlSnapshotRecoveryAdvisor(paths)

    advice = advisor.refresh_and_evaluate(
        "alpha-team",
        max_age_seconds=60,
        now=datetime(2030, 1, 1, 0, 0, 0, tzinfo=UTC),
    )

    assert advice.status == "usable"
    assert advice.stale is False
    assert advice.snapshot is not None
    assert advice.snapshot.generated_at == "2030-01-01T00:00:00+00:00"


def test_refresh_and_evaluate_skips_rewrite_for_already_fresh_snapshot(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _seed_store(paths)
    manager = TeamControlSnapshotManager(paths)
    manager.write("alpha-team", generated_at="2026-04-10T00:00:00+00:00")
    advisor = TeamControlSnapshotRecoveryAdvisor(paths)

    with patch.object(advisor._manager, "write", wraps=advisor._manager.write) as write_mock:
        advice = advisor.refresh_and_evaluate(
            "alpha-team",
            max_age_seconds=300,
            now=datetime(2026, 4, 10, 0, 4, 59, tzinfo=UTC),
        )

    assert advice.status == "usable"
    assert advice.stale is False
    assert advice.snapshot is not None
    assert write_mock.call_count == 0


def test_refresh_and_evaluate_does_not_mutate_canonical_files(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    store = _seed_store(paths)
    store.upsert_task(TeamTask(task_id="task-1", subject="Implement feature", status="pending"))
    manager = TeamControlSnapshotManager(paths)
    manager.write("alpha-team", generated_at="2026-04-10T00:00:00+00:00")
    advisor = TeamControlSnapshotRecoveryAdvisor(paths)
    tasks_before = store.paths.tasks_path.read_text(encoding="utf-8")

    with patch(
        "controlmesh.team.state.snapshot.utc_now",
        return_value="2026-04-10T00:10:00+00:00",
    ):
        advice = advisor.refresh_and_evaluate(
            "alpha-team",
            max_age_seconds=60,
            now=datetime(2026, 4, 10, 0, 10, 30, tzinfo=UTC),
        )
    tasks_after = store.paths.tasks_path.read_text(encoding="utf-8")

    assert advice.status == "usable"
    assert advice.snapshot is not None
    assert tasks_after == tasks_before
