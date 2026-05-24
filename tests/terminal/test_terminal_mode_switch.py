from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from controlmesh.config import AgentConfig
from controlmesh.terminal.enhanced_shell import EnhancedShell


@pytest.mark.asyncio
async def test_enter_native_runs_native_session() -> None:
    runtime = type("Runtime", (), {"provider": "codex"})()
    shell = EnhancedShell(runtime=runtime, config=AgentConfig())
    native = AsyncMock()

    with patch("controlmesh.terminal.enhanced_shell.NativePTYSession", return_value=native):
        await shell.enter_native()

    native.run.assert_awaited_once()
