from __future__ import annotations

import json
from pathlib import Path

from controlmesh.case_pack.models import CasePack


def load_case_pack(path: Path) -> CasePack:
    return CasePack.model_validate_json(path.read_text(encoding="utf-8"))


def dump_case_pack(case_pack: CasePack) -> str:
    return json.dumps(case_pack.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
