"""Tests for dynamic OpenCode model discovery."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from controlmesh.cli.opencode_discovery import _parse_models, discover_opencode_models


def _make_process_mock(
    *,
    stdout: bytes = b"",
    stderr: bytes = b"",
    returncode: int = 0,
) -> asyncio.subprocess.Process:
    proc = AsyncMock(spec=asyncio.subprocess.Process)
    proc.communicate.return_value = (stdout, stderr)
    proc.returncode = returncode
    return proc


def test_parse_models_filters_invalid_and_deduplicates() -> None:
    raw = (
        "zhipuai/glm-5.1\n"
        "zhipuai/glm-5.1\n"
        "not-a-model\n"
        "\n"
        "anthropic/claude-sonnet-4-5"
    )
    assert _parse_models(raw) == ("zhipuai/glm-5.1", "anthropic/claude-sonnet-4-5")


async def test_discover_opencode_models_for_active_provider() -> None:
    proc = _make_process_mock(
        stdout=b"zhipuai/glm-5.1\nzhipuai/glm-4.5-air\n",
        returncode=0,
    )
    with (
        patch("controlmesh.cli.opencode_discovery.which", return_value="/usr/bin/opencode"),
        patch("controlmesh.cli.opencode_discovery.read_opencode_primary_provider", return_value="zhipuai"),
        patch(
            "controlmesh.cli.opencode_discovery.asyncio.create_subprocess_exec",
            return_value=proc,
        ) as spawn,
    ):
        models = await discover_opencode_models()

    assert models == ("zhipuai/glm-5.1", "zhipuai/glm-4.5-air")
    spawn.assert_awaited_once()
    args = spawn.await_args.args
    assert args[:3] == ("/usr/bin/opencode", "models", "zhipuai")


async def test_discover_opencode_models_without_provider_uses_auto() -> None:
    proc = _make_process_mock(stdout=b"anthropic/claude-sonnet-4-5\n", returncode=0)
    with (
        patch("controlmesh.cli.opencode_discovery.which", return_value="/usr/bin/opencode"),
        patch("controlmesh.cli.opencode_discovery.read_opencode_primary_provider", return_value=""),
        patch(
            "controlmesh.cli.opencode_discovery.asyncio.create_subprocess_exec",
            return_value=proc,
        ) as spawn,
    ):
        models = await discover_opencode_models()

    assert models == ("anthropic/claude-sonnet-4-5",)
    args = spawn.await_args.args
    assert args[:2] == ("/usr/bin/opencode", "models")
    assert len(args) == 2


async def test_discover_opencode_models_returns_empty_on_failure() -> None:
    proc = _make_process_mock(stderr=b"boom", returncode=1)
    with (
        patch("controlmesh.cli.opencode_discovery.which", return_value="/usr/bin/opencode"),
        patch("controlmesh.cli.opencode_discovery.read_opencode_primary_provider", return_value="zhipuai"),
        patch(
            "controlmesh.cli.opencode_discovery.asyncio.create_subprocess_exec",
            return_value=proc,
        ),
    ):
        models = await discover_opencode_models()

    assert models == ()


async def test_discover_opencode_models_returns_empty_when_missing() -> None:
    with patch("controlmesh.cli.opencode_discovery.which", return_value=None):
        models = await discover_opencode_models()

    assert models == ()
