from __future__ import annotations

from pathlib import Path

from scripts.doctor_skill_links import _classify_symlink


def test_classify_symlink_loop(tmp_path: Path) -> None:
    loop = tmp_path / "loop"
    loop.symlink_to(loop)

    issue = _classify_symlink(loop)

    assert issue is not None
    assert issue.issue == "symlink_loop"
    assert issue.link_target == str(loop)


def test_classify_broken_symlink(tmp_path: Path) -> None:
    broken = tmp_path / "broken"
    broken.symlink_to(tmp_path / "missing")

    issue = _classify_symlink(broken)

    assert issue is not None
    assert issue.issue == "broken_symlink"
    assert issue.link_target == str(tmp_path / "missing")
