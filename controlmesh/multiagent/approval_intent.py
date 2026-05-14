from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


RELEASE_STEP_IDS = (
    "pytest_full",
    "uv_build",
    "verify_tag_local",
    "push_main",
    "push_tag",
    "verify_remote_tag",
    "gh_release_create",
)
APPROVAL_REQUIRED_STEP_IDS = frozenset({"push_main", "push_tag", "gh_release_create"})


@dataclass(frozen=True, slots=True)
class ApprovalIntent:
    target: str
    step_id: str
    source: Literal["short_approve", "mesh_approve"]


def parse_short_approval_intent(text: str) -> ApprovalIntent | None:
    parts = text.strip().split()
    if len(parts) != 3 or parts[0].lower() != "approve":
        return None
    step_id = parts[1].strip()
    target = parts[2].strip()
    if step_id not in APPROVAL_REQUIRED_STEP_IDS or not target:
        return None
    return ApprovalIntent(target=target, step_id=step_id, source="short_approve")


def parse_mesh_approval_intent(text: str) -> ApprovalIntent | None:
    parts = text.strip().split(None, 3)
    if len(parts) < 4 or parts[0] != "/mesh" or parts[1].lower() != "approve":
        return None
    target = parts[2].strip()
    step_id = parts[3].strip()
    if step_id not in APPROVAL_REQUIRED_STEP_IDS or not target:
        return None
    return ApprovalIntent(target=target, step_id=step_id, source="mesh_approve")


def render_explicit_step_required(*, target: str, step_id: str) -> str:
    return (
        "Release approval requires an explicit step.\n\n"
        "Current awaiting step:\n"
        f"- {step_id}\n\n"
        "Use:\n"
        f"approve {step_id} {target}"
    )


def is_rejected_broad_approval(text: str) -> bool:
    normalized = " ".join(text.strip().lower().split())
    if not normalized:
        return False
    return normalized.startswith("approve all ") or (
        normalized.startswith("approve ") and len(normalized.split()) in {1, 2, 3} and parse_short_approval_intent(text) is None
    )
