"""Security tests for the unregistered MW-006 artifact safe-open primitive."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from controlmesh.api import artifact_access
from controlmesh.api.admin_read import AdminHistoryCatalogReader
from controlmesh.api.artifact_access import (
    ArtifactNotFoundError,
    InvalidArtifactPathError,
    open_task_artifact,
    validate_artifact_relative_path,
)
from controlmesh.tasks.models import TaskSubmit
from controlmesh.tasks.registry import TaskRegistry
from controlmesh.workspace.paths import ControlMeshPaths

SAFE_OPEN_SECURITY_CASE_TESTS = {
    "AD-PATH-001": "test_safe_open_rejects_invalid_public_paths",
    "AD-PATH-002": "test_safe_open_rejects_invalid_public_paths",
    "AD-PATH-003": "test_safe_open_rejects_invalid_public_paths",
    "AD-PATH-004": "test_safe_open_rejects_invalid_public_paths",
    "AD-PATH-005": "test_safe_open_rejects_invalid_public_paths",
    "AD-TASK-001": "test_safe_open_returns_generic_not_found_for_missing_task",
    "AD-DIR-001": "test_safe_open_reads_allowlisted_file_from_custom_tasks_dir",
    "AD-ALLOW-001": "test_safe_open_reads_allowlisted_file_from_custom_tasks_dir",
    "AD-ALLOW-002": "test_safe_open_requires_exact_metadata_allowlist_match",
    "AD-ALLOW-003": "test_safe_open_rejects_directory",
    "AD-SYMLINK-001": "test_safe_open_rejects_symlink_escape",
    "AD-SYMLINK-002": "test_safe_open_rejects_symlink_escape",
    "AD-SYMLINK-003": "test_safe_open_blocks_symlink_replacement_after_allowlist",
    "AD-FILE-001": "test_safe_open_handles_file_removed_after_allowlist",
    "AD-FILE-002": "test_safe_open_rejects_unreadable_file",
    "AD-MIME-001": "test_safe_open_reads_allowlisted_file_from_custom_tasks_dir",
}


def _task_fixture(tmp_path: Path, *, custom_tasks_dir: bool = False):
    paths = ControlMeshPaths(
        controlmesh_home=tmp_path / ".controlmesh",
        home_defaults=Path("/opt/controlmesh/workspace"),
        framework_root=Path("/opt/controlmesh"),
    )
    registry = TaskRegistry(paths.tasks_registry_path, paths.tasks_dir)
    tasks_dir = tmp_path / "agents" / "reviewer" / "tasks" if custom_tasks_dir else None
    entry = registry.create(
        TaskSubmit(
            chat_id=1,
            prompt="artifact access test",
            message_id=1,
            thread_id=None,
            parent_agent="reviewer" if custom_tasks_dir else "main",
            name="Artifact Access",
        ),
        "codex",
        "gpt-5.2",
        tasks_dir=tasks_dir,
    )
    return AdminHistoryCatalogReader(paths), entry.task_id, registry.task_folder(entry.task_id)


def test_safe_open_security_case_links_resolve_to_tests() -> None:
    assert all(callable(globals().get(test_name)) for test_name in SAFE_OPEN_SECURITY_CASE_TESTS.values())


@pytest.mark.parametrize(
    "raw_path",
    [
        "",
        "/etc/passwd",
        "file:///etc/passwd",
        "C:/Windows/win.ini",
        "\\\\server\\share\\secret.txt",
        "nested\\secret.txt",
        "../secret.txt",
        "nested/../secret.txt",
        "nested//secret.txt",
        "nested/./secret.txt",
        "bad\x00name.txt",
        "bad\nname.txt",
    ],
)
def test_safe_open_rejects_invalid_public_paths(raw_path: str) -> None:
    with pytest.raises(InvalidArtifactPathError, match=r"^artifact path is invalid$"):
        validate_artifact_relative_path(raw_path)


def test_safe_open_reads_allowlisted_file_from_custom_tasks_dir(tmp_path: Path) -> None:
    reader, task_id, task_folder = _task_fixture(tmp_path, custom_tasks_dir=True)
    artifact = task_folder / "reports" / "summary.txt"
    artifact.parent.mkdir()
    artifact.write_text("safe content", encoding="utf-8")

    with open_task_artifact(reader, task_id, "reports/summary.txt") as opened:
        assert opened.stream.read() == b"safe content"
        assert opened.relative_path == "reports/summary.txt"
        assert opened.name == "summary.txt"
        assert opened.mime == "text/plain"
        assert opened.size == len(b"safe content")
        assert str(tmp_path) not in repr(opened)

    assert opened.stream.closed


def test_safe_open_returns_generic_not_found_for_missing_task(tmp_path: Path) -> None:
    reader, _task_id, _task_folder = _task_fixture(tmp_path)

    with (
        pytest.raises(ArtifactNotFoundError, match=r"^artifact not found$") as exc_info,
        open_task_artifact(reader, "missing-task", "RESULT.md"),
    ):
        pass

    assert str(tmp_path) not in str(exc_info.value)


def test_safe_open_requires_exact_metadata_allowlist_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader, task_id, task_folder = _task_fixture(tmp_path)
    artifact = task_folder / "report.txt"
    artifact.write_text("not allowlisted", encoding="utf-8")
    monkeypatch.setattr(artifact_access, "task_artifact_to_protocol", lambda *_args: None)

    with (
        pytest.raises(ArtifactNotFoundError, match=r"^artifact not found$"),
        open_task_artifact(reader, task_id, "report.txt"),
    ):
        pass


def test_safe_open_rejects_directory(tmp_path: Path) -> None:
    reader, task_id, task_folder = _task_fixture(tmp_path)
    (task_folder / "reports").mkdir()

    with (
        pytest.raises(ArtifactNotFoundError, match=r"^artifact not found$"),
        open_task_artifact(reader, task_id, "reports"),
    ):
        pass


@pytest.mark.parametrize("link_parent", [False, True], ids=["final-symlink", "parent-symlink"])
def test_safe_open_rejects_symlink_escape(tmp_path: Path, link_parent: bool) -> None:
    reader, task_id, task_folder = _task_fixture(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    if link_parent:
        (task_folder / "linked").symlink_to(outside, target_is_directory=True)
        relative_path = "linked/secret.txt"
    else:
        (task_folder / "secret.txt").symlink_to(outside / "secret.txt")
        relative_path = "secret.txt"

    with (
        pytest.raises(ArtifactNotFoundError, match=r"^artifact not found$"),
        open_task_artifact(reader, task_id, relative_path),
    ):
        pass


@pytest.mark.parametrize("replace_parent", [False, True], ids=["final-swap", "parent-swap"])
def test_safe_open_blocks_symlink_replacement_after_allowlist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replace_parent: bool,
) -> None:
    reader, task_id, task_folder = _task_fixture(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    parent = task_folder / "reports"
    parent.mkdir()
    artifact = parent / "report.txt"
    artifact.write_text("safe", encoding="utf-8")
    real_adapter = artifact_access.task_artifact_to_protocol

    def replace_after_allowlist(*args):
        metadata = real_adapter(*args)
        if replace_parent:
            shutil.rmtree(parent)
            parent.symlink_to(outside, target_is_directory=True)
        else:
            artifact.unlink()
            artifact.symlink_to(outside / "secret.txt")
        return metadata

    monkeypatch.setattr(artifact_access, "task_artifact_to_protocol", replace_after_allowlist)

    with (
        pytest.raises(ArtifactNotFoundError, match=r"^artifact not found$"),
        open_task_artifact(reader, task_id, "reports/report.txt"),
    ):
        pass


def test_safe_open_handles_file_removed_after_allowlist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader, task_id, task_folder = _task_fixture(tmp_path)
    artifact = task_folder / "vanishing.txt"
    artifact.write_text("temporary", encoding="utf-8")
    real_adapter = artifact_access.task_artifact_to_protocol

    def remove_after_allowlist(*args):
        metadata = real_adapter(*args)
        artifact.unlink()
        return metadata

    monkeypatch.setattr(artifact_access, "task_artifact_to_protocol", remove_after_allowlist)

    with (
        pytest.raises(ArtifactNotFoundError, match=r"^artifact not found$"),
        open_task_artifact(reader, task_id, "vanishing.txt"),
    ):
        pass


def test_safe_open_rejects_unreadable_file(tmp_path: Path) -> None:
    reader, task_id, task_folder = _task_fixture(tmp_path)
    artifact = task_folder / "unreadable.bin"
    artifact.write_bytes(b"private")
    artifact.chmod(0)
    try:
        with (
            pytest.raises(ArtifactNotFoundError, match=r"^artifact not found$"),
            open_task_artifact(reader, task_id, "unreadable.bin"),
        ):
            pass
    finally:
        artifact.chmod(0o600)
