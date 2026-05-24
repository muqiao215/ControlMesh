#!/usr/bin/env python3
"""Emit one JSONL init event and then sleep."""

from __future__ import annotations

import json
import sys
import time

print(json.dumps({"type": "system", "subtype": "init", "session_id": "fake-1"}), flush=True)
sys.stderr.flush()
time.sleep(5)
