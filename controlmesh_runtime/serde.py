"""Serialization helpers for the ControlMesh runtime store."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


class StoreDecodeError(ValueError):
    """Raised when persisted runtime state cannot be decoded safely."""


def _validate_schema_version(payload: object, path: Path) -> dict[str, object]:
    if not isinstance(payload, dict):
        msg = f"failed to decode {path}: expected object payload"
        raise StoreDecodeError(msg)
    if "schema_version" not in payload:
        msg = f"failed to decode {path}: missing schema_version"
        raise StoreDecodeError(msg)
    return payload


def write_json_atomic(path: Path, model: BaseModel) -> None:
    """Write one JSON model atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        os.close(fd)
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(model.model_dump(mode="json"), handle, ensure_ascii=True, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def read_json_model(path: Path, model_type: type[ModelT]) -> ModelT:
    """Read one JSON model with explicit schema checks."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as exc:
        msg = f"failed to decode {path}: invalid json"
        raise StoreDecodeError(msg) from exc
    payload = _validate_schema_version(raw, path)
    try:
        return model_type.model_validate(payload)
    except Exception as exc:
        msg = f"failed to decode {path}: schema validation failed"
        raise StoreDecodeError(msg) from exc


def append_jsonl_record(path: Path, model: BaseModel) -> None:
    """Append one model as a JSONL record."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(model.model_dump_json())
        handle.write("\n")


def read_jsonl_models(path: Path, model_type: type[ModelT]) -> list[ModelT]:
    """Read all JSONL models from one append-only file."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    items: list[ModelT] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            msg = f"failed to decode {path}: invalid jsonl"
            raise StoreDecodeError(msg) from exc
        payload = _validate_schema_version(raw, path)
        try:
            items.append(model_type.model_validate(payload))
        except Exception as exc:
            msg = f"failed to decode {path}: schema validation failed"
            raise StoreDecodeError(msg) from exc
    return items
