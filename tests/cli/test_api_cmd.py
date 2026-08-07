"""Tests for the standalone read-only API command."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from controlmesh.cli_commands.api_cmd import (
    _parse_api_subcommand,
    _parse_serve_options,
    _serve_read_only,
    api_serve,
    cmd_api,
)


def test_parse_api_serve_subcommand_and_options() -> None:
    args = ["api", "serve", "--port", "8877", "--token", "test-token"]

    options = _parse_serve_options(args)

    assert _parse_api_subcommand(args) == "serve"
    assert options.host == "127.0.0.1"
    assert options.port == 8877
    assert options.token == "test-token"


async def test_read_only_server_rejects_non_loopback_host() -> None:
    options = _parse_serve_options(["api", "serve", "--host", "192.0.2.1"])

    with pytest.raises(SystemExit, match=r"must bind to 127\.0\.0\.1"):
        await _serve_read_only(options)


def test_api_serve_runs_async_server() -> None:
    with patch(
        "controlmesh.cli_commands.api_cmd._serve_read_only",
        new=AsyncMock(),
    ) as serve:
        api_serve(["api", "serve", "--port", "8877"])

    serve.assert_awaited_once()
    assert serve.await_args.args[0].port == 8877


def test_cmd_api_dispatches_serve() -> None:
    with patch("controlmesh.cli_commands.api_cmd.api_serve") as serve:
        cmd_api(["api", "serve", "--port", "8877"])

    serve.assert_called_once_with(["api", "serve", "--port", "8877"])
