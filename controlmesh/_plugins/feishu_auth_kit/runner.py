"""Module runner for ControlMesh's bundled feishu-auth-kit plugin."""

from __future__ import annotations

import sys

from .feishu_auth_kit.cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
