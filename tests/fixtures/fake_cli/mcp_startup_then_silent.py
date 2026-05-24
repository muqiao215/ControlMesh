#!/usr/bin/env python3
"""Emit an MCP startup line, then sleep long enough to timeout."""

from __future__ import annotations

import sys
import time

sys.stderr.write("mcp startup: no servers\n")
sys.stderr.flush()
time.sleep(5)
