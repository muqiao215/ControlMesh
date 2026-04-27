"""WorkUnit primitives for capability-based task routing."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class WorkUnitKind(StrEnum):
    """Supported MVP development work units."""

    TEST_EXECUTION = "test_execution"
    CODE_REVIEW = "code_review"
    PATCH_CANDIDATE = "patch_candidate"


@dataclass(frozen=True, slots=True)
class WorkUnitRouteRequirements:
    """Capability and permission hints needed to route one unit of work."""

    capabilities: tuple[str, ...] = ()
    avoid_capabilities: tuple[str, ...] = ()
    can_edit: bool | None = None
    evaluator_required: bool = False
    promotion_allowed: bool = False


@dataclass(frozen=True, slots=True)
class WorkUnit:
    """A routable, executable task package."""

    kind: WorkUnitKind
    name: str = ""
    prompt: str = ""
    command: str = ""
    target: str = ""
    evidence: str = ""
    topology: str = ""
    requirements: WorkUnitRouteRequirements = field(
        default_factory=WorkUnitRouteRequirements
    )


def normalize_workunit_kind(value: str | WorkUnitKind | None) -> WorkUnitKind | None:
    """Normalize a user/API supplied workunit kind."""
    if isinstance(value, WorkUnitKind):
        return value
    normalized = (value or "").strip().lower().replace("-", "_")
    if not normalized:
        return None
    aliases = {
        "test": WorkUnitKind.TEST_EXECUTION,
        "tests": WorkUnitKind.TEST_EXECUTION,
        "pytest": WorkUnitKind.TEST_EXECUTION,
        "review": WorkUnitKind.CODE_REVIEW,
        "code_review": WorkUnitKind.CODE_REVIEW,
        "patch": WorkUnitKind.PATCH_CANDIDATE,
        "fix": WorkUnitKind.PATCH_CANDIDATE,
        "patch_candidate": WorkUnitKind.PATCH_CANDIDATE,
    }
    if normalized in aliases:
        return aliases[normalized]
    try:
        return WorkUnitKind(normalized)
    except ValueError:
        return None


def requirements_for_kind(kind: WorkUnitKind) -> WorkUnitRouteRequirements:
    """Return default routing requirements for the MVP kinds."""
    if kind is WorkUnitKind.TEST_EXECUTION:
        return WorkUnitRouteRequirements(
            capabilities=("shell_execution", "test_log_analysis", "evidence_writer"),
            can_edit=False,
            evaluator_required=False,
            promotion_allowed=False,
        )
    if kind is WorkUnitKind.CODE_REVIEW:
        return WorkUnitRouteRequirements(
            capabilities=("code_review", "diff_understanding", "evidence_writer"),
            can_edit=False,
            evaluator_required=True,
            promotion_allowed=False,
        )
    return WorkUnitRouteRequirements(
        capabilities=("code_patch", "test_execution", "evidence_writer"),
        can_edit=True,
        evaluator_required=True,
        promotion_allowed=False,
    )


def build_workunit_contract(unit: WorkUnit) -> str:
    """Render the worker-facing contract for a WorkUnit."""
    if unit.kind is WorkUnitKind.TEST_EXECUTION:
        command = f"\nCommand: `{unit.command}`" if unit.command else ""
        return (
            "## WorkUnit Contract: test_execution\n"
            "Run the requested test/check command and summarize the outcome.\n"
            f"{command}\n"
            "- Do not edit files.\n"
            "- Capture the exact command, exit status, and important logs.\n"
            "- Classify failures and provide the smallest useful reproduction.\n"
            "- Produce evidence before conclusions."
        )
    if unit.kind is WorkUnitKind.CODE_REVIEW:
        target = f"\nTarget: `{unit.target}`" if unit.target else ""
        return (
            "## WorkUnit Contract: code_review\n"
            "Review the target without changing files.\n"
            f"{target}\n"
            "- Report concrete findings first, with file/line evidence when possible.\n"
            "- Distinguish bugs, risks, missing tests, and open questions.\n"
            "- Do not produce or apply a patch unless explicitly resumed with permission."
        )
    evidence = f"\nEvidence: `{unit.evidence}`" if unit.evidence else ""
    return (
        "## WorkUnit Contract: patch_candidate\n"
        "Produce the smallest candidate fix and evidence for controller review.\n"
        f"{evidence}\n"
        "- Edit only files necessary for the candidate patch.\n"
        "- Run targeted verification where practical.\n"
        "- Summarize changed files, tests, and remaining risk.\n"
        "- The controller decides whether to promote the result."
    )
