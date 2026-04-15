"""Tests for Docker extras registry, Dockerfile generation, and CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from controlmesh.config import DockerConfig
from controlmesh.infra.docker_extras import (
    DOCKER_EXTRAS,
    DOCKER_EXTRAS_BY_ID,
    EXTRA_CATEGORIES,
    DockerExtra,
    calculate_build_timeout,
    extras_for_display,
    generate_dockerfile_extras,
    resolve_extras,
)

# ---------------------------------------------------------------------------
# Registry integrity
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_all_ids_unique(self) -> None:
        ids = [e.id for e in DOCKER_EXTRAS]
        assert len(ids) == len(set(ids))

    def test_all_categories_valid(self) -> None:
        for extra in DOCKER_EXTRAS:
            assert extra.category in EXTRA_CATEGORIES, f"{extra.id} has unknown category"

    def test_dependencies_exist(self) -> None:
        for extra in DOCKER_EXTRAS:
            for dep in extra.depends_on:
                assert dep in DOCKER_EXTRAS_BY_ID, f"{extra.id} depends on unknown {dep}"

    def test_no_circular_dependencies(self) -> None:
        """Walk every extra to ensure no cycles."""

        def _walk(eid: str, visited: set[str]) -> None:
            assert eid not in visited, f"Cycle detected at {eid}"
            visited.add(eid)
            extra = DOCKER_EXTRAS_BY_ID.get(eid)
            if extra:
                for dep in extra.depends_on:
                    _walk(dep, visited.copy())

        for extra in DOCKER_EXTRAS:
            _walk(extra.id, set())

    def test_by_id_dict_matches_tuple(self) -> None:
        assert len(DOCKER_EXTRAS_BY_ID) == len(DOCKER_EXTRAS)
        for extra in DOCKER_EXTRAS:
            assert DOCKER_EXTRAS_BY_ID[extra.id] is extra

    def test_extras_for_display_covers_all(self) -> None:
        displayed = {e.id for _, extras in extras_for_display() for e in extras}
        all_ids = {e.id for e in DOCKER_EXTRAS}
        assert displayed == all_ids


# ---------------------------------------------------------------------------
# resolve_extras
# ---------------------------------------------------------------------------


class TestResolveExtras:
    def test_empty_input(self) -> None:
        assert resolve_extras([]) == []

    def test_single_no_deps(self) -> None:
        result = resolve_extras(["ffmpeg"])
        assert len(result) == 1
        assert result[0].id == "ffmpeg"

    def test_includes_transitive_dependencies(self) -> None:
        result = resolve_extras(["whisper"])
        ids = [e.id for e in result]
        assert "ffmpeg" in ids
        assert "whisper" in ids
        assert ids.index("ffmpeg") < ids.index("whisper")

    def test_deep_transitive_dependencies(self) -> None:
        result = resolve_extras(["easyocr"])
        ids = [e.id for e in result]
        assert "pytorch-cpu" in ids
        assert ids.index("pytorch-cpu") < ids.index("easyocr")

    def test_deduplicates(self) -> None:
        result = resolve_extras(["ffmpeg", "whisper"])
        ids = [e.id for e in result]
        assert ids.count("ffmpeg") == 1

    def test_unknown_ids_ignored(self) -> None:
        result = resolve_extras(["nonexistent", "ffmpeg"])
        assert len(result) == 1
        assert result[0].id == "ffmpeg"

    def test_all_unknown(self) -> None:
        assert resolve_extras(["nope", "also_nope"]) == []


# ---------------------------------------------------------------------------
# generate_dockerfile_extras
# ---------------------------------------------------------------------------

_BASE = "FROM ubuntu\nUSER node\n"


class TestGenerateDockerfile:
    def test_empty_extras_returns_base(self) -> None:
        assert generate_dockerfile_extras(_BASE, []) == _BASE

    def test_apt_only(self) -> None:
        extras = [
            DockerExtra(
                id="test",
                name="Test",
                description="d",
                category="Audio / Speech",
                size_estimate="~1 MB",
                apt_packages=["pkg1", "pkg2"],
            )
        ]
        result = generate_dockerfile_extras(_BASE, extras)
        assert "USER root" in result
        assert "apt-get install -y --no-install-recommends" in result
        assert "pkg1" in result
        assert "pkg2" in result
        assert "pip install" not in result
        assert result.rstrip().endswith("USER node")

    def test_pip_only(self) -> None:
        extras = [
            DockerExtra(
                id="test",
                name="Test",
                description="d",
                category="Audio / Speech",
                size_estimate="~1 MB",
                pip_packages=["lib1"],
            )
        ]
        result = generate_dockerfile_extras(_BASE, extras)
        assert "pip install --no-cache-dir lib1" in result
        assert "apt-get" not in result

    def test_mixed_apt_and_pip(self) -> None:
        extras = resolve_extras(["tesseract"])
        result = generate_dockerfile_extras(_BASE, extras)
        assert "tesseract-ocr" in result
        assert "pytesseract" in result

    def test_preserves_base_content(self) -> None:
        extras = resolve_extras(["ffmpeg"])
        result = generate_dockerfile_extras(_BASE, extras)
        assert result.startswith(_BASE.rstrip())

    def test_user_switch(self) -> None:
        extras = resolve_extras(["ffmpeg"])
        result = generate_dockerfile_extras(_BASE, extras)
        lines = result.split("\n")
        # Must have USER root before installs and USER node after.
        root_idx = next(i for i, line in enumerate(lines) if line == "USER root")
        node_idx = next(i for i, line in enumerate(lines) if i > root_idx and line == "USER node")
        assert root_idx < node_idx

    def test_pytorch_separate_index_url(self) -> None:
        extras = resolve_extras(["pytorch-cpu", "pandas"])
        result = generate_dockerfile_extras(_BASE, extras)
        # PyTorch should have --index-url, pandas should not.
        pip_lines = [line for line in result.split("\n") if line.startswith("RUN pip")]
        assert len(pip_lines) == 2
        index_lines = [line for line in pip_lines if "--index-url" in line]
        assert len(index_lines) == 1
        assert "torch" in index_lines[0]
        # Standard PyPI install should use constraints to prevent CUDA upgrades.
        assert "idx-constraints.txt" in result

    def test_no_constraints_without_custom_index(self) -> None:
        extras = resolve_extras(["pandas", "scipy"])
        result = generate_dockerfile_extras(_BASE, extras)
        assert "idx-constraints" not in result

    def test_apt_packages_sorted_deduped(self) -> None:
        extras = [
            DockerExtra(
                id="a",
                name="A",
                description="d",
                category="Audio / Speech",
                size_estimate="~1 MB",
                apt_packages=["zzz", "aaa", "aaa"],
            )
        ]
        result = generate_dockerfile_extras(_BASE, extras)
        assert "aaa zzz" in result


# ---------------------------------------------------------------------------
# calculate_build_timeout
# ---------------------------------------------------------------------------


class TestBuildTimeout:
    def test_base_only(self) -> None:
        assert calculate_build_timeout([]) == 300

    def test_custom_base(self) -> None:
        assert calculate_build_timeout([], base=100) == 100

    def test_with_extras(self) -> None:
        extras = resolve_extras(["whisper"])
        timeout = calculate_build_timeout(extras)
        # whisper (120) + ffmpeg (0)
        assert timeout == 300 + 120


# ---------------------------------------------------------------------------
# DockerConfig extras field
# ---------------------------------------------------------------------------


class TestDockerConfigExtras:
    def test_default_empty(self) -> None:
        cfg = DockerConfig()
        assert cfg.extras == []

    def test_from_dict(self) -> None:
        cfg = DockerConfig(extras=["whisper", "ffmpeg"])
        assert cfg.extras == ["whisper", "ffmpeg"]

    def test_serialization(self) -> None:
        cfg = DockerConfig(extras=["pandas"])
        data = cfg.model_dump()
        assert data["extras"] == ["pandas"]


# ---------------------------------------------------------------------------
# CLI: extras subcommands
# ---------------------------------------------------------------------------


class TestExtrasCliList:
    def test_extras_list_empty(self, tmp_path: Path) -> None:
        from controlmesh.cli_commands.docker import docker_extras_list

        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"docker": {"extras": []}}))

        with patch(
            "controlmesh.cli_commands.docker.docker_read_config",
            return_value=(config_path, json.loads(config_path.read_text())),
        ):
            docker_extras_list()

    def test_extras_list_with_entries(self, tmp_path: Path) -> None:
        from controlmesh.cli_commands.docker import docker_extras_list

        config_path = tmp_path / "config.json"
        data = {"docker": {"extras": ["ffmpeg", "pandas"]}}
        config_path.write_text(json.dumps(data))

        with patch(
            "controlmesh.cli_commands.docker.docker_read_config",
            return_value=(config_path, data),
        ):
            docker_extras_list()


class TestExtrasCliAdd:
    def test_add_stores_in_config(self, tmp_path: Path) -> None:
        from controlmesh.cli_commands.docker import docker_extras_add

        config_path = tmp_path / "config.json"
        data: dict[str, object] = {"docker": {"extras": []}}
        config_path.write_text(json.dumps(data))

        with (
            patch(
                "controlmesh.cli_commands.docker.docker_read_config",
                return_value=(config_path, data),
            ),
            patch("controlmesh.infra.json_store.atomic_json_save") as mock_save,
        ):
            docker_extras_add(["docker", "extras-add", "ffmpeg"])

        mock_save.assert_called_once()
        saved_data = mock_save.call_args[0][1]
        assert "ffmpeg" in saved_data["docker"]["extras"]

    def test_add_resolves_dependencies(self, tmp_path: Path) -> None:
        from controlmesh.cli_commands.docker import docker_extras_add

        config_path = tmp_path / "config.json"
        data: dict[str, object] = {"docker": {"extras": []}}
        config_path.write_text(json.dumps(data))

        with (
            patch(
                "controlmesh.cli_commands.docker.docker_read_config",
                return_value=(config_path, data),
            ),
            patch("controlmesh.infra.json_store.atomic_json_save") as mock_save,
        ):
            docker_extras_add(["docker", "extras-add", "whisper"])

        saved_data = mock_save.call_args[0][1]
        extras = saved_data["docker"]["extras"]
        assert "ffmpeg" in extras
        assert "whisper" in extras

    def test_add_duplicate_noop(self, tmp_path: Path) -> None:
        from controlmesh.cli_commands.docker import docker_extras_add

        config_path = tmp_path / "config.json"
        data: dict[str, object] = {"docker": {"extras": ["ffmpeg"]}}
        config_path.write_text(json.dumps(data))

        with (
            patch(
                "controlmesh.cli_commands.docker.docker_read_config",
                return_value=(config_path, data),
            ),
            patch("controlmesh.infra.json_store.atomic_json_save") as mock_save,
        ):
            docker_extras_add(["docker", "extras-add", "ffmpeg"])

        mock_save.assert_not_called()

    def test_add_unknown_shows_error(self) -> None:
        from controlmesh.cli_commands.docker import docker_extras_add

        # Should not crash, just print error.
        docker_extras_add(["docker", "extras-add", "nonexistent"])


class TestExtrasCliRemove:
    def test_remove_from_config(self, tmp_path: Path) -> None:
        from controlmesh.cli_commands.docker import docker_extras_remove

        config_path = tmp_path / "config.json"
        data: dict[str, object] = {"docker": {"extras": ["ffmpeg", "pandas"]}}
        config_path.write_text(json.dumps(data))

        with (
            patch(
                "controlmesh.cli_commands.docker.docker_read_config",
                return_value=(config_path, data),
            ),
            patch("controlmesh.infra.json_store.atomic_json_save") as mock_save,
        ):
            docker_extras_remove(["docker", "extras-remove", "ffmpeg"])

        saved_data = mock_save.call_args[0][1]
        assert "ffmpeg" not in saved_data["docker"]["extras"]
        assert "pandas" in saved_data["docker"]["extras"]

    def test_remove_not_installed(self, tmp_path: Path) -> None:
        from controlmesh.cli_commands.docker import docker_extras_remove

        config_path = tmp_path / "config.json"
        data: dict[str, object] = {"docker": {"extras": []}}
        config_path.write_text(json.dumps(data))

        with (
            patch(
                "controlmesh.cli_commands.docker.docker_read_config",
                return_value=(config_path, data),
            ),
            patch("controlmesh.infra.json_store.atomic_json_save") as mock_save,
        ):
            docker_extras_remove(["docker", "extras-remove", "ffmpeg"])

        mock_save.assert_not_called()


# ---------------------------------------------------------------------------
# DockerManager build with extras
# ---------------------------------------------------------------------------


def _make_docker_paths(tmp_path: Path) -> tuple[Path, object]:
    """Create ControlMeshPaths and framework dir for Docker manager tests."""
    from controlmesh.workspace.paths import ControlMeshPaths

    home = tmp_path / ".controlmesh"
    home.mkdir()
    (home / "workspace").mkdir()
    (home / "workspace" / "tools").mkdir()
    fw = tmp_path / "framework"
    fw.mkdir()
    paths = ControlMeshPaths(controlmesh_home=home, home_defaults=fw / "workspace", framework_root=fw)
    return fw, paths


class TestDockerManagerExtras:
    async def test_build_image_with_extras(self, tmp_path: Path) -> None:
        from controlmesh.infra.docker import DockerManager

        fw, paths = _make_docker_paths(tmp_path)
        (fw / "Dockerfile.sandbox").write_text("FROM ubuntu\nUSER node\n")

        config = DockerConfig(
            enabled=True,
            image_name="test-img",
            container_name="test-ctr",
            extras=["ffmpeg", "pandas"],
        )
        mgr = DockerManager(config, paths)
        built_content: list[str] = []

        async def mock_exec(*args: str, **_kwargs: object) -> tuple[int, str]:
            cmd = " ".join(args)
            if "docker build" in cmd:
                f_idx = args.index("-f")
                with Path(args[f_idx + 1]).open() as fh:  # noqa: ASYNC230
                    built_content.append(fh.read())
                return 0, "built"
            return 0, ""

        with patch.object(mgr, "_exec_stream", side_effect=mock_exec):
            result = await mgr._build_image("test-img")

        assert result is True
        assert built_content
        assert "ffmpeg" in built_content[0]
        assert "pandas" in built_content[0]
        assert "Docker extras" in built_content[0]

    async def test_build_image_without_extras(self, tmp_path: Path) -> None:
        from controlmesh.infra.docker import DockerManager

        fw, paths = _make_docker_paths(tmp_path)
        base_content = "FROM ubuntu\nUSER node\n"
        (fw / "Dockerfile.sandbox").write_text(base_content)

        config = DockerConfig(enabled=True, image_name="test-img", container_name="test-ctr")
        mgr = DockerManager(config, paths)
        built_content: list[str] = []

        async def mock_exec(*args: str, **_kwargs: object) -> tuple[int, str]:
            cmd = " ".join(args)
            if "docker build" in cmd:
                f_idx = args.index("-f")
                with Path(args[f_idx + 1]).open() as fh:  # noqa: ASYNC230
                    built_content.append(fh.read())
                return 0, "built"
            return 0, ""

        with patch.object(mgr, "_exec_stream", side_effect=mock_exec):
            result = await mgr._build_image("test-img")

        assert result is True
        assert built_content
        assert "Docker extras" not in built_content[0]
        assert built_content[0] == base_content

    async def test_build_timeout_scales_with_extras(self, tmp_path: Path) -> None:
        from controlmesh.infra.docker import DockerManager

        fw, paths = _make_docker_paths(tmp_path)
        (fw / "Dockerfile.sandbox").write_text("FROM ubuntu\nUSER node\n")

        config = DockerConfig(
            enabled=True,
            image_name="test-img",
            container_name="test-ctr",
            extras=["pytorch-cpu"],  # 180s extra
        )
        mgr = DockerManager(config, paths)
        captured_timeout: float | None = None

        async def mock_exec(*args: str, **kwargs: object) -> tuple[int, str]:
            nonlocal captured_timeout
            cmd = " ".join(args)
            if "docker build" in cmd:
                captured_timeout = kwargs.get("deadline_seconds")
                return 0, "built"
            return 0, ""

        with patch.object(mgr, "_exec_stream", side_effect=mock_exec):
            await mgr._build_image("test-img")

        assert captured_timeout == 300 + 180
