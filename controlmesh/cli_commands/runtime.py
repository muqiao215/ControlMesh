"""Thin CLI ingress for the autonomous runtime loop."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from pathlib import Path

from controlmesh_runtime import (
    AutonomousPromotionApproval,
    AutonomousRuntimeLoop,
    AutonomousRuntimeLoopRequest,
    FailureClass,
    QueryAction,
    RecoveryContext,
    RecoveryReason,
    ReviewOutcome,
    RuntimeEvidenceIdentity,
    RuntimeStage,
    SignalAction,
    UpdateAction,
    WorkerState,
    WorkerStatus,
)
from controlmesh_runtime.runtime_message_api import query, signal, update


class _CliWorkerController:
    """Minimal single-worker controller for CLI ingress."""

    def __init__(self) -> None:
        self._states: dict[str, WorkerState] = {}

    async def create(self, worker_id: str) -> WorkerState:
        state = WorkerState(worker_id=worker_id, status=WorkerStatus.READY)
        self._states[worker_id] = state
        return state

    async def await_ready(
        self,
        worker_id: str,
        *,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
    ) -> WorkerState:
        del timeout_seconds, poll_interval_seconds
        return self._states.get(worker_id, WorkerState(worker_id=worker_id, status=WorkerStatus.READY))

    async def fetch_state(self, worker_id: str) -> WorkerState | None:
        return self._states.get(worker_id)

    async def restart(self, worker_id: str) -> WorkerState:
        state = WorkerState(worker_id=worker_id, status=WorkerStatus.READY)
        self._states[worker_id] = state
        return state

    async def terminate(self, worker_id: str) -> WorkerState:
        state = WorkerState(worker_id=worker_id, status=WorkerStatus.FINISHED)
        self._states[worker_id] = state
        return state


def cmd_runtime(args: Sequence[str]) -> None:
    """Handle runtime ingress commands."""
    parsed = _build_parser().parse_args(_normalize_args(args))
    if parsed.runtime_action == "run":
        payload = asyncio.run(_run_runtime_ingress(parsed))
    elif parsed.runtime_action == "signal":
        payload = _run_runtime_signal(parsed)
    elif parsed.runtime_action == "query":
        payload = _run_runtime_query(parsed)
    elif parsed.runtime_action == "update":
        payload = _run_runtime_update(parsed)
    else:
        raise SystemExit(1)
    print(json.dumps(payload, ensure_ascii=True))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="controlmesh runtime")
    parser.add_argument("runtime_action", choices=("run", "signal", "query", "update"))
    parser.add_argument("--root", required=True)
    parser.add_argument("--packet-id", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--line", required=True)
    parser.add_argument("--plan-id")
    parser.add_argument("--worker-id")
    parser.add_argument("--recovery-reason", choices=tuple(reason.value for reason in RecoveryReason))
    parser.add_argument("--runtime-stage", choices=tuple(stage.value for stage in RuntimeStage))
    parser.add_argument(
        "--action",
        choices=tuple(action.value for action in SignalAction)
        + tuple(action.value for action in QueryAction)
        + tuple(action.value for action in UpdateAction),
    )
    parser.add_argument("--review-outcome", choices=tuple(outcome.value for outcome in ReviewOutcome))
    parser.add_argument("--review-reason", action="append", default=[])
    parser.add_argument("--latest-completed")
    parser.add_argument("--next-action")
    return parser


def _normalize_args(args: Sequence[str]) -> list[str]:
    commands = [arg for arg in args if not arg.startswith("-")]
    if commands[:1] == ["runtime"]:
        return list(args[1:])
    return list(args)


async def _run_runtime_ingress(args: argparse.Namespace) -> dict[str, object]:
    if args.worker_id is None or args.recovery_reason is None:
        raise SystemExit(1)
    promotion_approval = _build_promotion_approval(args)
    loop = AutonomousRuntimeLoop(
        root=Path(args.root),
        worker_controller=_CliWorkerController(),
    )
    outcome = await loop.run(
        AutonomousRuntimeLoopRequest(
            packet_id=args.packet_id,
            context=RecoveryContext(
                task_id=args.task_id,
                line=args.line,
                worker_id=args.worker_id,
                current_status=WorkerStatus.DEGRADED,
                failure_class=FailureClass.TOOL_RUNTIME,
                recovery_reason=RecoveryReason(args.recovery_reason),
            ),
            runtime_stage=None if args.runtime_stage is None else RuntimeStage(args.runtime_stage),
            promotion_approval=promotion_approval,
        )
    )
    return {
        "packet_id": args.packet_id,
        "task_id": args.task_id,
        "line": args.line,
        "plan_id": outcome.checkpoint.loop_outcome.result.evidence_identity.plan_id,
        "status": outcome.checkpoint.loop_outcome.result.status.value,
        "runtime_runnable": outcome.checkpoint.loop_outcome.runtime_runnable,
        "persisted_event_count": outcome.checkpoint.persisted_event_count,
        "summary_materialized": outcome.summary is not None,
        "promotion_receipt_id": None if outcome.promotion is None else outcome.promotion.receipt_id,
        "applied_triggers": list(outcome.applied_triggers),
        "final_worker_status": (
            None
            if outcome.checkpoint.loop_outcome.final_worker_state is None
            else outcome.checkpoint.loop_outcome.final_worker_state.status.value
        ),
    }


def _run_runtime_signal(args: argparse.Namespace) -> dict[str, object]:
    return signal(
        root=Path(args.root),
        episode=_build_episode(args),
        action=SignalAction(args.action),
    )


def _run_runtime_query(args: argparse.Namespace) -> dict[str, object]:
    return query(
        root=Path(args.root),
        episode=_build_episode(args),
        action=QueryAction(args.action),
    )


def _run_runtime_update(args: argparse.Namespace) -> dict[str, object]:
    if args.action != UpdateAction.PROMOTE.value:
        raise SystemExit(1)
    if args.review_outcome is None or args.latest_completed is None or args.next_action is None:
        raise SystemExit(1)
    return update(
        root=Path(args.root),
        episode=_build_episode(args),
        action=UpdateAction(args.action),
        payload={
            "review_outcome": args.review_outcome,
            "review_reason": list(args.review_reason),
            "latest_completed": args.latest_completed,
            "next_action": args.next_action,
        },
    )


def _build_promotion_approval(args: argparse.Namespace) -> AutonomousPromotionApproval | None:
    if args.review_outcome is None:
        return None
    if args.latest_completed is None or args.next_action is None:
        raise SystemExit(1)
    return AutonomousPromotionApproval(
        review_outcome=ReviewOutcome(args.review_outcome),
        review_reasons=tuple(args.review_reason),
        latest_completed=args.latest_completed,
        next_action=args.next_action,
    )


def _build_episode(args: argparse.Namespace) -> RuntimeEvidenceIdentity:
    if args.plan_id is None:
        raise SystemExit(1)
    return RuntimeEvidenceIdentity(
        packet_id=args.packet_id,
        task_id=args.task_id,
        line=args.line,
        plan_id=args.plan_id,
    )


__all__ = ["cmd_runtime"]
