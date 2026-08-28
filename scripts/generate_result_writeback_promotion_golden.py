#!/usr/bin/env python3
"""Generate or check the Python result-writeback/promotion golden matrix."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from tests.golden.runners.result_writeback_promotion import generate_matrix
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tests/golden/fixtures/runtime/result-writeback-promotion.matrix.json"
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    actual = json.dumps(generate_matrix(), indent=2, sort_keys=True) + "\n"
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != actual:
            print(f"result writeback/promotion golden drift: run {Path(__file__).name}")
            return 1
        print(f"result writeback/promotion golden matrix is current: {OUTPUT.relative_to(ROOT)}")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(actual, encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)}")
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
