from __future__ import annotations

from pathlib import Path

from controlmesh.case_pack.__main__ import main

EXAMPLES_ROOT = Path(__file__).resolve().parents[2] / "examples" / "case-pack"


def test_cli_lint_returns_zero_for_official_example(capsys) -> None:
    exit_code = main(["lint", str(EXAMPLES_ROOT / "minimal" / "case.json")])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS" in captured.out


def test_cli_render_writes_two_views(tmp_path: Path) -> None:
    case_path = EXAMPLES_ROOT / "minimal" / "case.json"
    timeline_out = tmp_path / "timeline.md"
    lifted_out = tmp_path / "lifted.md"

    exit_code = main(
        [
            "render",
            str(case_path),
            "--timeline-out",
            str(timeline_out),
            "--lifted-out",
            str(lifted_out),
        ]
    )

    assert exit_code == 0
    assert timeline_out.read_text(encoding="utf-8").startswith("# Minimal Case")
    assert lifted_out.read_text(encoding="utf-8").startswith("# Minimal Case")
