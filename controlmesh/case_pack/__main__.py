from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from controlmesh.case_pack.io import load_case_pack
from controlmesh.case_pack.lint import CasePackLintError, lint_case_pack_path
from controlmesh.case_pack.render import render_lifted_markdown, render_timeline_markdown


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m controlmesh.case_pack")
    subparsers = parser.add_subparsers(dest="command", required=True)

    lint_parser = subparsers.add_parser("lint", help="Validate case-pack schema and semantics.")
    lint_parser.add_argument("case_path", type=Path)

    render_parser = subparsers.add_parser("render", help="Render derived markdown views.")
    render_parser.add_argument("case_path", type=Path)
    render_parser.add_argument("--timeline-out", type=Path, required=True)
    render_parser.add_argument("--lifted-out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "lint":
        return _run_lint(args)
    if args.command == "render":
        return _run_render(args)
    parser.error(f"unsupported command: {args.command}")
    return 2


def _run_lint(args: Any) -> int:
    try:
        lint_case_pack_path(args.case_path, raise_on_error=True)
    except CasePackLintError as exc:
        print("FAIL case-pack lint")
        print(exc)
        return 1
    print(f"PASS case-pack lint: {args.case_path}")
    return 0


def _run_render(args: Any) -> int:
    case_pack = load_case_pack(args.case_path)
    args.timeline_out.write_text(render_timeline_markdown(case_pack), encoding="utf-8")
    args.lifted_out.write_text(render_lifted_markdown(case_pack), encoding="utf-8")
    print(f"WROTE {args.timeline_out}")
    print(f"WROTE {args.lifted_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
