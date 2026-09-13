"""Hermetic checks for the bounded CI Docker readiness helper.

The helper exists because run 34750299686 (SHA 93fb734) failed a container test
when a read-only `docker info` preflight reported `container_engine_unavailable`
after the production 10s supervisor timeout, while the following container tests
passed. Readiness may retry within a bound, but a still-unavailable engine must
remain a CI failure: the container gates are never allowed to pass on absence.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

HELPER = (
    Path(__file__).resolve().parents[2] / ".github" / "scripts" / "docker-readiness.sh"
)


def _fake_docker(tmp_path: Path, body: str) -> str:
    script = tmp_path / "fake-docker"
    script.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    script.chmod(0o755)
    return str(script)


def _run(docker_bin: str, **overrides: str) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": "/usr/bin:/bin",
        "CM_CI_DOCKER_BIN": docker_bin,
        "CM_CI_READY_ATTEMPTS": "3",
        "CM_CI_READY_TIMEOUT": "1",
        "CM_CI_READY_BUDGET": "4",
        "CM_CI_READY_SLEEP": "1",
        **overrides,
    }
    return subprocess.run(
        ["bash", str(HELPER)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_readiness_fails_closed_when_engine_stays_unavailable(tmp_path: Path) -> None:
    docker_bin = _fake_docker(tmp_path, 'echo "Cannot connect to the Docker daemon" >&2\nexit 1\n')

    started = time.monotonic()
    result = _run(docker_bin)
    elapsed = time.monotonic() - started

    assert result.returncode == 1
    assert "docker-readiness: engine unavailable" in result.stdout
    assert "Cannot connect to the Docker daemon" in result.stdout
    assert elapsed < 20, f"readiness exceeded its bound: {elapsed:.1f}s"


def test_readiness_accepts_an_available_engine(tmp_path: Path) -> None:
    docker_bin = _fake_docker(tmp_path, "echo 'ENGINEID123 linux'\n")

    result = _run(docker_bin)

    assert result.returncode == 0
    assert "docker-readiness: ready" in result.stdout
    assert "ENGINEID123 linux" in result.stdout


@pytest.mark.parametrize("body", ["exec sleep 30\n", "exit 0\n"])
def test_readiness_rejects_hung_and_empty_engines(tmp_path: Path, body: str) -> None:
    """A timed-out probe is indistinguishable from an absent engine: both fail closed."""
    docker_bin = _fake_docker(tmp_path, body)

    result = _run(docker_bin, CM_CI_READY_ATTEMPTS="1", CM_CI_READY_TIMEOUT="1")

    assert result.returncode == 1
    assert "engine remained unavailable" in result.stdout


def test_diagnose_mode_never_fails_the_job(tmp_path: Path) -> None:
    docker_bin = _fake_docker(tmp_path, "exit 1\n")

    result = subprocess.run(
        ["bash", str(HELPER), "--diagnose"],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "CM_CI_DOCKER_BIN": docker_bin},
        check=False,
    )

    assert result.returncode == 0
    assert "docker-readiness: diagnose snapshot" in result.stdout
