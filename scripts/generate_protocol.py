"""Generate Python protocol models from JSON Schema.

This intentionally supports the schema subset used by `schemas/controlmesh/v1`.
It avoids adding a new generator dependency while keeping Python models derived
from the same source as the TypeScript protocol package.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO_ROOT / "schemas" / "controlmesh" / "v1"
OUTPUT = REPO_ROOT / "controlmesh" / "protocol" / "generated" / "models.py"

HEADER = '''"""Generated protocol models from schemas/controlmesh/v1.

Do not edit manually. Regenerate with:

    uv run python scripts/generate_protocol.py
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

'''


def _class_name_from_ref(ref: str) -> str:
    stem = Path(ref).name.removesuffix(".schema.json")
    return "".join(part.capitalize() for part in stem.split("-"))


def _py_type(schema: dict[str, Any]) -> str:
    if "const" in schema:
        return f"Literal[{json.dumps(schema['const'])}]"
    if "$ref" in schema:
        return _class_name_from_ref(str(schema["$ref"]))
    enum = schema.get("enum")
    if isinstance(enum, list):
        return "Literal[" + ", ".join(json.dumps(item) for item in enum) + "]"
    raw_type = schema.get("type")
    if isinstance(raw_type, list):
        return _join_union(_primitive_type(item) for item in raw_type)
    if raw_type == "array":
        return f"list[{_py_type(schema.get('items') or {})}]"
    if raw_type == "object":
        additional = schema.get("additionalProperties")
        if isinstance(additional, dict):
            return f"dict[str, {_py_type(additional)}]"
        return "dict[str, Any]"
    return _primitive_type(raw_type)


def _primitive_type(raw_type: object) -> str:
    if raw_type == "string":
        return "str"
    if raw_type in {"integer", "number"}:
        return "int" if raw_type == "integer" else "float"
    if raw_type == "boolean":
        return "bool"
    if raw_type == "null":
        return "None"
    return "Any"


def _join_union(parts: object) -> str:
    seen: list[str] = []
    for part in parts:
        text = str(part)
        if text not in seen:
            seen.append(text)
    return " | ".join(seen)


def _optional_type(py_type: str) -> str:
    return py_type if "None" in py_type.split(" | ") else f"{py_type} | None"


def _field_name(name: str) -> str:
    if name == "schema_version":
        return name
    if name.isidentifier() and not name.startswith("_"):
        return name
    return f"{name}_"


def _render_model(schema: dict[str, Any]) -> str:
    title = str(schema["title"])
    if schema.get("type") != "object":
        return f"{title} = {_py_type(schema)}\n"

    required = set(schema.get("required") or [])
    lines = [f"class {title}(BaseModel):", '    model_config = ConfigDict(extra="allow")']
    for name, property_schema in (schema.get("properties") or {}).items():
        py_name = _field_name(name)
        py_type = _py_type(property_schema)
        if name in required:
            default = ""
        else:
            py_type = _optional_type(py_type)
            default = " = None"
        if py_name == name:
            lines.append(f"    {py_name}: {py_type}{default}")
        else:
            lines.append(f"    {py_name}: {py_type}{default} = Field(alias={json.dumps(name)})")
    if len(lines) == 2:
        lines.append("    pass")
    return "\n".join(lines) + "\n"


def main() -> None:
    chunks = [HEADER]
    for path in sorted(SCHEMA_DIR.glob("*.schema.json")):
        schema = json.loads(path.read_text())
        chunks.append(_render_model(schema))
        chunks.append("\n\n")
    OUTPUT.write_text("".join(chunks).rstrip() + "\n")


if __name__ == "__main__":
    main()
