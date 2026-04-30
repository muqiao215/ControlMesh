#!/usr/bin/env python3
"""Submit a phased release workflow to the background task system.

This entrypoint creates a PlanFiles plan for software release with sensible
default phases, then submits each phase as a background task using plan_id/
phase_id metadata. Publish phases are tagged with ``evaluator=foreground`` so
the foreground controller can review and approve before external side effects.

Usage:
    python3 release_task.py [options] "Release description"

Options:
    --name NAME          Override the plan name (default: "release-<timestamp>")
    --provider PROVIDER  Explicit provider hint (claude, codex, gemini, claw)
    --model MODEL        Model hint (opus, sonnet, etc.)
    --claude             Prefer Claude for all phases (sets route=claude on phases)
    --repo-url URL       Repository URL for the release
    --version VERSION    Target version (auto-detected if not provided)
    --dry-run            Create plan but do not submit tasks (shows plan only)
    --phase PHASE        Start from a specific phase (skip earlier phases)
    --foreground-eval   Use foreground approval for all publish/release phases
                         (this is the default; use --no-foreground-eval to disable)

Exit codes:
    0   Tasks submitted successfully (or --dry-run completed)
    1   Error

Example:
    # Full release with Claude preference
    python3 release_task.py --claude --repo-url https://github.com/org/repo

    # Dry-run to preview the plan
    python3 release_task.py --dry-run --repo-url https://github.com/org/repo

    # Start from preflight (skip repo audit)
    python3 release_task.py --phase preflight_checks --repo-url https://github.com/org/repo

Environment variables CONTROLMESH_AGENT_NAME and CONTROLMESH_INTERAGENT_PORT are
automatically set by the ControlMesh framework.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path


_HELP_FLAGS = {"--help", "-h"}


def _load_shared() -> tuple[object, object, object]:
    tools_dir = os.path.dirname(__file__)
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    from _shared import (
        detect_agent_name,
        get_api_url,
        normalize_provider_name,
        post_json,
    )

    return get_api_url, post_json, detect_agent_name, normalize_provider_name


# Default phases for a release workflow.
# Each phase has:
#   id: unique phase identifier
#   title: human-readable phase title
#   workunit_kind: the WorkUnit kind for routing
#   route: routing preference ("claude", "auto", etc.)
#   evaluator: approval requirement ("foreground" = requires controller approval)
#   description: what the phase does
DEFAULT_RELEASE_PHASES = (
    {
        "id": "repo_audit",
        "title": "Repository Audit",
        "workunit_kind": "repo_audit",
        "route": "auto",
        "evaluator": "",
        "description": "Inspect repository state: branch coverage, uncommitted "
        "changes, open critical issues, dependency health.",
    },
    {
        "id": "preflight_checks",
        "title": "Preflight Checks",
        "workunit_kind": "test_execution",
        "route": "auto",
        "evaluator": "",
        "description": "Run build, unit tests, integration tests, lint, and type "
        "checks. Fail fast on any critical failure.",
    },
    {
        "id": "release_prep",
        "title": "Release Preparation",
        "workunit_kind": "patch_candidate",
        "route": "auto",
        "evaluator": "",
        "description": "Determine next version, update CHANGELOG, bump version "
        "files, create git tag (local only at this stage).",
    },
    {
        "id": "publish",
        "title": "Publish Release",
        "workunit_kind": "github_release",
        "route": "claude",
        "evaluator": "foreground",
        "description": "Push git tag, create GitHub release, publish to package "
        "registries. REQUIRES FOREGROUND APPROVAL before external side effects.",
    },
    {
        "id": "verify",
        "title": "Post-Release Verification",
        "workunit_kind": "test_execution",
        "route": "auto",
        "evaluator": "",
        "description": "Verify release artifacts, check CI pipelines, confirm "
        "package registry visibility.",
    },
)

# Phases that require foreground approval before external effects
FOREGROUND_APPROVAL_PHASES = frozenset({"publish", "github_release"})

# Phase order (used for --phase skip)
_PHASE_ORDER = tuple(p["id"] for p in DEFAULT_RELEASE_PHASES)


def _generate_plan_id(name: str) -> str:
    """Generate a deterministic plan_id from a name + timestamp."""
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    safe_name = "".join(c if c.isalnum() else "-" for c in name.lower())
    return f"release-{safe_name}-{ts}"


def _build_plan_markdown(
    plan_id: str,
    description: str,
    repo_url: str,
    version: str,
) -> str:
    """Build the PLAN.md markdown for the release workflow."""
    lines = [
        f"# Release Plan: {plan_id}",
        "",
        f"**Description**: {description}",
        f"**Repository**: {repo_url}",
        f"**Version**: {version or '(auto-detect)'}",
        "",
        "## Phases",
        "",
    ]
    for phase in DEFAULT_RELEASE_PHASES:
        approval = " [FOREGROUND APPROVAL REQUIRED]" if phase["evaluator"] == "foreground" else ""
        lines.append(f"### {phase['id']}: {phase['title']}{approval}")
        lines.append(f"- WorkUnit: `{phase['workunit_kind']}`")
        lines.append(f"- Route: `{phase['route']}`")
        lines.append(f"- {phase['description']}")
        lines.append("")

    lines.extend([
        "## Foreground Controller Notes",
        "",
        "- The `publish` phase (and any `github_release` phases) require explicit "
        "foreground approval before external side effects.",
        "- Use `python3 tools/task_tools/list_tasks.py` to monitor phase progress.",
        "- Use `python3 tools/task_tools/resume_task.py TASK_ID \"approval message\"` "
        "to approve or provide input to a waiting phase.",
        "- Use `python3 tools/task_tools/cancel_task.py TASK_ID` to abort a phase.",
        "",
        "## PlanFiles Artifacts",
        "",
        "This plan creates artifacts in `~/.controlmesh/plans/<plan_id>/`:",
        "- `PLAN.md` - this file",
        "- `PHASES.json` - phase manifest with status",
        "- `STATE.json` - overall plan state",
        "- `<phase_id>/` - per-phase TASKMEMORY.md, EVIDENCE.json, RESULT.md",
    ])
    return "\n".join(lines)


def _submit_phase(
    post_json: object,
    get_api_url: object,
    sender: str,
    plan_id: str,
    phase: dict,
    prompt: str,
    provider: str,
    model: str,
    chat_id: int | None = None,
    topic_id: int | None = None,
) -> dict[str, object]:
    """Submit one phase as a background task."""
    url_func = get_api_url  # type: ignore
    post_func = post_json  # type: ignore

    body: dict[str, object] = {
        "from": sender,
        "prompt": prompt,
        "name": f"[{plan_id}] {phase['title']}",
        "workunit_kind": phase["workunit_kind"],
        "route": phase["route"],
        "plan_id": plan_id,
        "plan_markdown": "",  # Filled by first phase via create_task
        "phase_id": phase["id"],
        "phase_title": phase["title"],
    }

    if provider:
        body["provider"] = provider
    if model:
        body["model"] = model
    if phase["evaluator"]:
        body["evaluator"] = phase["evaluator"]

    if chat_id:
        body["chat_id"] = chat_id
    if topic_id:
        body["topic_id"] = topic_id

    return post_func(url_func("/tasks/create"), body, timeout=10)


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] in _HELP_FLAGS:
        print((__doc__ or "").strip())
        return

    get_api_url, post_json, detect_agent_name, normalize_provider_name = _load_shared()

    # Parse arguments
    name = ""
    provider = ""
    model = ""
    claude_preferred = False
    repo_url = ""
    version = ""
    dry_run = False
    start_phase = ""
    foreground_eval = True  # Default: use foreground approval for publish phases

    while args:
        if args[0] == "--name" and len(args) >= 2:
            name = args[1]
            args = args[2:]
        elif args[0] == "--provider" and len(args) >= 2:
            provider = normalize_provider_name(args[1])
            args = args[2:]
        elif args[0] == "--model" and len(args) >= 2:
            model = args[1]
            args = args[2:]
        elif args[0] == "--claude":
            claude_preferred = True
            args = args[1:]
        elif args[0] == "--repo-url" and len(args) >= 2:
            repo_url = args[1]
            args = args[2:]
        elif args[0] == "--version" and len(args) >= 2:
            version = args[1]
            args = args[2:]
        elif args[0] == "--dry-run":
            dry_run = True
            args = args[1:]
        elif args[0] == "--phase" and len(args) >= 2:
            start_phase = args[1]
            args = args[2:]
        elif args[0] == "--foreground-eval":
            foreground_eval = True
            args = args[1:]
        elif args[0] == "--no-foreground-eval":
            foreground_eval = False
            args = args[1:]
        else:
            break

    # Remaining positional argument is the description
    description = args[0] if args else "Software release"

    # Generate plan_id
    plan_name = name or description.split()[0][:20]
    plan_id = _generate_plan_id(plan_name)

    # Build plan markdown (used for all phases via create_task plan_phases)
    plan_markdown = _build_plan_markdown(plan_id, description, repo_url, version)

    # Build plan_phases for the create_task API
    plan_phases = []
    for phase in DEFAULT_RELEASE_PHASES:
        # Apply --claude preference
        if claude_preferred:
            phase = dict(phase)
            phase["route"] = "claude"

        # Disable foreground approval if requested
        if not foreground_eval and phase["id"] in FOREGROUND_APPROVAL_PHASES:
            phase = dict(phase)
            phase["evaluator"] = ""

        plan_phases.append(phase)

    # Filter phases based on --phase start point
    phases_to_run = plan_phases
    if start_phase:
        try:
            start_index = _PHASE_ORDER.index(start_phase)
            phases_to_run = plan_phases[start_index:]
        except ValueError:
            print(f"Error: Unknown phase '{start_phase}'", file=sys.stderr)
            print(f"Available phases: {', '.join(_PHASE_ORDER)}", file=sys.stderr)
            sys.exit(1)

    # Print plan summary
    print(f"Release Plan: {plan_id}")
    print(f"Description: {description}")
    print(f"Repository: {repo_url or '(not specified)'}")
    print(f"Version: {version or '(auto-detect)'}")
    print(f"Foreground approval for publish: {'yes' if foreground_eval else 'no'}")
    if claude_preferred:
        print("Claude preference: enabled (all phases)")
    print()
    print("Phases:")
    for phase in phases_to_run:
        approval = " [FOREGROUND APPROVAL]" if phase["evaluator"] == "foreground" else ""
        print(f"  - {phase['id']}: {phase['title']}{approval}")
    print()

    if dry_run:
        print("Dry-run mode: showing plan only, no tasks submitted.")
        print(f"Plan ID: {plan_id}")
        print()
        print("To submit the plan, run without --dry-run.")
        return

    # Submit phases
    sender = detect_agent_name()

    # Propagate sender context
    chat_id_str = os.environ.get("CONTROLMESH_CHAT_ID", "")
    topic_id_str = os.environ.get("CONTROLMESH_TOPIC_ID", "")
    chat_id = int(chat_id_str) if chat_id_str else None
    topic_id = int(topic_id_str) if topic_id_str else None

    # First phase gets the full plan manifest
    first_phase = phases_to_run[0]
    first_body: dict[str, object] = {
        "from": sender,
        "prompt": f"Execute phase 1 of the release plan.\n\n{description}",
        "name": f"[{plan_id}] {first_phase['title']}",
        "workunit_kind": first_phase["workunit_kind"],
        "route": first_phase["route"],
        "plan_id": plan_id,
        "plan_markdown": plan_markdown,
        "plan_phases": list(phases_to_run),
        "phase_id": first_phase["id"],
        "phase_title": first_phase["title"],
    }
    if provider:
        first_body["provider"] = provider
    if model:
        first_body["model"] = model
    if first_phase["evaluator"]:
        first_body["evaluator"] = first_phase["evaluator"]
    if chat_id:
        first_body["chat_id"] = chat_id
    if topic_id:
        first_body["topic_id"] = topic_id

    print(f"Submitting phase 1: {first_phase['id']}...")
    result = post_json(get_api_url("/tasks/create"), first_body, timeout=10)
    if not result.get("success"):
        error = result.get("error", "Unknown error")
        print(f"Error submitting phase 1: {error}", file=sys.stderr)
        sys.exit(1)

    first_task_id = result.get("task_id", "?")
    print(f"  Task submitted: {first_task_id}")

    # Remaining phases
    for i, phase in enumerate(phases_to_run[1:], start=2):
        body: dict[str, object] = {
            "from": sender,
            "prompt": f"Execute phase {i} of the release plan.\n\n{description}",
            "name": f"[{plan_id}] {phase['title']}",
            "workunit_kind": phase["workunit_kind"],
            "route": phase["route"],
            "plan_id": plan_id,
            "plan_markdown": "",  # Not needed for subsequent phases
            "phase_id": phase["id"],
            "phase_title": phase["title"],
        }
        if provider:
            body["provider"] = provider
        if model:
            body["model"] = model
        if phase["evaluator"]:
            body["evaluator"] = phase["evaluator"]
        if chat_id:
            body["chat_id"] = chat_id
        if topic_id:
            body["topic_id"] = topic_id

        print(f"Submitting phase {i}: {phase['id']}...")
        result = post_json(get_api_url("/tasks/create"), body, timeout=10)
        if not result.get("success"):
            error = result.get("error", "Unknown error")
            print(f"Warning: Error submitting phase {i}: {error}", file=sys.stderr)
            print("  The plan was partially submitted. Check task list for status.", file=sys.stderr)
        else:
            task_id = result.get("task_id", "?")
            print(f"  Task submitted: {task_id}")

    print()
    print(f"Release workflow '{plan_id}' submitted.")
    print("Use `python3 tools/task_tools/list_tasks.py` to monitor progress.")
    print()
    print("PlanFiles artifacts:")
    print(f"  ~/.controlmesh/plans/{plan_id}/PLAN.md")
    print(f"  ~/.controlmesh/plans/{plan_id}/PHASES.json")


if __name__ == "__main__":
    main()
