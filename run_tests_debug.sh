#!/usr/bin/env bash
# Runs each test file individually and logs which one causes the session crash.
# Output goes to both terminal AND a persistent log file.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$SCRIPT_DIR/test_crash_debug.txt"
echo "=== Test debug run started at $(date) ===" | tee "$LOG"
echo "Log file: $LOG"
echo ""

cd "$(dirname "$0")"
source .venv/bin/activate

# Collect all test files
mapfile -t TEST_FILES < <(find tests -name 'test_*.py' -type f | sort)

echo "Found ${#TEST_FILES[@]} test files" | tee -a "$LOG"
echo "==========================================" | tee -a "$LOG"

for f in "${TEST_FILES[@]}"; do
    echo "" | tee -a "$LOG"
    echo ">>> STARTING: $f ($(date +%H:%M:%S))" | tee -a "$LOG"
    sync  # flush to disk before running, in case session dies

    if pytest "$f" -x -q --tb=no 2>&1 | tee -a "$LOG"; then
        echo "<<< PASSED:  $f" | tee -a "$LOG"
    else
        echo "<<< FAILED:  $f (exit=$?)" | tee -a "$LOG"
    fi

    sync  # flush after each test file
done

echo "" | tee -a "$LOG"
echo "=== All test files completed at $(date) ===" | tee -a "$LOG"
echo "Full log: $LOG"
