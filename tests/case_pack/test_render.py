from __future__ import annotations

from pathlib import Path

from controlmesh.case_pack.io import load_case_pack
from controlmesh.case_pack.render import render_lifted_markdown, render_timeline_markdown

EXAMPLES_ROOT = Path(__file__).resolve().parents[2] / "examples" / "case-pack"


def test_minimal_case_renders_expected_views() -> None:
    case_pack = load_case_pack(EXAMPLES_ROOT / "minimal" / "case.json")

    timeline = render_timeline_markdown(case_pack)
    lifted = render_lifted_markdown(case_pack)

    expected_timeline = (EXAMPLES_ROOT / "minimal" / "expected-timeline.md").read_text(
        encoding="utf-8"
    )
    expected_lifted = (EXAMPLES_ROOT / "minimal" / "expected-lifted.md").read_text(
        encoding="utf-8"
    )

    assert timeline == expected_timeline
    assert lifted == expected_lifted


def test_real_case_renders_expected_views() -> None:
    case_pack = load_case_pack(EXAMPLES_ROOT / "public-repo-release-gate" / "case.json")

    timeline = render_timeline_markdown(case_pack)
    lifted = render_lifted_markdown(case_pack)

    expected_timeline = (
        EXAMPLES_ROOT / "public-repo-release-gate" / "expected-timeline.md"
    ).read_text(encoding="utf-8")
    expected_lifted = (EXAMPLES_ROOT / "public-repo-release-gate" / "expected-lifted.md").read_text(
        encoding="utf-8"
    )

    assert timeline == expected_timeline
    assert lifted == expected_lifted
