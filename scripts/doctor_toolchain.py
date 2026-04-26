#!/usr/bin/env python3
"""Render a small uv/bun/python toolchain doctor report."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class ToolStatus:
    """One tool entry in the doctor report."""

    name: str
    command: str
    ok: bool
    version: str | None
    detail: str


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of plain text.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when required tools are missing or Python is below the minimum.",
    )
    parser.add_argument(
        "--require-bun",
        action="store_true",
        help="Treat Bun as required for strict mode.",
    )
    parser.add_argument(
        "--min-python",
        default="3.11",
        help="Minimum supported Python version for strict mode checks.",
    )
    return parser.parse_args()


def _resolve_command(candidates: list[str]) -> tuple[str | None, str]:
    for candidate in candidates:
        expanded = str(Path(candidate).expanduser())
        if Path(expanded).is_file() and Path(expanded).exists():
            return expanded, expanded
        resolved = shutil.which(candidate)
        if resolved:
            return resolved, candidate
    return None, candidates[0]


def _run_version(candidates: list[str]) -> ToolStatus:
    resolved, display = _resolve_command(candidates)
    if not resolved:
        return ToolStatus(
            name=display.split("/")[-1],
            command=display,
            ok=False,
            version=None,
            detail="not found",
        )

    result = subprocess.run(
        [resolved, "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    output = (result.stdout or result.stderr).strip()
    return ToolStatus(
        name=Path(display).name,
        command=resolved,
        ok=result.returncode == 0,
        version=output or None,
        detail="ok" if result.returncode == 0 else f"exit {result.returncode}",
    )


def _python_status() -> tuple[ToolStatus, tuple[int, int, int]]:
    version_info = sys.version_info[:3]
    executable = Path(sys.executable).resolve()
    version = f"Python {version_info[0]}.{version_info[1]}.{version_info[2]}"
    return (
        ToolStatus(
            name="python",
            command=str(executable),
            ok=True,
            version=version,
            detail="ok",
        ),
        version_info,
    )


def _parse_min_python(raw: str) -> tuple[int, int]:
    pieces = raw.split(".")
    if len(pieces) < 2:
        raise SystemExit(f"Invalid --min-python value: {raw!r}")
    return int(pieces[0]), int(pieces[1])


def _render_text(statuses: list[ToolStatus], min_python: str, strict_failed: bool) -> str:
    lines = ["Toolchain doctor", f"minimum_python: {min_python}"]
    for status in statuses:
        marker = "ok" if status.ok and status.detail == "ok" else "warn"
        if not status.ok:
            marker = "missing"
        version = status.version or "-"
        lines.append(f"{status.name}: {marker} | {version} | {status.detail} | {status.command}")
    lines.append(f"strict_status: {'failed' if strict_failed else 'passed'}")
    return "\n".join(lines)


def main() -> int:
    args = _parse_args()
    python_status, python_version = _python_status()
    uv_status = _run_version(["uv"])
    bun_status = _run_version(["bun", "~/.bun/bin/bun"])
    statuses = [python_status, uv_status, bun_status]

    min_python = _parse_min_python(args.min_python)
    strict_failed = False
    if python_version[:2] < min_python:
        strict_failed = True
        python_status.detail = f"requires >= {args.min_python}"
    if not uv_status.ok:
        strict_failed = True
    if args.require_bun and not bun_status.ok:
        strict_failed = True

    if args.json:
        payload = {
            "minimum_python": args.min_python,
            "strict_status": "failed" if strict_failed else "passed",
            "tools": [asdict(status) for status in statuses],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=True))
    else:
        print(_render_text(statuses, args.min_python, strict_failed))

    if args.strict and strict_failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
