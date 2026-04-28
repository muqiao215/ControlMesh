#!/usr/bin/env python3
"""Create a capability-routed background task.

Usage:
    python3 route_task.py --kind test_execution --name "Run pytest" \
        --command "uv run pytest tests/test_x.py -q"
    python3 route_task.py --kind code_review --target "git diff main" --topology review_fanout
    python3 route_task.py --kind patch_candidate --name "Fix failing test" \
        --evidence logs/pytest.log

Options:
    --kind KIND        test_execution, code_review, or patch_candidate
    --name NAME        Human-readable task name
    --command CMD      Test/check command for test_execution
    --target TARGET    Review target or scope
    --evidence PATH    Evidence/log path for patch_candidate
    --topology NAME    Optional topology or alias
    --provider PROV    Explicit provider override
    --model MODEL      Explicit model override
    --capability CAP   Required capability hint (repeatable)
    --evaluator NAME   Evaluator hint, e.g. foreground
"""

from __future__ import annotations

import os
import sys


_HELP_FLAGS = {"--help", "-h"}


def _load_shared() -> tuple[object, object, object, object]:
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


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] in _HELP_FLAGS:
        print((__doc__ or "").strip())
        return

    get_api_url, post_json, detect_agent_name, normalize_provider_name = _load_shared()
    name = ""
    kind = ""
    command = ""
    target = ""
    evidence = ""
    topology = ""
    provider = ""
    model = ""
    evaluator = ""
    required_capabilities: list[str] = []

    while args:
        if args[0] == "--name" and len(args) >= 2:
            name = args[1]
            args = args[2:]
        elif args[0] in {"--kind", "--workunit-kind"} and len(args) >= 2:
            kind = args[1]
            args = args[2:]
        elif args[0] == "--command" and len(args) >= 2:
            command = args[1]
            args = args[2:]
        elif args[0] == "--target" and len(args) >= 2:
            target = args[1]
            args = args[2:]
        elif args[0] == "--evidence" and len(args) >= 2:
            evidence = args[1]
            args = args[2:]
        elif args[0] == "--topology" and len(args) >= 2:
            topology = args[1]
            args = args[2:]
        elif args[0] == "--provider" and len(args) >= 2:
            provider = args[1]
            args = args[2:]
        elif args[0] == "--model" and len(args) >= 2:
            model = args[1]
            args = args[2:]
        elif args[0] == "--capability" and len(args) >= 2:
            required_capabilities.append(args[1])
            args = args[2:]
        elif args[0] == "--evaluator" and len(args) >= 2:
            evaluator = args[1]
            args = args[2:]
        else:
            break

    prompt = args[0] if args else _default_prompt(kind, command, target, evidence)
    if not prompt:
        print(
            "Usage: python3 route_task.py --kind KIND "
            "[--command CMD|--target TARGET|prompt]",
            file=sys.stderr,
        )
        sys.exit(1)

    body: dict[str, object] = {
        "from": detect_agent_name(),
        "prompt": prompt,
        "route": "auto",
    }
    if name:
        body["name"] = name
    if kind:
        body["workunit_kind"] = kind
    if command:
        body["command"] = command
    if target:
        body["target"] = target
    if evidence:
        body["evidence"] = evidence
    if topology:
        body["topology"] = topology
    if provider:
        body["provider"] = normalize_provider_name(provider)
    if model:
        body["model"] = model
    if required_capabilities:
        body["required_capabilities"] = required_capabilities
    if evaluator:
        body["evaluator"] = evaluator

    chat_id = os.environ.get("CONTROLMESH_CHAT_ID", "")
    topic_id = os.environ.get("CONTROLMESH_TOPIC_ID", "")
    if chat_id:
        body["chat_id"] = int(chat_id)
    if topic_id:
        body["topic_id"] = int(topic_id)

    result = post_json(get_api_url("/tasks/create"), body, timeout=10)
    if result.get("success"):
        task_id = result.get("task_id", "unknown")
        display = f"'{name}'" if name else task_id
        print(f"Routed background task {display} created (task_id: {task_id}).")
        return
    print(f"Error: {result.get('error', 'Unknown error')}", file=sys.stderr)
    sys.exit(1)


def _default_prompt(kind: str, command: str, target: str, evidence: str) -> str:
    normalized = kind.strip().lower().replace("-", "_")
    if normalized == "test_execution" and command:
        return f"Run this command and summarize the result: {command}"
    if normalized == "code_review" and target:
        return f"Review this target and report findings: {target}"
    if normalized == "patch_candidate":
        if evidence:
            return f"Use this evidence to produce a minimal patch candidate: {evidence}"
        return "Produce a minimal patch candidate with evidence."
    return ""


if __name__ == "__main__":
    main()
