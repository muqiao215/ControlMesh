"""WorkUnit primitives for capability-based task routing."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class RoutingRisk(StrEnum):
    """Risk levels used by the background admission gate."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


FORCE_FOREGROUND_CAPS: frozenset[str] = frozenset(
    {
        "repo_write",
        "git_write",
        "network_write",
        "github_release",
        "publish",
    }
)

_WRITE_SIDE_EFFECTS: frozenset[str] = frozenset(
    {
        "repo_write",
        "git_write",
        "network_write",
        "publish",
        "release_create",
        "external_write",
    }
)


class WorkUnitKind(StrEnum):
    """Supported capability-routed work units."""

    TEST_EXECUTION = "test_execution"
    CODE_REVIEW = "code_review"
    PATCH_CANDIDATE = "patch_candidate"
    PLAN_WITH_FILES = "plan_with_files"
    PHASE_EXECUTION = "phase_execution"
    PHASE_REVIEW = "phase_review"
    GITHUB_RELEASE = "github_release"
    DOCS_PUBLISH = "docs_publish"
    REPO_AUDIT = "repo_audit"
    DEPENDENCY_UPDATE = "dependency_update"
    TEST_TRIAGE = "test_triage"


@dataclass(frozen=True, slots=True)
class WorkUnitRouteRequirements:
    """Capability and permission hints needed to route one unit of work."""

    capabilities: tuple[str, ...] = ()
    avoid_capabilities: tuple[str, ...] = ()
    can_edit: bool | None = None
    evaluator_required: bool = False
    promotion_allowed: bool = False


@dataclass(frozen=True, slots=True)
class RoutingIntent:
    """Explicit safety intent for a WorkUnit before worker scoring."""

    risk: RoutingRisk = RoutingRisk.LOW
    required_caps: frozenset[str] = frozenset()
    side_effects: frozenset[str] = frozenset()
    requires_user_approval: bool = False
    output_policy: str = "summarized_only"


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
        "plan": WorkUnitKind.PLAN_WITH_FILES,
        "planfiles": WorkUnitKind.PLAN_WITH_FILES,
        "planning_with_files": WorkUnitKind.PLAN_WITH_FILES,
        "phase": WorkUnitKind.PHASE_EXECUTION,
        "phase_execute": WorkUnitKind.PHASE_EXECUTION,
        "phase_execution": WorkUnitKind.PHASE_EXECUTION,
        "phase_review": WorkUnitKind.PHASE_REVIEW,
        "github_release": WorkUnitKind.GITHUB_RELEASE,
        "release": WorkUnitKind.GITHUB_RELEASE,
        "docs": WorkUnitKind.DOCS_PUBLISH,
        "docs_publish": WorkUnitKind.DOCS_PUBLISH,
        "audit": WorkUnitKind.REPO_AUDIT,
        "repo_audit": WorkUnitKind.REPO_AUDIT,
        "dependency_update": WorkUnitKind.DEPENDENCY_UPDATE,
        "deps": WorkUnitKind.DEPENDENCY_UPDATE,
        "test_triage": WorkUnitKind.TEST_TRIAGE,
    }
    if normalized in aliases:
        return aliases[normalized]
    try:
        return WorkUnitKind(normalized)
    except ValueError:
        return None


def requirements_for_kind(kind: WorkUnitKind) -> WorkUnitRouteRequirements:
    """Return default routing requirements for routable WorkUnit kinds."""
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
    if kind is WorkUnitKind.PATCH_CANDIDATE:
        return WorkUnitRouteRequirements(
            capabilities=("code_patch", "test_execution", "evidence_writer"),
            can_edit=True,
            evaluator_required=True,
            promotion_allowed=False,
        )
    if kind is WorkUnitKind.GITHUB_RELEASE:
        return WorkUnitRouteRequirements(
            capabilities=("github_release", "release_notes", "shell_execution", "evidence_writer"),
            can_edit=False,
            evaluator_required=True,
            promotion_allowed=False,
        )
    if kind is WorkUnitKind.DOCS_PUBLISH:
        return WorkUnitRouteRequirements(
            capabilities=("docs_publish", "release_notes", "evidence_writer"),
            can_edit=True,
            evaluator_required=True,
            promotion_allowed=False,
        )
    if kind is WorkUnitKind.REPO_AUDIT:
        return WorkUnitRouteRequirements(
            capabilities=("repo_audit", "code_search", "evidence_writer"),
            can_edit=False,
            evaluator_required=True,
            promotion_allowed=False,
        )
    if kind is WorkUnitKind.TEST_TRIAGE:
        return WorkUnitRouteRequirements(
            capabilities=("test_triage", "test_log_analysis", "evidence_writer"),
            can_edit=False,
            evaluator_required=True,
            promotion_allowed=False,
        )
    if kind is WorkUnitKind.DEPENDENCY_UPDATE:
        return WorkUnitRouteRequirements(
            capabilities=("dependency_update", "shell_execution", "evidence_writer"),
            can_edit=True,
            evaluator_required=True,
            promotion_allowed=False,
        )
    if kind is WorkUnitKind.PHASE_REVIEW:
        return WorkUnitRouteRequirements(
            capabilities=("phase_review", "evidence_writer", "final_judgment"),
            can_edit=False,
            evaluator_required=True,
            promotion_allowed=False,
        )
    if kind is WorkUnitKind.PLAN_WITH_FILES:
        return WorkUnitRouteRequirements(
            capabilities=("planning", "evidence_writer"),
            can_edit=True,
            evaluator_required=True,
            promotion_allowed=False,
        )
    return WorkUnitRouteRequirements(
        capabilities=("code_patch", "test_execution", "evidence_writer"),
        can_edit=True,
        evaluator_required=True,
        promotion_allowed=False,
    )


