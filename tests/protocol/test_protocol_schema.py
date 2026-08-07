"""Protocol schema safety checks for the TypeScript migration boundary."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "schemas" / "controlmesh" / "v1"
GENERATED_TYPES = REPO_ROOT / "packages" / "controlmesh-protocol" / "src" / "generated" / "types.ts"
GENERATED_PYTHON = REPO_ROOT / "controlmesh" / "protocol" / "generated" / "models.py"

REQUIRED_SCHEMA_FILES = {
    "agent-event.schema.json",
    "artifact.schema.json",
    "ask-parent-response.schema.json",
    "ask-parent.schema.json",
    "config.schema.json",
    "doctor-result.schema.json",
    "error.schema.json",
    "log-event.schema.json",
    "memory-record.schema.json",
    "provider-capability.schema.json",
    "provider-event.schema.json",
    "runtime-event.schema.json",
    "task-event.schema.json",
    "task-state.schema.json",
    "task.schema.json",
    "topology.schema.json",
    "transport-message.schema.json",
    "workspace-manifest.schema.json",
}


def _load_schema(name: str) -> dict[str, object]:
    return json.loads((SCHEMA_DIR / name).read_text())


def test_phase_b_protocol_schema_set_is_present() -> None:
    actual = {path.name for path in SCHEMA_DIR.glob("*.schema.json")}
    assert actual >= REQUIRED_SCHEMA_FILES


def test_object_schemas_preserve_unknown_fields() -> None:
    for schema_name in REQUIRED_SCHEMA_FILES - {"task-state.schema.json"}:
        schema = _load_schema(schema_name)
        assert schema["additionalProperties"] is True, schema_name


def test_task_state_schema_preserves_existing_runtime_states() -> None:
    schema = _load_schema("task-state.schema.json")

    assert set(schema["enum"]) >= {
        "running",
        "done",
        "failed",
        "cancelled",
        "waiting",
        "detached",
        "recovering",
        "stale",
    }


def test_task_schema_keeps_runtime_boundary_fields() -> None:
    schema = _load_schema("task.schema.json")
    properties = schema["properties"]

    for field in (
        "schema_version",
        "task_id",
        "chat_id",
        "thread_id",
        "parent_agent",
        "provider",
        "model",
        "status",
        "session_id",
        "created_at",
        "completed_at",
        "elapsed_seconds",
        "result_preview",
        "last_question",
    ):
        assert field in properties

    assert schema["additionalProperties"] is True


def test_generated_types_are_in_sync() -> None:
    before = GENERATED_TYPES.read_text()

    subprocess.run(["pnpm", "generate:protocol"], cwd=REPO_ROOT, check=True)

    assert GENERATED_TYPES.read_text() == before


def test_generated_python_models_are_in_sync() -> None:
    before = GENERATED_PYTHON.read_text()

    subprocess.run(["uv", "run", "python", "scripts/generate_protocol.py"], cwd=REPO_ROOT, check=True)

    assert GENERATED_PYTHON.read_text() == before
