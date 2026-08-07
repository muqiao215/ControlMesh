#!/usr/bin/env python3
"""Generate or check the canonical Python task-lifecycle golden matrix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tests.golden.runners.task_lifecycle import generate_matrix

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tests/golden/fixtures/tasks/lifecycle.matrix.json"


def render() -> str:
    return json.dumps(generate_matrix(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if the committed matrix differs")
    args = parser.parse_args()
    actual = render()
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != actual:
            print(f"task lifecycle golden drift: run {Path(__file__).name}")
            return 1
        print(f"task lifecycle golden matrix is current: {OUTPUT.relative_to(ROOT)}")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(actual, encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
