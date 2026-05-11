#!/usr/bin/env python3
"""Report broken or looping skill symlinks across runtime skill roots."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class LinkIssue:
    """One problematic skill symlink."""

    base: str
    name: str
    path: str
    link_target: str | None
    issue: str


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of plain text.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero if any issue is found.")
    return parser.parse_args()


def _skill_roots() -> list[Path]:
    roots = [
        Path.home() / ".claude" / "skills",
        Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "skills",
        Path.home() / ".agents" / "skills",
        Path.home() / ".controlmesh" / "workspace" / "skills",
    ]
    seen: set[Path] = set()
    unique: list[Path] = []
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        unique.append(root)
    return unique


def _classify_symlink(path: Path) -> LinkIssue | None:
    if not path.is_symlink():
        return None
    try:
        target = os.readlink(path)
    except OSError:
        target = None
    try:
        path.resolve()
    except RuntimeError:
        issue = "symlink_loop"
    except OSError:
        issue = "broken_symlink"
    else:
        return None
    return LinkIssue(
        base=str(path.parent),
        name=path.name,
        path=str(path),
        link_target=target,
        issue=issue,
    )


def _collect_issues() -> list[LinkIssue]:
    issues: list[LinkIssue] = []
    for root in _skill_roots():
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            issue = _classify_symlink(entry)
            if issue is not None:
                issues.append(issue)
    return issues


def _render_text(issues: list[LinkIssue]) -> str:
    lines = ["Skill link doctor"]
    if not issues:
        lines.append("status: ok")
        return "\n".join(lines)
    lines.append(f"status: issues={len(issues)}")
    for issue in issues:
        target = issue.link_target or "-"
        lines.append(f"{issue.issue} | {issue.path} -> {target}")
    return "\n".join(lines)


def main() -> int:
    args = _parse_args()
    issues = _collect_issues()
    if args.json:
        payload = {
            "status": "ok" if not issues else "issues",
            "issue_count": len(issues),
            "issues": [asdict(issue) for issue in issues],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=True))
    else:
        print(_render_text(issues))
    if args.strict and issues:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
