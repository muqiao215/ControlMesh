#!/usr/bin/env python3
"""Write stderr and exit 1."""

from __future__ import annotations

import sys

sys.stderr.write("fatal auth\n")
sys.stderr.flush()
sys.exit(1)
