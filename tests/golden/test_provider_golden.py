"""Golden provider outcomes and event ordering from the Python supervisor."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from controlmesh.cli.supervisor import ProviderRunSupervisor
from controlmesh.cli.types import AgentRequest, CLIResponse

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "providers"


class _FakeProvider:
    def __init__(self, behavior: str) -> None:
        self.behavior = behavior

    async def send(self, **_kwargs: object) -> CLIResponse:
        if self.behavior == "timeout":
            raise TimeoutError
        if self.behavior == "error":
            raise RuntimeError("fake provider failure")
        return CLIResponse(result="fake success", returncode=0)


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / f"fake.{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("behavior", ["success", "timeout", "error"])
async def test_python_provider_reference_matches_golden_fixture(behavior: str) -> None:
    fixture = _load_fixture(behavior)
    supervisor = ProviderRunSupervisor("Fake")
    supervisor.started(pid=123, command=("fake",))

    response = await supervisor.run_oneshot(
        _FakeProvider(behavior),
        AgentRequest(prompt=fixture["input"]["prompt"]),
    )

    actual_response = response.model_dump(mode="json")
    for key, expected in fixture["expected"]["response"].items():
        assert actual_response[key] == expected
    if expected_fragment := fixture["expected"].get("result_contains"):
        assert expected_fragment in response.result
    assert [event.kind for event in supervisor.events] == fixture["expected"]["event_kinds"]
