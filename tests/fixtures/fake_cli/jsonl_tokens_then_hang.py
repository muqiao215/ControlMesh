#!/usr/bin/env python3
"""Emit JSONL assistant text and then sleep."""

from __future__ import annotations

import json
import time

print(
    json.dumps(
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "hello"}]},
        }
    ),
    flush=True,
)
time.sleep(5)