def intent_for_kind(
    kind: WorkUnitKind,
    requirements: WorkUnitRouteRequirements | None = None,
) -> RoutingIntent:
    """Return the conservative routing intent for a WorkUnit kind."""
    requirements = requirements or requirements_for_kind(kind)
    required_caps = set(requirements.capabilities)
    side_effects: set[str] = set()
    risk = RoutingRisk.LOW

    if kind is WorkUnitKind.PATCH_CANDIDATE:
        required_caps.add("repo_write")
        side_effects.add("repo_write")
        risk = RoutingRisk.MEDIUM

    if kind is WorkUnitKind.GITHUB_RELEASE:
        required_caps.update({"github_release", "publish"})
        side_effects.update({"git_write", "network_write", "publish", "release_create"})
        risk = RoutingRisk.HIGH
    elif kind is WorkUnitKind.DOCS_PUBLISH:
        required_caps.update({"publish", "network_write"})
        side_effects.update({"repo_write", "network_write", "publish", "external_write"})
        risk = RoutingRisk.HIGH
    elif kind is WorkUnitKind.DEPENDENCY_UPDATE:
        required_caps.update({"repo_write", "network_write"})
        side_effects.update({"repo_write", "network_write"})
        risk = RoutingRisk.HIGH

    return RoutingIntent(
        risk=risk,
        required_caps=frozenset(required_caps),
        side_effects=frozenset(side_effects),
        requires_user_approval=bool(side_effects & _WRITE_SIDE_EFFECTS),
        output_policy="summarized_only",
    )


def force_foreground(intent: RoutingIntent) -> bool:
    """Return True when the intent cannot be admitted to background routing."""
    return (
        intent.risk == RoutingRisk.HIGH
        or bool(intent.required_caps & FORCE_FOREGROUND_CAPS)
        or bool(intent.side_effects & FORCE_FOREGROUND_CAPS)
        or intent.requires_user_approval
    )


def may_background(intent: RoutingIntent, worker: object) -> bool:
    """P0 background admission predicate for a resolved intent and worker slot."""
    if intent.risk == RoutingRisk.HIGH:
        return False
    if intent.side_effects & _WRITE_SIDE_EFFECTS:
        return False
    if not bool(getattr(worker, "runtime_writeback", False)):
        return False
    capabilities = frozenset(getattr(worker, "capabilities", {}) or {})
    if not intent.required_caps.issubset(capabilities):
        return False
    if getattr(worker, "output_channel", getattr(worker, "output_policy", "")) != "summarized_only":
        return False
    return getattr(worker, "mode", "") == "background"


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
    if unit.kind is WorkUnitKind.GITHUB_RELEASE:
        target = f"\nTarget: `{unit.target}`" if unit.target else ""
        return (
            "## WorkUnit Contract: github_release\n"
            "Prepare release evidence for foreground approval.\n"
            f"{target}\n"
            "- Do not publish, tag, push, upload, or send external notifications.\n"
            "- Inspect release state and produce proposed release notes.\n"
            "- Capture exact commands, relevant URLs, versions, and unresolved blockers.\n"
            "- Wait for the controller to perform or explicitly approve publish actions."
        )
    if unit.kind is WorkUnitKind.PLAN_WITH_FILES:
        return (
            "## WorkUnit Contract: plan_with_files\n"
            "Create or update the canonical file-backed execution plan.\n"
            "- Maintain PLAN.md, PHASES.json, and STATE.json.\n"
            "- Define clear phase titles, workunit kinds, and edit permissions.\n"
            "- Do not guess missing requirements; ask the parent when blocked.\n"
            "- Treat the plan files as the source of truth for later phase execution."
        )
    if unit.kind is WorkUnitKind.PHASE_EXECUTION:
        return (
            "## WorkUnit Contract: phase_execution\n"
            "Execute the assigned plan phase and write durable phase artifacts.\n"
            "- Keep work scoped to the assigned phase.\n"
            "- Write TASKMEMORY.md, EVIDENCE.json, and RESULT.md for controller review.\n"
            "- Ask the parent when blocked instead of guessing.\n"
            "- The foreground controller approves, repairs, or advances the next phase."
        )
    if unit.kind is WorkUnitKind.PHASE_REVIEW:
        return (
            "## WorkUnit Contract: phase_review\n"
            "Review phase artifacts without changing canonical files.\n"
            "- Verify RESULT.md claims against EVIDENCE.json.\n"
            "- Classify the phase as approve, repair, or ask.\n"
            "- Report concrete evidence and remaining risks."
        )
    if unit.kind in {
        WorkUnitKind.DOCS_PUBLISH,
        WorkUnitKind.REPO_AUDIT,
        WorkUnitKind.DEPENDENCY_UPDATE,
        WorkUnitKind.TEST_TRIAGE,
    }:
        return (
            f"## WorkUnit Contract: {unit.kind.value}\n"
            "Complete the requested unit with controller-reviewable evidence.\n"
            "- Respect the route's edit permission.\n"
            "- Capture exact commands, files inspected or changed, and outcomes.\n"
            "- Produce a concise result and unresolved-risk summary."
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
