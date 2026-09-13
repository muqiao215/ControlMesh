"""External-controller CLI for host-job attempts (submit, wait, consume)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Sequence

from controlmesh.errors import CLIError
from controlmesh.runtime.host_job_bridge import (
    OUTCOME_NEEDS_REVIEW,
    HostJobBridgeError,
    await_terminal_event,
    consume_terminal_event,
    read_attempt,
    run_attempt,
)
from controlmesh.workspace.paths import ControlMeshPaths, resolve_paths

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NO_EVENT = 3
EXIT_NEEDS_REVIEW = 4

_USAGE = """Usage:
  controlmesh hostjob run     --job-id ID --parent NAME --command "CMD" [--timeout SECONDS]
  controlmesh hostjob wait    --job-id ID --parent NAME [--wait-timeout SECONDS]
  controlmesh hostjob consume --job-id ID --parent NAME
  controlmesh hostjob status  --job-id ID

Local controller bridge over the durable host-job substrate. `--parent NAME` is the
explicit parent binding: it is persisted with the command digest, workspace and
provenance on the first `run`, and enforced by `wait`/`consume`; it is never inferred.
One execution for uncontended or cooperating concurrent callers — not exactly-once under
crashes: an uncertain dispatch is never replayed automatically. Existing job evidence
without a valid dispatch intent is refused, never adopted. Consumption is atomic across
OS processes and is at-most-once, not guaranteed delivery.

Timeout flags (both `0` = wait forever):
  run   --timeout SECONDS        detach after N seconds, leaving the worker running
  wait  --wait-timeout SECONDS   give up waiting after N seconds
Both commands accept --poll-interval SECONDS (default 0.25).

Exit codes:
  0  a terminal event was returned
  3  no terminal event to consume yet (still running, or already consumed)
  4  needs review: worker fate or dispatch outcome is unconfirmed; no receipt consumed,
     no replay authorized, later genuine completion is still reconcilable
  1  usage, binding mismatch, uncertain/corrupt dispatch intent, or runtime error
"""


def cmd_hostjob(args: Sequence[str]) -> None:
    """Handle `controlmesh hostjob ...` commands."""
    parsed = _build_parser().parse_args(_normalize_args(args))
    try:
        _dispatch(parsed)
    except (HostJobBridgeError, ValueError, CLIError) as exc:
        _print({"error": str(exc)})
        raise SystemExit(EXIT_ERROR) from None


def _dispatch(parsed: argparse.Namespace) -> None:
    action = parsed.hostjob_action
    if action == "run":
        if not parsed.command.strip():
            raise SystemExit(EXIT_ERROR)
        event = asyncio.run(
            run_attempt(
                _paths(),
                job_id=parsed.job_id,
                command=parsed.command,
                parent_agent=parsed.parent,
                job_kind=parsed.kind,
                plan_id=parsed.plan_id,
                source_task_id=parsed.task_id,
                repo=parsed.repo,
                summary=parsed.summary,
                approval_required=parsed.approval_required,
                side_effect=parsed.side_effect,
                cwd=parsed.cwd,
                timeout_seconds=_timeout(parsed.timeout),
                poll_interval_seconds=parsed.poll_interval,
            )
        )
        raise SystemExit(_print_event(event))
    if action == "wait":
        event = asyncio.run(
            await_terminal_event(
                _paths(),
                job_id=parsed.job_id,
                parent_agent=parsed.parent,
                timeout_seconds=_timeout(parsed.wait_timeout),
                poll_interval_seconds=parsed.poll_interval,
            )
        )
        raise SystemExit(_print_event(event))
    if action == "consume":
        event = consume_terminal_event(_paths(), job_id=parsed.job_id, parent_agent=parsed.parent)
        raise SystemExit(_print_event(event))
    if action == "status":
        event = read_attempt(_paths(), job_id=parsed.job_id)
        if event is None:
            raise SystemExit(EXIT_ERROR)
        _print(event)
        raise SystemExit(EXIT_OK)
    raise SystemExit(EXIT_ERROR)


def _timeout(seconds: float) -> float | None:
    """``0`` (or less) means wait until the attempt reaches a terminal state."""
    return None if seconds <= 0 else seconds


def _paths() -> ControlMeshPaths:
    """Resolve paths with an explicit ``CONTROLMESH_HOME`` override when set."""
    home = os.environ.get("CONTROLMESH_HOME", "").strip()
    if home:
        return resolve_paths(controlmesh_home=home)
    from controlmesh.__main__ import load_config

    return resolve_paths(controlmesh_home=load_config().controlmesh_home or None)


def _print(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=True))


def _print_event(event: dict[str, object] | None) -> int:
    if event is None:
        _print({"terminal_event": None})
        return EXIT_NO_EVENT
    _print(event)
    return EXIT_NEEDS_REVIEW if event.get("outcome") == OUTCOME_NEEDS_REVIEW else EXIT_OK


def _normalize_args(args: Sequence[str]) -> list[str]:
    if args and args[0] == "hostjob":
        return list(args[1:])
    return list(args)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="controlmesh hostjob", description=_USAGE)
    parser.add_argument("hostjob_action", choices=("run", "wait", "consume", "status"))
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--parent", default="")
    parser.add_argument("--command", default="")
    parser.add_argument("--kind", default="external_cli")
    parser.add_argument("--plan-id", default="")
    parser.add_argument("--task-id", default="")
    parser.add_argument("--repo", default="")
    parser.add_argument("--summary", default="")
    parser.add_argument("--cwd", default="")
    parser.add_argument("--timeout", type=float, default=0.0, help="run: detach after N seconds (0 = wait forever)")
    parser.add_argument("--wait-timeout", type=float, default=10.0, help="wait: give up after N seconds (0 = wait forever)")
    parser.add_argument("--poll-interval", type=float, default=0.25)
    parser.add_argument("--approval-required", action="store_true")
    parser.add_argument("--side-effect", action="store_true")
    return parser


__all__ = ["cmd_hostjob"]
