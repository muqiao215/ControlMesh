"""Tests for cli/gemini_utils.py: shared Gemini utilities."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from controlmesh.cli.gemini_utils import (
    create_system_prompt_file,
    discover_gemini_models,
    find_gemini_cli,
    find_gemini_cli_js,
    trust_workspace,
)


class TestFindGeminiCli:
    def test_found(self) -> None:
        with patch("controlmesh.cli.gemini_utils.which", return_value="/usr/bin/gemini"):
            assert find_gemini_cli() == "/usr/bin/gemini"

    def test_found_via_nvm_fallback(self, tmp_path: Path) -> None:
        gemini = tmp_path / ".nvm" / "versions" / "node" / "v22.0.0" / "bin" / "gemini"
        gemini.parent.mkdir(parents=True)
        gemini.write_text("#!/usr/bin/env node\n")

        with (
            patch("controlmesh.cli.gemini_utils.which", return_value=None),
            patch("controlmesh.cli.gemini_utils.Path.home", return_value=tmp_path),
        ):
            assert find_gemini_cli() == str(gemini)

    def test_not_found_raises(self, tmp_path: Path) -> None:
        with (
            patch("controlmesh.cli.gemini_utils.which", return_value=None),
            patch("controlmesh.cli.gemini_utils.Path.home", return_value=tmp_path),
            pytest.raises(FileNotFoundError, match="gemini CLI not found"),
        ):
            find_gemini_cli()

    def test_found_via_windows_appdata_fallback(self, tmp_path: Path) -> None:
        gemini = tmp_path / "AppData" / "Roaming" / "npm" / "gemini.cmd"
        gemini.parent.mkdir(parents=True)
        gemini.write_text("@echo off\n")

        with (
            patch("controlmesh.cli.gemini_utils.which", return_value=None),
            patch("controlmesh.cli.gemini_utils.Path.home", return_value=tmp_path),
            patch("controlmesh.cli.gemini_utils.is_windows", return_value=True),
            patch.dict(
                "os.environ", {"APPDATA": str(tmp_path / "AppData" / "Roaming")}, clear=False
            ),
        ):
            assert find_gemini_cli() == str(gemini)


class TestFindGeminiCliJs:
    def test_found(self, tmp_path: Path) -> None:
        index_js = tmp_path / "@google" / "gemini-cli" / "dist" / "index.js"
        index_js.parent.mkdir(parents=True)
        index_js.write_text("// entry")

        with (
            patch("controlmesh.cli.gemini_utils.which", return_value="/usr/bin/npm"),
            patch(
                "controlmesh.cli.gemini_utils.subprocess.check_output",
                return_value=str(tmp_path),
            ),
        ):
            result = find_gemini_cli_js()
            assert result == str(index_js)

    def test_not_found_no_npm(self, tmp_path: Path) -> None:
        with (
            patch("controlmesh.cli.gemini_utils.which", return_value=None),
            patch("controlmesh.cli.gemini_utils.Path.home", return_value=tmp_path),
        ):
            assert find_gemini_cli_js() is None

    def test_not_found_no_file(self, tmp_path: Path) -> None:
        with (
            patch("controlmesh.cli.gemini_utils.which", return_value="/usr/bin/npm"),
            patch(
                "controlmesh.cli.gemini_utils.subprocess.check_output",
                return_value=str(tmp_path),
            ),
        ):
            assert find_gemini_cli_js() is None

    def test_found_from_cli_path_fallback(self, tmp_path: Path) -> None:
        cli = tmp_path / ".nvm" / "versions" / "node" / "v22.0.0" / "bin" / "gemini"
        cli.parent.mkdir(parents=True)
        cli.write_text("#!/usr/bin/env node\n")

        index_js = (
            tmp_path
            / ".nvm"
            / "versions"
            / "node"
            / "v22.0.0"
            / "lib"
            / "node_modules"
            / "@google"
            / "gemini-cli"
            / "dist"
            / "index.js"
        )
        index_js.parent.mkdir(parents=True)
        index_js.write_text("// entry")

        with (
            patch("controlmesh.cli.gemini_utils.which", return_value=None),
            patch("controlmesh.cli.gemini_utils.Path.home", return_value=tmp_path),
        ):
            assert find_gemini_cli_js() == str(index_js)

    def test_found_from_windows_npm_layout(self, tmp_path: Path) -> None:
        appdata = tmp_path / "AppData" / "Roaming"
        cli = appdata / "npm" / "gemini.cmd"
        cli.parent.mkdir(parents=True)
        cli.write_text("@echo off\n")

        index_js = appdata / "npm" / "node_modules" / "@google" / "gemini-cli" / "dist" / "index.js"
        index_js.parent.mkdir(parents=True)
        index_js.write_text("// entry")

        with (
            patch("controlmesh.cli.gemini_utils.which", return_value=None),
            patch("controlmesh.cli.gemini_utils.Path.home", return_value=tmp_path),
            patch("controlmesh.cli.gemini_utils.is_windows", return_value=True),
            patch.dict("os.environ", {"APPDATA": str(appdata)}, clear=False),
        ):
            assert find_gemini_cli_js() == str(index_js)


class TestDiscoverGeminiModels:
    def test_from_file(self, tmp_path: Path) -> None:
        models_js = (
            tmp_path
            / "@google"
            / "gemini-cli"
            / "node_modules"
            / "@google"
            / "gemini-cli-core"
            / "dist"
            / "src"
            / "config"
            / "models.js"
        )
        models_js.parent.mkdir(parents=True)
        models_js.write_text(
            "const VALID = new Set(['gemini-2.5-pro', 'gemini-2.5-flash', 'gemini-test-1']);"
        )

        with (
            patch("controlmesh.cli.gemini_utils.which", return_value="/usr/bin/npm"),
            patch(
                "controlmesh.cli.gemini_utils.subprocess.check_output",
                return_value=str(tmp_path),
            ),
        ):
            result = discover_gemini_models()
            assert "gemini-2.5-pro" in result
            assert "gemini-2.5-flash" in result
            assert "gemini-test-1" in result

    def test_fallback_when_no_npm(self, tmp_path: Path) -> None:
        with (
            patch("controlmesh.cli.gemini_utils.which", return_value=None),
            patch("controlmesh.cli.gemini_utils.Path.home", return_value=tmp_path),
        ):
            result = discover_gemini_models()
            assert result == frozenset()

    def test_fallback_when_no_file(self, tmp_path: Path) -> None:
        with (
            patch("controlmesh.cli.gemini_utils.which", return_value="/usr/bin/npm"),
            patch(
                "controlmesh.cli.gemini_utils.subprocess.check_output",
                return_value=str(tmp_path),
            ),
        ):
            result = discover_gemini_models()
            assert result == frozenset()


class TestTrustWorkspace:
    def test_creates_file(self, tmp_path: Path) -> None:
        gemini_home = tmp_path / ".gemini"
        trust_file = gemini_home / "trustedFolders.json"

        with patch("controlmesh.cli.gemini_utils.Path.home", return_value=tmp_path):
            trust_workspace(tmp_path / "workspace")

        assert trust_file.exists()
        data = json.loads(trust_file.read_text())
        assert str(tmp_path / "workspace") in data

    def test_appends_existing(self, tmp_path: Path) -> None:
        gemini_home = tmp_path / ".gemini"
        gemini_home.mkdir()
        trust_file = gemini_home / "trustedFolders.json"
        trust_file.write_text(json.dumps({"/existing": "TRUST_FOLDER"}))

        with patch("controlmesh.cli.gemini_utils.Path.home", return_value=tmp_path):
            trust_workspace(tmp_path / "new_workspace")

        data = json.loads(trust_file.read_text())
        assert "/existing" in data
        assert str(tmp_path / "new_workspace") in data

    def test_skips_if_already_trusted(self, tmp_path: Path) -> None:
        gemini_home = tmp_path / ".gemini"
        gemini_home.mkdir()
        trust_file = gemini_home / "trustedFolders.json"
        ws_path = str(tmp_path / "workspace")
        trust_file.write_text(json.dumps({ws_path: "TRUST_FOLDER"}))

        with patch("controlmesh.cli.gemini_utils.Path.home", return_value=tmp_path):
            trust_workspace(tmp_path / "workspace")

        data = json.loads(trust_file.read_text())
        assert len(data) == 1


class TestCreateSystemPromptFile:
    def test_creates_file(self) -> None:
        path = create_system_prompt_file("You are a helpful assistant.")
        try:
            content = Path(path).read_text()
            assert "You are a helpful assistant." in content
        finally:
            Path(path).unlink(missing_ok=True)

    def test_appends_extra(self) -> None:
        path = create_system_prompt_file("Base prompt", "Extra context")
        try:
            content = Path(path).read_text()
            assert "Base prompt" in content
            assert "Extra context" in content
        finally:
            Path(path).unlink(missing_ok=True)
