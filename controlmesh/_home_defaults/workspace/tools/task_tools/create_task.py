#!/usr/bin/env python3
"""Create a background task that runs autonomously.

The task runs in the background and delivers its result back to your chat
when complete. You formulate the prompt with all necessary context — the
task agent does NOT have access to the conversation history.

Usage:
    python3 create_task.py [options] "Your task description here"

Options:
    --name NAME        Human-readable task name (e.g. "Flugsuche Paris")
    --provider PROV    Override provider (claude, codex, gemini, claw-code, opencode)
    --model MODEL      Override model (opus, sonnet, flash, etc.)
    --thinking LEVEL   Reasoning effort for codex (low, medium, high)
    --topology NAME    Explicit topology (pipeline, fanout_merge, director_worker, debate_judge)
    --route auto       Let ControlMesh route by WorkUnit capability
    --kind KIND        WorkUnit kind (test_execution, code_review, patch_candidate)
    --command CMD      Command associated with the WorkUnit
    --target TARGET    Review target or scope
    --evidence PATH    Evidence/log path for patch candidates
    --capability CAP   Required capability hint (repeatable)
    --evaluator NAME   Evaluator hint, e.g. foreground

Environment variables CONTROLMESH_AGENT_NAME and CONTROLMESH_INTERAGENT_PORT are
automatically set by the ControlMesh framework.
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
    provider = ""
    model = ""
    thinking = ""
    topology = ""
    route = ""
    workunit_kind = ""
    command = ""
    target = ""
    evidence = ""
    required_capabilities: list[str] = []
    evaluator = ""

    # Parse named options
    while args:
        if args[0] == "--name" and len(args) >= 2:
            name = args[1]
            args = args[2:]
        elif args[0] == "--provider" and len(args) >= 2:
            provider = args[1]
            args = args[2:]
        elif args[0] == "--model" and len(args) >= 2:
            model = args[1]
            args = args[2:]
        elif args[0] == "--thinking" and len(args) >= 2:
            thinking = args[1]
            args = args[2:]
        elif args[0] == "--topology" and len(args) >= 2:
            topology = args[1]
            args = args[2:]
        elif args[0] == "--route" and len(args) >= 2:
            route = args[1]
            args = args[2:]
        elif args[0] in {"--kind", "--workunit-kind"} and len(args) >= 2:
            workunit_kind = args[1]
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
        elif args[0] == "--capability" and len(args) >= 2:
            required_capabilities.append(args[1])
            args = args[2:]
        elif args[0] == "--evaluator" and len(args) >= 2:
            evaluator = args[1]
            args = args[2:]
        else:
            break

    if not args:
        print(
            'Usage: python3 create_task.py [--name NAME] [--provider P] '
            '[--model M] [--thinking L] [--route auto] [--kind KIND] "prompt"',
            file=sys.stderr,
        )
        sys.exit(1)

    prompt = args[0]
    sender = detect_agent_name()

    url = get_api_url("/tasks/create")
    body: dict[str, object] = {"from": sender, "prompt": prompt}
    if name:
        body["name"] = name
    if provider:
        body["provider"] = normalize_provider_name(provider)
    if model:
        body["model"] = model
    if thinking:
        body["thinking"] = thinking
    if topology:
        body["topology"] = topology
    if route:
        body["route"] = route
    if workunit_kind:
        body["workunit_kind"] = workunit_kind
    if command:
        body["command"] = command
    if target:
        body["target"] = target
    if evidence:
        body["evidence"] = evidence
    if required_capabilities:
        body["required_capabilities"] = required_capabilities
    if evaluator:
        body["evaluator"] = evaluator

    # Propagate sender context so task results route back to the originating chat/topic
    chat_id = os.environ.get("CONTROLMESH_CHAT_ID", "")
    topic_id = os.environ.get("CONTROLMESH_TOPIC_ID", "")
    if chat_id:
        body["chat_id"] = int(chat_id)
    if topic_id:
        body["topic_id"] = int(topic_id)

    result = post_json(url, body, timeout=10)

    if result.get("success"):
        task_id = result.get("task_id", "unknown")
        display = f"'{name}'" if name else task_id
        print(
            f"Background task {display} created (task_id: {task_id}). "
            f"The result will be delivered back to your chat when ready."
        )
    else:
        error = result.get("error", "Unknown error")
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
