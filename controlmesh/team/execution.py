"""TaskHub-backed topology execution seam."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from controlmesh.team.models import (
    TeamDirectorDecision,
    TeamJudgeDecision,
    TeamReducedTopologyResult,
    TeamStructuredResult,
    TeamTopologyCheckpoint,
    TeamTopologyExecutionState,
    TeamTopologyInterruptionState,
)

if TYPE_CHECKING:
    from controlmesh.tasks.hub import TaskHub


def _utc_now_iso(at: datetime | None = None) -> str:
    """Return a normalized UTC ISO-8601 timestamp."""
    return (at or datetime.now(UTC)).astimezone(UTC).isoformat()


def _compress_text(value: str, *, limit: int = 140) -> str:
    """Project longer result text into a compact topology progress summary."""
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3].rstrip()}..."


def _unique_roles(*groups: list[str]) -> list[str]:
    """Return roles in first-seen order without duplicates."""
    seen: set[str] = set()
    ordered: list[str] = []
    for group in groups:
        for role in group:
            if role not in seen:
                seen.add(role)
                ordered.append(role)
    return ordered


class TeamTopologyExecutionSpine:
    """Persist topology-local execution state on top of the TaskHub lifecycle."""

    def __init__(self, hub: TaskHub) -> None:
        self._hub = hub

    def read(self, task_id: str) -> TeamTopologyExecutionState | None:
        """Load the current topology execution state for a task."""
        raw = self._hub.read_topology_state(task_id)
        if raw is None:
            return None
        return TeamTopologyExecutionState.model_validate(raw)

    def start(
        self,
        task_id: str,
        *,
        topology: str,
        active_roles: list[str] | None = None,
        latest_summary: str | None = None,
        round_index: int | None = None,
        round_limit: int | None = None,
        at: datetime | None = None,
    ) -> TeamTopologyExecutionState:
        """Initialize the execution seam for one TaskHub-backed task."""
        if self.read(task_id) is not None:
            msg = f"Topology execution state already exists for task '{task_id}'"
            raise ValueError(msg)
        now = _utc_now_iso(at)
        state = TeamTopologyExecutionState(
            task_id=task_id,
            execution_id=f"{task_id}-exec",
            topology=topology,
            checkpoints=[
                TeamTopologyCheckpoint(
                    checkpoint_id="cp_0001",
                    topology=topology,
                    substage="planning",
                    phase_status="in_progress",
                    active_roles=list(active_roles or []),
                    latest_summary=latest_summary,
                    round_index=round_index,
                    round_limit=round_limit,
                    recorded_at=now,
                )
            ],
            created_at=now,
            updated_at=now,
        )
        return self._write(state)

    def record_checkpoint(
        self,
        task_id: str,
        *,
        substage: str,
        phase_status: str,
        active_roles: list[str] | None = None,
        completed_roles: list[str] | None = None,
        latest_summary: str | None = None,
        waiting_on: str | None = None,
        artifact_count: int = 0,
        needs_parent_input: bool = False,
        repair_state: str | None = None,
        round_index: int | None = None,
        round_limit: int | None = None,
        result: TeamStructuredResult | None = None,
        reduced_result: TeamReducedTopologyResult | None = None,
        at: datetime | None = None,
    ) -> TeamTopologyExecutionState:
        """Append one checkpoint without introducing topology-specific dispatch logic."""
        state = self._require(task_id)
        checkpoint = TeamTopologyCheckpoint(
            checkpoint_id=self._next_checkpoint_id(state),
            topology=state.topology,
            substage=substage,
            phase_status=phase_status,
            active_roles=list(active_roles or []),
            completed_roles=list(completed_roles or []),
            latest_summary=latest_summary,
            waiting_on=waiting_on,
            artifact_count=artifact_count,
            needs_parent_input=needs_parent_input,
            repair_state=repair_state,
            round_index=round_index,
            round_limit=round_limit,
            result=result,
            reduced_result=reduced_result,
            recorded_at=_utc_now_iso(at),
        )
        updated = state.model_copy(
            update={
                "checkpoints": [*state.checkpoints, checkpoint],
                "updated_at": checkpoint.recorded_at,
            }
        )
        return self._write(updated)

    def interrupt_for_parent(
        self,
        task_id: str,
        *,
        requested_by_role: str,
        question: str,
        waiting_on: str,
        latest_summary: str | None = None,
        resume_phase_status: str = "in_progress",
        completed_roles: list[str] | None = None,
        artifact_count: int | None = None,
        result: TeamStructuredResult | None = None,
        repair_state: str | None = None,
        round_index: int | None = None,
        round_limit: int | None = None,
        at: datetime | None = None,
    ) -> TeamTopologyExecutionState:
        """Persist a parent-input interruption on top of the current checkpoint."""
        state = self._require(task_id)
        latest = state.current_checkpoint
        now = _utc_now_iso(at)
        blocked_checkpoint = TeamTopologyCheckpoint(
            checkpoint_id=self._next_checkpoint_id(state),
            topology=state.topology,
            substage="waiting_parent",
            phase_status="blocked",
            active_roles=[requested_by_role],
            completed_roles=list(completed_roles or latest.completed_roles),
            latest_summary=latest_summary,
            waiting_on=waiting_on,
            artifact_count=latest.artifact_count if artifact_count is None else artifact_count,
            needs_parent_input=True,
            repair_state=repair_state,
            round_index=latest.round_index if round_index is None else round_index,
            round_limit=latest.round_limit if round_limit is None else round_limit,
            result=result,
            recorded_at=now,
        )
        interruption = TeamTopologyInterruptionState(
            status="waiting_parent",
            requested_by_role=requested_by_role,
            question=question,
            waiting_on=waiting_on,
            raised_at=now,
            resume_substage=latest.substage,
            resume_phase_status=resume_phase_status,
            resume_count=state.interruption.resume_count,
            last_parent_input=state.interruption.last_parent_input,
            last_resumed_at=state.interruption.last_resumed_at,
        )
        updated = state.model_copy(
            update={
                "checkpoints": [*state.checkpoints, blocked_checkpoint],
                "interruption": interruption,
                "updated_at": now,
            }
        )
        return self._write(updated)

    def resume_from_parent(
        self,
        task_id: str,
        *,
        parent_input: str,
        latest_summary: str | None = None,
        active_roles: list[str] | None = None,
        completed_roles: list[str] | None = None,
        round_index: int | None = None,
        round_limit: int | None = None,
        at: datetime | None = None,
    ) -> TeamTopologyExecutionState:
        """Clear a parent-input interruption and re-enter the saved substage."""
        state = self._require(task_id)
        if state.interruption.status != "waiting_parent":
            msg = f"Task '{task_id}' is not waiting on parent input"
            raise ValueError(msg)

        latest = state.current_checkpoint
        resume_substage = state.interruption.resume_substage
        assert resume_substage is not None  # model validation guarantees this while waiting
        now = _utc_now_iso(at)
        resumed_checkpoint = TeamTopologyCheckpoint(
            checkpoint_id=self._next_checkpoint_id(state),
            topology=state.topology,
            substage=resume_substage,
            phase_status=state.interruption.resume_phase_status or "in_progress",
            active_roles=list(active_roles or latest.active_roles),
            completed_roles=list(completed_roles or latest.completed_roles),
            latest_summary=latest_summary,
            artifact_count=latest.artifact_count,
            round_index=latest.round_index if round_index is None else round_index,
            round_limit=latest.round_limit if round_limit is None else round_limit,
            recorded_at=now,
        )
        interruption = TeamTopologyInterruptionState(
            status="idle",
            resume_count=state.interruption.resume_count + 1,
            last_parent_input=parent_input,
            last_resumed_at=now,
        )
        updated = state.model_copy(
            update={
                "checkpoints": [*state.checkpoints, resumed_checkpoint],
                "interruption": interruption,
                "updated_at": now,
            }
        )
        return self._write(updated)

    def _require(self, task_id: str) -> TeamTopologyExecutionState:
        state = self.read(task_id)
        if state is None:
            msg = f"Topology execution state for task '{task_id}' was not initialized"
            raise ValueError(msg)
        return state

    def _next_checkpoint_id(self, state: TeamTopologyExecutionState) -> str:
        return f"cp_{len(state.checkpoints) + 1:04d}"

    def _write(self, state: TeamTopologyExecutionState) -> TeamTopologyExecutionState:
        self._hub.write_topology_state(state.task_id, state.model_dump(mode="json"))
        return state

    @property
    def parallel_limit(self) -> int:
        """Expose the TaskHub-backed bounded parallel budget to topology runtimes."""
        return int(self._hub._config.max_parallel)


class TeamPipelineRuntime:
    """Pipeline-only execution behavior layered on the Step 2 persistence seam."""

    def __init__(self, spine: TeamTopologyExecutionSpine) -> None:
        self._spine = spine

    def read(self, task_id: str) -> TeamTopologyExecutionState | None:
        """Load the current pipeline execution state."""
        return self._spine.read(task_id)

    def start(
        self,
        task_id: str,
        *,
        planning_summary: str,
        planner_role: str = "planner",
        at: datetime | None = None,
    ) -> TeamTopologyExecutionState:
        """Initialize the pipeline run in the planning substage."""
        return self._spine.start(
            task_id,
            topology="pipeline",
            active_roles=[planner_role],
            latest_summary=_compress_text(planning_summary),
            at=at,
        )

    def dispatch_worker(
        self,
        task_id: str,
        *,
        worker_role: str = "worker",
        latest_summary: str | None = None,
        at: datetime | None = None,
    ) -> TeamTopologyExecutionState:
        """Advance the pipeline from planning into the ordered worker pass."""
        state = self._require(task_id, expected_substage="planning")
        planner_role = self._planner_role(state)
        summary = latest_summary or state.current_checkpoint.latest_summary or "Planner dispatched worker."
        return self._spine.record_checkpoint(
            task_id,
            substage="worker_running",
            phase_status="in_progress",
            active_roles=[worker_role],
            completed_roles=[planner_role],
            latest_summary=_compress_text(summary),
            artifact_count=state.current_checkpoint.artifact_count,
            at=at,
        )

    def record_worker_result(
        self,
        task_id: str,
        result: TeamStructuredResult,
        *,
        reviewer_role: str = "reviewer",
        at: datetime | None = None,
    ) -> TeamTopologyExecutionState:
        """Persist the worker pass and dispatch the reviewer pass."""
        state = self._require(task_id, expected_substage="worker_running")
        self._ensure_result(result, expected_substage="worker_running")
        if result.status == "completed":
            return self._spine.record_checkpoint(
                task_id,
                substage="review_running",
                phase_status="in_progress",
                active_roles=[reviewer_role],
                completed_roles=self._completed_roles(state, result.worker_role),
                latest_summary=self._result_summary(result),
                artifact_count=len(result.artifacts),
                result=result,
                at=at,
            )
        if result.status == "failed":
            reduced = self._terminal_reduced_result(result)
            return self._spine.record_checkpoint(
                task_id,
                substage="failed",
                phase_status="failed",
                active_roles=[],
                completed_roles=self._completed_roles(state, result.worker_role),
                latest_summary=self._reduced_summary(reduced),
                artifact_count=len(reduced.selected_artifacts),
                result=result,
                reduced_result=reduced,
                at=at,
            )
        msg = f"pipeline worker pass does not accept status '{result.status}'"
        raise ValueError(msg)

    def record_review_result(
        self,
        task_id: str,
        result: TeamStructuredResult,
        *,
        parent_question: str | None = None,
        waiting_on: str | None = None,
        repair_worker_role: str = "worker",
        at: datetime | None = None,
    ) -> TeamTopologyExecutionState:
        """Persist the reviewer pass and drive terminal, waiting, or repair transitions."""
        state = self._require(task_id, expected_substage="review_running")
        self._ensure_result(result, expected_substage="review_running")
        if result.status in {"completed", "failed"}:
            reduced = self._reduce_review_result(state, result)
            substage = "completed" if result.status == "completed" else "failed"
            phase_status = "completed" if result.status == "completed" else "failed"
            return self._spine.record_checkpoint(
                task_id,
                substage=substage,
                phase_status=phase_status,
                active_roles=[],
                completed_roles=self._completed_roles(state, result.worker_role),
                latest_summary=self._reduced_summary(reduced),
                artifact_count=len(reduced.selected_artifacts),
                result=result,
                reduced_result=reduced,
                at=at,
            )
        if result.status == "needs_parent_input":
            if parent_question is None or waiting_on is None:
                msg = "parent_question and waiting_on are required for pipeline review interruptions"
                raise ValueError(msg)
            return self._spine.interrupt_for_parent(
                task_id,
                requested_by_role=result.worker_role,
                question=parent_question,
                waiting_on=waiting_on,
                latest_summary=self._result_summary(result),
                completed_roles=list(state.current_checkpoint.completed_roles),
                artifact_count=max(state.current_checkpoint.artifact_count, len(result.artifacts)),
                result=result,
                at=at,
            )
        if result.status == "needs_repair":
            repair_role = self._repair_worker_role(state, default=repair_worker_role)
            return self._spine.record_checkpoint(
                task_id,
                substage="repairing",
                phase_status="in_progress",
                active_roles=[repair_role],
                completed_roles=[self._planner_role(state)],
                latest_summary=self._result_summary(result),
                artifact_count=max(state.current_checkpoint.artifact_count, len(result.artifacts)),
                repair_state=result.repair_hint,
                result=result,
                at=at,
            )
        msg = f"pipeline review pass does not accept status '{result.status}'"
        raise ValueError(msg)

    def record_repair_result(
        self,
        task_id: str,
        result: TeamStructuredResult,
        *,
        reviewer_role: str = "reviewer",
        at: datetime | None = None,
    ) -> TeamTopologyExecutionState:
        """Persist the repair pass and re-enter review for a final decision."""
        state = self._require(task_id, expected_substage="repairing")
        self._ensure_result(result, expected_substage="repairing")
        if result.status == "completed":
            return self._spine.record_checkpoint(
                task_id,
                substage="review_running",
                phase_status="in_progress",
                active_roles=[reviewer_role],
                completed_roles=self._completed_roles(state, result.worker_role),
                latest_summary=self._result_summary(result),
                artifact_count=len(result.artifacts),
                result=result,
                at=at,
            )
        if result.status == "failed":
            reduced = self._terminal_reduced_result(result)
            return self._spine.record_checkpoint(
                task_id,
                substage="failed",
                phase_status="failed",
                active_roles=[],
                completed_roles=self._completed_roles(state, result.worker_role),
                latest_summary=self._reduced_summary(reduced),
                artifact_count=len(reduced.selected_artifacts),
                result=result,
                reduced_result=reduced,
                at=at,
            )
        msg = f"pipeline repair pass does not accept status '{result.status}'"
        raise ValueError(msg)

    def resume_from_parent(
        self,
        task_id: str,
        *,
        parent_input: str,
        latest_summary: str | None = None,
        at: datetime | None = None,
    ) -> TeamTopologyExecutionState:
        """Resume a blocked reviewer pass without bypassing the Step 2 seam."""
        state = self._require(task_id, expected_substage="waiting_parent")
        requested_by = state.interruption.requested_by_role
        active_roles = [requested_by] if requested_by is not None else None
        summary = latest_summary or state.current_checkpoint.latest_summary
        return self._spine.resume_from_parent(
            task_id,
            parent_input=parent_input,
            latest_summary=summary,
            active_roles=active_roles,
            completed_roles=list(state.current_checkpoint.completed_roles),
            at=at,
        )

    def _require(self, task_id: str, *, expected_substage: str | None = None) -> TeamTopologyExecutionState:
        state = self._spine.read(task_id)
        if state is None:
            msg = f"Topology execution state for task '{task_id}' was not initialized"
            raise ValueError(msg)
        if state.topology != "pipeline":
            msg = f"Task '{task_id}' is not using the pipeline topology"
            raise ValueError(msg)
        if expected_substage is not None and state.current_checkpoint.substage != expected_substage:
            msg = (
                f"Task '{task_id}' must be in '{expected_substage}' before this pipeline step; "
                f"current substage is '{state.current_checkpoint.substage}'"
            )
            raise ValueError(msg)
        return state

    def _ensure_result(self, result: TeamStructuredResult, *, expected_substage: str) -> None:
        if result.topology != "pipeline":
            msg = "pipeline runtime only accepts pipeline structured results"
            raise ValueError(msg)
        if result.substage != expected_substage:
            msg = (
                f"pipeline runtime expected a '{expected_substage}' result, "
                f"received '{result.substage}'"
            )
            raise ValueError(msg)

    def _planner_role(self, state: TeamTopologyExecutionState) -> str:
        if state.checkpoints and state.checkpoints[0].active_roles:
            return state.checkpoints[0].active_roles[0]
        return "planner"

    def _completed_roles(self, state: TeamTopologyExecutionState, *additional: str) -> list[str]:
        return _unique_roles([self._planner_role(state)], list(state.current_checkpoint.completed_roles), list(additional))

    def _repair_worker_role(self, state: TeamTopologyExecutionState, *, default: str) -> str:
        previous = state.current_checkpoint.result
        if previous is not None and previous.worker_role != "reviewer":
            return previous.worker_role
        for checkpoint in reversed(state.checkpoints):
            if checkpoint.result is not None and checkpoint.result.substage in {"worker_running", "repairing"}:
                return checkpoint.result.worker_role
        return default

    def _review_input_result(self, state: TeamTopologyExecutionState) -> TeamStructuredResult:
        current = state.current_checkpoint.result
        if current is not None and current.substage in {"worker_running", "repairing"}:
            return current
        for checkpoint in reversed(state.checkpoints):
            candidate = checkpoint.result
            if candidate is not None and candidate.substage in {"worker_running", "repairing"}:
                return candidate
        msg = "review checkpoints require a structured worker input result before terminal reduction"
        raise ValueError(msg)

    def _reduce_review_result(
        self,
        state: TeamTopologyExecutionState,
        review_result: TeamStructuredResult,
    ) -> TeamReducedTopologyResult:
        worker_result = self._review_input_result(state)
        selected_evidence = review_result.evidence or worker_result.evidence
        selected_artifacts = review_result.artifacts or worker_result.artifacts
        return TeamReducedTopologyResult(
            topology="pipeline",
            final_status=review_result.status,
            reduced_summary=review_result.summary,
            selected_evidence=list(selected_evidence),
            selected_artifacts=list(selected_artifacts),
            next_action=review_result.next_action,
        )

    def _terminal_reduced_result(self, result: TeamStructuredResult) -> TeamReducedTopologyResult:
        return TeamReducedTopologyResult(
            topology="pipeline",
            final_status=result.status,
            reduced_summary=result.summary,
            selected_evidence=list(result.evidence),
            selected_artifacts=list(result.artifacts),
            next_action=result.next_action,
        )

    def _result_summary(self, result: TeamStructuredResult) -> str:
        parts = [f"{result.worker_role}: {_compress_text(result.summary, limit=96)}"]
        if result.evidence:
            parts.append(f"{len(result.evidence)} evidence")
        if result.artifacts:
            parts.append(f"{len(result.artifacts)} artifacts")
        if result.status == "needs_repair" and result.repair_hint is not None:
            parts.append(f"repair: {_compress_text(result.repair_hint, limit=40)}")
        elif result.next_action is not None:
            parts.append(_compress_text(result.next_action, limit=40))
        return " | ".join(parts)

    def _reduced_summary(self, reduced: TeamReducedTopologyResult) -> str:
        parts = [_compress_text(reduced.reduced_summary, limit=104)]
        if reduced.selected_evidence:
            parts.append(f"{len(reduced.selected_evidence)} evidence")
        if reduced.selected_artifacts:
            parts.append(f"{len(reduced.selected_artifacts)} artifacts")
        if reduced.next_action is not None:
            parts.append(_compress_text(reduced.next_action, limit=40))
        return " | ".join(parts)


class TeamFanoutMergeRuntime:
    """fanout_merge execution behavior layered on the Step 2 persistence seam."""

    def __init__(self, spine: TeamTopologyExecutionSpine) -> None:
        self._spine = spine

    def read(self, task_id: str) -> TeamTopologyExecutionState | None:
        """Load the current fanout execution state."""
        return self._spine.read(task_id)

    def start(
        self,
        task_id: str,
        *,
        planning_summary: str,
        coordinator_role: str = "coordinator",
        at: datetime | None = None,
    ) -> TeamTopologyExecutionState:
        """Initialize the fanout run in the planning substage."""
        return self._spine.start(
            task_id,
            topology="fanout_merge",
            active_roles=[coordinator_role],
            latest_summary=_compress_text(planning_summary),
            at=at,
        )

    def dispatch_workers(
        self,
        task_id: str,
        *,
        worker_roles: list[str],
        latest_summary: str | None = None,
        at: datetime | None = None,
    ) -> TeamTopologyExecutionState:
        """Advance the fanout run into a bounded parallel dispatch batch."""
        state = self._require(task_id, expected_substage="planning")
        if not worker_roles:
            msg = "fanout dispatch requires at least one worker role"
            raise ValueError(msg)
        limit = self._spine.parallel_limit
        if len(worker_roles) > limit:
            msg = (
                f"fanout dispatch requested {len(worker_roles)} workers but the bounded "
                f"parallel limit is {limit}"
            )
            raise ValueError(msg)
        coordinator_role = self._coordinator_role(state)
        summary = latest_summary or self._dispatch_summary(worker_roles, limit=limit)
        return self._spine.record_checkpoint(
            task_id,
            substage="dispatching",
            phase_status="in_progress",
            active_roles=list(worker_roles),
            completed_roles=[coordinator_role],
            latest_summary=_compress_text(summary),
            artifact_count=0,
            at=at,
        )

    def record_worker_results(
        self,
        task_id: str,
        results: list[TeamStructuredResult],
        *,
        reducer_role: str = "reducer",
        at: datetime | None = None,
    ) -> TeamTopologyExecutionState:
        """Persist one fanout collection batch and enter reduction or terminal failure."""
        state = self._require(task_id, expected_substage="dispatching")
        if not results:
            msg = "fanout collection requires at least one worker result"
            raise ValueError(msg)

        current_state = state
        for result in results:
            self._ensure_result(result, expected_substage="collecting")
            current_state = self._spine.record_checkpoint(
                task_id,
                substage="collecting",
                phase_status="in_progress",
                active_roles=[result.worker_role],
                completed_roles=list(current_state.current_checkpoint.completed_roles),
                latest_summary=self._result_summary(result),
                artifact_count=current_state.current_checkpoint.artifact_count + len(result.artifacts),
                result=result,
                at=at,
            )

        collected = self._collecting_results(current_state)
        successful = [result for result in collected if result.status == "completed"]
        failed = [result for result in collected if result.status == "failed"]
        coordinator_role = self._coordinator_role(current_state)

        if not successful:
            reduced = self._failed_worker_batch_result(failed)
            return self._spine.record_checkpoint(
                task_id,
                substage="failed",
                phase_status="failed",
                active_roles=[],
                completed_roles=[coordinator_role],
                latest_summary=self._reduced_summary(reduced),
                artifact_count=len(reduced.selected_artifacts),
                reduced_result=reduced,
                at=at,
            )

        summary = self._worker_rollup_summary(successful, failed)
        return self._spine.record_checkpoint(
            task_id,
            substage="reducing",
            phase_status="in_progress",
            active_roles=[reducer_role],
            completed_roles=_unique_roles(
                [coordinator_role],
                [result.worker_role for result in successful],
            ),
            latest_summary=summary,
            artifact_count=sum(len(result.artifacts) for result in successful),
            at=at,
        )

    def record_reducer_result(
        self,
        task_id: str,
        result: TeamStructuredResult,
        *,
        parent_question: str | None = None,
        waiting_on: str | None = None,
        repair_worker_role: str = "coordinator",
        at: datetime | None = None,
    ) -> TeamTopologyExecutionState:
        """Persist the reducer pass and drive terminal, waiting, or repair transitions."""
        state = self._require(task_id, expected_substage="reducing")
        self._ensure_result(result, expected_substage="reducing")
        if result.status in {"completed", "failed"}:
            reduced = self._reduce_reducer_result(state, result)
            substage = "completed" if result.status == "completed" else "failed"
            phase_status = "completed" if result.status == "completed" else "failed"
            return self._spine.record_checkpoint(
                task_id,
                substage=substage,
                phase_status=phase_status,
                active_roles=[],
                completed_roles=self._completed_roles(state, result.worker_role),
                latest_summary=self._reduced_summary(reduced),
                artifact_count=len(reduced.selected_artifacts),
                result=result,
                reduced_result=reduced,
                at=at,
            )
        if result.status == "needs_parent_input":
            if parent_question is None or waiting_on is None:
                msg = "parent_question and waiting_on are required for fanout reducer interruptions"
                raise ValueError(msg)
            return self._spine.interrupt_for_parent(
                task_id,
                requested_by_role=result.worker_role,
                question=parent_question,
                waiting_on=waiting_on,
                latest_summary=self._result_summary(result),
                completed_roles=list(state.current_checkpoint.completed_roles),
                artifact_count=max(state.current_checkpoint.artifact_count, len(result.artifacts)),
                result=result,
                at=at,
            )
        if result.status == "needs_repair":
            return self._spine.record_checkpoint(
                task_id,
                substage="repairing",
                phase_status="in_progress",
                active_roles=[repair_worker_role],
                completed_roles=list(state.current_checkpoint.completed_roles),
                latest_summary=self._result_summary(result),
                artifact_count=max(state.current_checkpoint.artifact_count, len(result.artifacts)),
                repair_state=result.repair_hint,
                result=result,
                at=at,
            )
        msg = f"fanout reducer pass does not accept status '{result.status}'"
        raise ValueError(msg)

    def resume_from_parent(
        self,
        task_id: str,
        *,
        parent_input: str,
        latest_summary: str | None = None,
        at: datetime | None = None,
    ) -> TeamTopologyExecutionState:
        """Resume a blocked reducer pass without bypassing the Step 2 seam."""
        state = self._require(task_id, expected_substage="waiting_parent")
        requested_by = state.interruption.requested_by_role
        active_roles = [requested_by] if requested_by is not None else None
        summary = latest_summary or state.current_checkpoint.latest_summary
        return self._spine.resume_from_parent(
            task_id,
            parent_input=parent_input,
            latest_summary=summary,
            active_roles=active_roles,
            completed_roles=list(state.current_checkpoint.completed_roles),
            at=at,
        )

    def record_repair_result(
        self,
        task_id: str,
        result: TeamStructuredResult,
        *,
        reducer_role: str = "reducer",
        at: datetime | None = None,
    ) -> TeamTopologyExecutionState:
        """Persist a repair pass and return to reduction."""
        state = self._require(task_id, expected_substage="repairing")
        self._ensure_result(result, expected_substage="repairing")
        if result.status == "completed":
            return self._spine.record_checkpoint(
                task_id,
                substage="reducing",
                phase_status="in_progress",
                active_roles=[reducer_role],
                completed_roles=self._completed_roles(state, result.worker_role),
                latest_summary=self._result_summary(result),
                artifact_count=max(state.current_checkpoint.artifact_count, len(result.artifacts)),
                result=result,
                at=at,
            )
        if result.status == "failed":
            reduced = TeamReducedTopologyResult(
                topology="fanout_merge",
                final_status="failed",
                reduced_summary=result.summary,
                selected_evidence=list(result.evidence),
                selected_artifacts=list(result.artifacts),
                next_action=result.next_action,
            )
            return self._spine.record_checkpoint(
                task_id,
                substage="failed",
                phase_status="failed",
                active_roles=[],
                completed_roles=list(state.current_checkpoint.completed_roles),
                latest_summary=self._reduced_summary(reduced),
                artifact_count=len(reduced.selected_artifacts),
                result=result,
                reduced_result=reduced,
                at=at,
            )
        msg = f"fanout repair pass does not accept status '{result.status}'"
        raise ValueError(msg)

    def _require(self, task_id: str, *, expected_substage: str | None = None) -> TeamTopologyExecutionState:
        state = self._spine.read(task_id)
        if state is None:
            msg = f"Topology execution state for task '{task_id}' was not initialized"
            raise ValueError(msg)
        if state.topology != "fanout_merge":
            msg = f"Task '{task_id}' is not using the fanout_merge topology"
            raise ValueError(msg)
        if expected_substage is not None and state.current_checkpoint.substage != expected_substage:
            msg = (
                f"Task '{task_id}' must be in '{expected_substage}' before this fanout step; "
                f"current substage is '{state.current_checkpoint.substage}'"
            )
            raise ValueError(msg)
        return state

    def _ensure_result(self, result: TeamStructuredResult, *, expected_substage: str) -> None:
        if result.topology != "fanout_merge":
            msg = "fanout runtime only accepts fanout_merge structured results"
            raise ValueError(msg)
        if result.substage != expected_substage:
            msg = (
                f"fanout runtime expected a '{expected_substage}' result, "
                f"received '{result.substage}'"
            )
            raise ValueError(msg)

    def _coordinator_role(self, state: TeamTopologyExecutionState) -> str:
        if state.checkpoints and state.checkpoints[0].active_roles:
            return state.checkpoints[0].active_roles[0]
        return "coordinator"

    def _completed_roles(self, state: TeamTopologyExecutionState, *additional: str) -> list[str]:
        return _unique_roles(
            [self._coordinator_role(state)],
            list(state.current_checkpoint.completed_roles),
            list(additional),
        )

    def _collecting_results(self, state: TeamTopologyExecutionState) -> list[TeamStructuredResult]:
        return [
            checkpoint.result
            for checkpoint in state.checkpoints
            if checkpoint.result is not None and checkpoint.result.substage == "collecting"
        ]

    def _reduce_reducer_result(
        self,
        state: TeamTopologyExecutionState,
        reducer_result: TeamStructuredResult,
    ) -> TeamReducedTopologyResult:
        successful = [
            result for result in self._collecting_results(state) if result.status == "completed"
        ]
        selected_evidence = reducer_result.evidence or [
            evidence
            for result in successful
            for evidence in result.evidence
        ]
        selected_artifacts = reducer_result.artifacts or [
            artifact
            for result in successful
            for artifact in result.artifacts
        ]
        return TeamReducedTopologyResult(
            topology="fanout_merge",
            final_status=reducer_result.status,
            reduced_summary=reducer_result.summary,
            selected_evidence=list(selected_evidence),
            selected_artifacts=list(selected_artifacts),
            next_action=reducer_result.next_action,
        )

    def _failed_worker_batch_result(
        self,
        failed: list[TeamStructuredResult],
    ) -> TeamReducedTopologyResult:
        summary = "All fanout workers failed before reduction."
        if failed:
            summary = (
                f"All fanout workers failed before reduction: "
                f"{', '.join(result.worker_role for result in failed)}."
            )
        return TeamReducedTopologyResult(
            topology="fanout_merge",
            final_status="failed",
            reduced_summary=summary,
            selected_evidence=[
                evidence
                for result in failed
                for evidence in result.evidence
            ],
            selected_artifacts=[
                artifact
                for result in failed
                for artifact in result.artifacts
            ],
        )

    def _dispatch_summary(self, worker_roles: list[str], *, limit: int) -> str:
        roles = ", ".join(worker_roles)
        return f"Dispatching {len(worker_roles)}/{limit} bounded parallel workers: {roles}."

    def _worker_rollup_summary(
        self,
        successful: list[TeamStructuredResult],
        failed: list[TeamStructuredResult],
    ) -> str:
        success_roles = ", ".join(result.worker_role for result in successful)
        parts = [
            f"{len(successful)} worker results ready for reduction: {success_roles}.",
        ]
        if failed:
            failed_roles = ", ".join(result.worker_role for result in failed)
            parts.append(f"partial failure: {len(failed)} failed ({failed_roles})")
        return " ".join(parts)

    def _result_summary(self, result: TeamStructuredResult) -> str:
        parts = [f"{result.worker_role}: {_compress_text(result.summary, limit=96)}"]
        if result.evidence:
            parts.append(f"{len(result.evidence)} evidence")
        if result.artifacts:
            parts.append(f"{len(result.artifacts)} artifacts")
        if result.status == "needs_repair" and result.repair_hint is not None:
            parts.append(f"repair: {_compress_text(result.repair_hint, limit=40)}")
        elif result.next_action is not None:
            parts.append(_compress_text(result.next_action, limit=40))
        return " | ".join(parts)

    def _reduced_summary(self, reduced: TeamReducedTopologyResult) -> str:
        parts = [_compress_text(reduced.reduced_summary, limit=104)]
        if reduced.selected_evidence:
            parts.append(f"{len(reduced.selected_evidence)} evidence")
        if reduced.selected_artifacts:
            parts.append(f"{len(reduced.selected_artifacts)} artifacts")
        if reduced.next_action is not None:
            parts.append(_compress_text(reduced.next_action, limit=40))
        return " | ".join(parts)


class TeamDirectorWorkerRuntime:
    """director_worker execution behavior layered on the Step 2 persistence seam."""

    def __init__(
        self,
        spine: TeamTopologyExecutionSpine,
        *,
        max_rounds: int = 3,
        max_parent_interruptions: int = 1,
        max_repair_cycles_per_run: int = 1,
        max_parallel_workers_per_round: int | None = None,
        max_total_worker_dispatches: int | None = None,
    ) -> None:
        if max_rounds < 1:
            raise ValueError("max_rounds must be greater than or equal to 1")
        if max_parent_interruptions < 0:
            raise ValueError("max_parent_interruptions must be greater than or equal to 0")
        if max_repair_cycles_per_run < 0:
            raise ValueError("max_repair_cycles_per_run must be greater than or equal to 0")

        parallel_limit = spine.parallel_limit
        effective_parallel = max_parallel_workers_per_round or parallel_limit
        if effective_parallel < 1:
            raise ValueError("max_parallel_workers_per_round must be greater than or equal to 1")
        if effective_parallel > parallel_limit:
            msg = (
                "max_parallel_workers_per_round must not exceed the TaskHub bounded parallel "
                f"limit of {parallel_limit}"
            )
            raise ValueError(msg)

        total_dispatch_limit = max_total_worker_dispatches or (max_rounds * effective_parallel)
        if total_dispatch_limit < 1:
            raise ValueError("max_total_worker_dispatches must be greater than or equal to 1")

        self._spine = spine
        self._max_rounds = max_rounds
        self._max_parent_interruptions = max_parent_interruptions
        self._max_repair_cycles_per_run = max_repair_cycles_per_run
        self._max_parallel_workers_per_round = effective_parallel
        self._max_total_worker_dispatches = total_dispatch_limit

    def read(self, task_id: str) -> TeamTopologyExecutionState | None:
        """Load the current director_worker execution state."""
        return self._spine.read(task_id)

    def start(
        self,
        task_id: str,
        *,
        planning_summary: str,
        director_role: str = "director",
        round_limit: int | None = None,
        at: datetime | None = None,
    ) -> TeamTopologyExecutionState:
        """Initialize the director_worker run in the planning substage."""
        effective_round_limit = round_limit or self._max_rounds
        if effective_round_limit < 1:
            raise ValueError("round_limit must be greater than or equal to 1")
        if effective_round_limit > self._max_rounds:
            msg = (
                "round_limit must not exceed the configured director_worker max_rounds "
                f"budget of {self._max_rounds}"
            )
            raise ValueError(msg)
        return self._spine.start(
            task_id,
            topology="director_worker",
            active_roles=[director_role],
            latest_summary=_compress_text(planning_summary),
            round_index=1,
            round_limit=effective_round_limit,
            at=at,
        )

    def record_director_decision(
        self,
        task_id: str,
        decision: TeamDirectorDecision,
        *,
        parent_question: str | None = None,
        waiting_on: str | None = None,
        at: datetime | None = None,
    ) -> TeamTopologyExecutionState:
        """Persist one typed director decision and advance exactly one runtime step."""
        state = self._require(task_id, expected_substages={"planning", "director_deciding", "repairing"})
        self._ensure_decision(decision)

        current_round = self._current_round(state)
        round_limit = self._round_limit(state)

        if decision.decision == "dispatch_workers":
            target_round = self._dispatch_round_for(state)
            if decision.round_index != target_round:
                msg = (
                    "director dispatch decisions must target the next formal round start; "
                    f"expected round_index {target_round}, received {decision.round_index}"
                )
                raise ValueError(msg)
            if target_round > round_limit or target_round > self._max_rounds:
                return self._record_budget_failure(
                    task_id,
                    state,
                    decision=decision,
                    summary=(
                        "director_worker failed with budget_exhausted: "
                        f"round {target_round} exceeds the frozen limit of {round_limit}."
                    ),
                    at=at,
                )
            if len(decision.dispatch_roles) > self._max_parallel_workers_per_round:
                msg = (
                    f"director_worker dispatch requested {len(decision.dispatch_roles)} workers but "
                    f"the bounded parallel limit is {self._max_parallel_workers_per_round}"
                )
                raise ValueError(msg)
            if self._dispatch_count(state) + len(decision.dispatch_roles) > self._max_total_worker_dispatches:
                return self._record_budget_failure(
                    task_id,
                    state,
                    decision=decision,
                    summary=(
                        "director_worker failed with budget_exhausted: "
                        "max_total_worker_dispatches was exceeded."
                    ),
                    at=at,
                )
            return self._spine.record_checkpoint(
                task_id,
                substage="dispatching",
                phase_status="in_progress",
                active_roles=list(decision.dispatch_roles),
                completed_roles=[self._director_role(state)],
                latest_summary=self._decision_summary(decision),
                artifact_count=state.current_checkpoint.artifact_count,
                round_index=target_round,
                round_limit=round_limit,
                at=at,
            )

        if decision.round_index != current_round:
            msg = (
                "director decisions that do not start a new dispatch round must match the current "
                f"round_index {current_round}; received {decision.round_index}"
            )
            raise ValueError(msg)

        if decision.decision == "complete":
            reduced = self._reduce_director_decision(state, decision, final_status="completed")
            return self._spine.record_checkpoint(
                task_id,
                substage="completed",
                phase_status="completed",
                active_roles=[],
                completed_roles=self._terminal_completed_roles(state),
                latest_summary=self._reduced_summary(reduced),
                artifact_count=len(reduced.selected_artifacts),
                round_index=current_round,
                round_limit=round_limit,
                reduced_result=reduced,
                at=at,
            )

        if decision.decision == "failed":
            reduced = self._reduce_director_decision(state, decision, final_status="failed")
            return self._spine.record_checkpoint(
                task_id,
                substage="failed",
                phase_status="failed",
                active_roles=[],
                completed_roles=self._terminal_completed_roles(state),
                latest_summary=self._reduced_summary(reduced),
                artifact_count=len(reduced.selected_artifacts),
                round_index=current_round,
                round_limit=round_limit,
                reduced_result=reduced,
                at=at,
            )

        if decision.decision == "needs_parent_input":
            if parent_question is None or waiting_on is None:
                msg = (
                    "parent_question and waiting_on are required for director_worker "
                    "parent interruptions"
                )
                raise ValueError(msg)
            if self._parent_interruption_count(state) >= self._max_parent_interruptions:
                return self._record_budget_failure(
                    task_id,
                    state,
                    decision=decision,
                    summary=(
                        "director_worker failed with budget_exhausted: "
                        "max_parent_interruptions was exceeded."
                    ),
                    at=at,
                )
            return self._spine.interrupt_for_parent(
                task_id,
                requested_by_role=self._director_role(state),
                question=parent_question,
                waiting_on=waiting_on,
                latest_summary=self._decision_summary(decision),
                completed_roles=list(state.current_checkpoint.completed_roles),
                artifact_count=state.current_checkpoint.artifact_count,
                repair_state=state.current_checkpoint.repair_state,
                round_index=current_round,
                round_limit=round_limit,
                at=at,
            )

        if decision.decision == "needs_repair":
            if state.current_checkpoint.substage != "director_deciding":
                raise ValueError("director_worker repairs can only start from director_deciding")
            if self._repair_cycle_count(state) >= self._max_repair_cycles_per_run:
                return self._record_budget_failure(
                    task_id,
                    state,
                    decision=decision,
                    summary=(
                        "director_worker failed with budget_exhausted: "
                        "max_repair_cycles_per_run was exceeded."
                    ),
                    at=at,
                )
            return self._spine.record_checkpoint(
                task_id,
                substage="repairing",
                phase_status="in_progress",
                active_roles=[self._director_role(state)],
                completed_roles=[self._director_role(state)],
                latest_summary=self._decision_summary(decision),
                artifact_count=state.current_checkpoint.artifact_count,
                repair_state=decision.repair_hint,
                round_index=current_round,
                round_limit=round_limit,
                at=at,
            )

        msg = f"director_worker does not accept decision '{decision.decision}'"
        raise ValueError(msg)

    def record_worker_results(
        self,
        task_id: str,
        results: list[TeamStructuredResult],
        *,
        director_role: str | None = None,
        at: datetime | None = None,
    ) -> TeamTopologyExecutionState:
        """Persist one bounded worker batch and return control to the director."""
        state = self._require(task_id, expected_substages={"dispatching"})
        if not results:
            raise ValueError("director_worker collection requires at least one worker result")

        dispatched_roles = list(state.current_checkpoint.active_roles)
        submitted_roles = [result.worker_role for result in results]
        if len(set(submitted_roles)) != len(submitted_roles):
            raise ValueError("director_worker collection requires unique worker roles per batch")
        if sorted(submitted_roles) != sorted(dispatched_roles):
            msg = (
                "director_worker collection must include exactly one result for each dispatched "
                f"role; expected {sorted(dispatched_roles)}, received {sorted(submitted_roles)}"
            )
            raise ValueError(msg)

        current_round = self._current_round(state)
        round_limit = self._round_limit(state)
        active_director_role = director_role or self._director_role(state)
        current_state = state
        for result in results:
            self._ensure_result(result)
            current_state = self._spine.record_checkpoint(
                task_id,
                substage="collecting",
                phase_status="in_progress",
                active_roles=[result.worker_role],
                completed_roles=list(current_state.current_checkpoint.completed_roles),
                latest_summary=self._result_summary(result),
                artifact_count=current_state.current_checkpoint.artifact_count + len(result.artifacts),
                round_index=current_round,
                round_limit=round_limit,
                result=result,
                at=at,
            )

        summary = self._worker_rollup_summary(results)
        completed_roles = _unique_roles(
            [active_director_role],
            [result.worker_role for result in results if result.status != "failed"],
        )
        return self._spine.record_checkpoint(
            task_id,
            substage="director_deciding",
            phase_status="in_progress",
            active_roles=[active_director_role],
            completed_roles=completed_roles,
            latest_summary=summary,
            artifact_count=current_state.current_checkpoint.artifact_count,
            round_index=current_round,
            round_limit=round_limit,
            at=at,
        )

    def resume_from_parent(
        self,
        task_id: str,
        *,
        parent_input: str,
        latest_summary: str | None = None,
        at: datetime | None = None,
    ) -> TeamTopologyExecutionState:
        """Resume a blocked director checkpoint without bypassing the Step 2 seam."""
        state = self._require(task_id, expected_substages={"waiting_parent"})
        requested_by = state.interruption.requested_by_role
        active_roles = [requested_by] if requested_by is not None else None
        summary = latest_summary or state.current_checkpoint.latest_summary
        return self._spine.resume_from_parent(
            task_id,
            parent_input=parent_input,
            latest_summary=summary,
            active_roles=active_roles,
            completed_roles=list(state.current_checkpoint.completed_roles),
            round_index=state.current_checkpoint.round_index,
            round_limit=state.current_checkpoint.round_limit,
            at=at,
        )

    def _require(
        self,
        task_id: str,
        *,
        expected_substages: set[str] | None = None,
    ) -> TeamTopologyExecutionState:
        state = self._spine.read(task_id)
        if state is None:
            msg = f"Topology execution state for task '{task_id}' was not initialized"
            raise ValueError(msg)
        if state.topology != "director_worker":
            msg = f"Task '{task_id}' is not using the director_worker topology"
            raise ValueError(msg)
        if expected_substages is not None and state.current_checkpoint.substage not in expected_substages:
            expected = ", ".join(sorted(expected_substages))
            msg = (
                f"Task '{task_id}' must be in one of '{expected}' before this director_worker "
                f"step; current substage is '{state.current_checkpoint.substage}'"
            )
            raise ValueError(msg)
        return state

    def _ensure_result(self, result: TeamStructuredResult) -> None:
        if result.topology != "director_worker":
            raise ValueError("director_worker runtime only accepts director_worker structured results")
        if result.substage != "collecting":
            msg = (
                "director_worker runtime expected a 'collecting' result, "
                f"received '{result.substage}'"
            )
            raise ValueError(msg)

    def _ensure_decision(self, decision: TeamDirectorDecision) -> None:
        if decision.topology != "director_worker":
            raise ValueError("director_worker runtime only accepts director_worker decisions")

    def _director_role(self, state: TeamTopologyExecutionState) -> str:
        if state.checkpoints and state.checkpoints[0].active_roles:
            return state.checkpoints[0].active_roles[0]
        return "director"

    def _current_round(self, state: TeamTopologyExecutionState) -> int:
        return state.current_checkpoint.round_index or 1

    def _round_limit(self, state: TeamTopologyExecutionState) -> int:
        return state.current_checkpoint.round_limit or self._max_rounds

    def _dispatch_round_for(self, state: TeamTopologyExecutionState) -> int:
        if state.current_checkpoint.substage == "planning":
            return self._current_round(state)
        return self._current_round(state) + 1

    def _dispatch_count(self, state: TeamTopologyExecutionState) -> int:
        return sum(
            len(checkpoint.active_roles)
            for checkpoint in state.checkpoints
            if checkpoint.substage == "dispatching"
        )

    def _repair_cycle_count(self, state: TeamTopologyExecutionState) -> int:
        return sum(1 for checkpoint in state.checkpoints if checkpoint.substage == "repairing")

    def _parent_interruption_count(self, state: TeamTopologyExecutionState) -> int:
        return sum(1 for checkpoint in state.checkpoints if checkpoint.substage == "waiting_parent")

    def _collecting_results(self, state: TeamTopologyExecutionState) -> list[TeamStructuredResult]:
        return [
            checkpoint.result
            for checkpoint in state.checkpoints
            if checkpoint.result is not None and checkpoint.result.substage == "collecting"
        ]

    def _preferred_terminal_sources(self, state: TeamTopologyExecutionState) -> list[TeamStructuredResult]:
        results = self._collecting_results(state)
        successful = [result for result in results if result.status == "completed"]
        return successful or results

    def _reduce_director_decision(
        self,
        state: TeamTopologyExecutionState,
        decision: TeamDirectorDecision,
        *,
        final_status: str,
    ) -> TeamReducedTopologyResult:
        source_results = self._preferred_terminal_sources(state)
        selected_evidence = decision.evidence or [
            evidence
            for result in source_results
            for evidence in result.evidence
        ]
        selected_artifacts = decision.artifacts or [
            artifact
            for result in source_results
            for artifact in result.artifacts
        ]
        return TeamReducedTopologyResult(
            topology="director_worker",
            final_status=final_status,
            reduced_summary=decision.summary,
            selected_evidence=list(selected_evidence),
            selected_artifacts=list(selected_artifacts),
            next_action=decision.next_action,
        )

    def _record_budget_failure(
        self,
        task_id: str,
        state: TeamTopologyExecutionState,
        *,
        decision: TeamDirectorDecision,
        summary: str,
        at: datetime | None = None,
    ) -> TeamTopologyExecutionState:
        reduced = TeamReducedTopologyResult(
            topology="director_worker",
            final_status="failed",
            reduced_summary=summary,
            selected_evidence=list(decision.evidence)
            or [
                evidence
                for result in self._preferred_terminal_sources(state)
                for evidence in result.evidence
            ],
            selected_artifacts=list(decision.artifacts)
            or [
                artifact
                for result in self._preferred_terminal_sources(state)
                for artifact in result.artifacts
            ],
            next_action=decision.next_action,
        )
        return self._spine.record_checkpoint(
            task_id,
            substage="failed",
            phase_status="failed",
            active_roles=[],
            completed_roles=self._terminal_completed_roles(state),
            latest_summary=self._reduced_summary(reduced),
            artifact_count=len(reduced.selected_artifacts),
            round_index=self._current_round(state),
            round_limit=self._round_limit(state),
            reduced_result=reduced,
            at=at,
        )

    def _terminal_completed_roles(self, state: TeamTopologyExecutionState) -> list[str]:
        return _unique_roles([self._director_role(state)], list(state.current_checkpoint.completed_roles))

    def _worker_rollup_summary(self, results: list[TeamStructuredResult]) -> str:
        completed = [result.worker_role for result in results if result.status == "completed"]
        repair = [result.worker_role for result in results if result.status == "needs_repair"]
        failed = [result.worker_role for result in results if result.status == "failed"]
        parts = [
            f"{len(results)} director_worker results collected for the director.",
        ]
        if completed:
            parts.append(f"completed: {', '.join(completed)}")
        if repair:
            parts.append(f"repair: {', '.join(repair)}")
        if failed:
            parts.append(f"failed: {', '.join(failed)}")
        return " | ".join(parts)

    def _decision_summary(self, decision: TeamDirectorDecision) -> str:
        parts = [f"director: {_compress_text(decision.summary, limit=96)}"]
        if decision.decision == "dispatch_workers":
            parts.append(f"{len(decision.dispatch_roles)} workers")
        if decision.repair_hint is not None:
            parts.append(f"repair: {_compress_text(decision.repair_hint, limit=40)}")
        elif decision.next_action is not None:
            parts.append(_compress_text(decision.next_action, limit=40))
        return " | ".join(parts)

    def _result_summary(self, result: TeamStructuredResult) -> str:
        parts = [f"{result.worker_role}: {_compress_text(result.summary, limit=96)}"]
        if result.evidence:
            parts.append(f"{len(result.evidence)} evidence")
        if result.artifacts:
            parts.append(f"{len(result.artifacts)} artifacts")
        if result.status == "needs_repair" and result.repair_hint is not None:
            parts.append(f"repair: {_compress_text(result.repair_hint, limit=40)}")
        elif result.next_action is not None:
            parts.append(_compress_text(result.next_action, limit=40))
        return " | ".join(parts)

    def _reduced_summary(self, reduced: TeamReducedTopologyResult) -> str:
        parts = [_compress_text(reduced.reduced_summary, limit=104)]
        if reduced.selected_evidence:
            parts.append(f"{len(reduced.selected_evidence)} evidence")
        if reduced.selected_artifacts:
            parts.append(f"{len(reduced.selected_artifacts)} artifacts")
        if reduced.next_action is not None:
            parts.append(_compress_text(reduced.next_action, limit=40))
        return " | ".join(parts)


class TeamDebateJudgeRuntime:
    """debate_judge execution behavior layered on the Step 2 persistence seam."""

    def __init__(self, spine: TeamTopologyExecutionSpine) -> None:
        self._spine = spine

    def read(self, task_id: str) -> TeamTopologyExecutionState | None:
        """Load the current debate_judge execution state."""
        return self._spine.read(task_id)

    def start(
        self,
        task_id: str,
        *,
        planning_summary: str,
        round_limit: int,
        judge_role: str = "judge",
        at: datetime | None = None,
    ) -> TeamTopologyExecutionState:
        """Initialize the debate_judge run in the planning substage."""
        if round_limit <= 0:
            raise ValueError("round_limit must be greater than 0")
        return self._spine.start(
            task_id,
            topology="debate_judge",
            active_roles=[judge_role],
            latest_summary=_compress_text(planning_summary),
            round_index=1,
            round_limit=round_limit,
            at=at,
        )

    def start_candidate_round(
        self,
        task_id: str,
        *,
        candidate_roles: list[str],
        latest_summary: str | None = None,
        at: datetime | None = None,
    ) -> TeamTopologyExecutionState:
        """Enter the first or repaired candidate round without bypassing the spine."""
        state = self._require(task_id)
        if state.current_checkpoint.substage not in {"planning", "repairing"}:
            msg = (
                "debate_judge can only enter candidate_round from planning or repairing; "
                f"current substage is '{state.current_checkpoint.substage}'"
            )
            raise ValueError(msg)
        normalized_roles = self._validate_candidate_roles(candidate_roles)
        judge_role = self._judge_role(state)
        round_index = state.current_checkpoint.round_index or 1
        round_limit = state.current_checkpoint.round_limit
        summary = latest_summary or self._candidate_round_summary(
            round_index=round_index,
            candidate_roles=normalized_roles,
            round_limit=round_limit,
        )
        return self._spine.record_checkpoint(
            task_id,
            substage="candidate_round",
            phase_status="in_progress",
            active_roles=normalized_roles,
            completed_roles=[judge_role],
            latest_summary=_compress_text(summary),
            round_index=round_index,
            round_limit=round_limit,
            at=at,
        )

    def record_candidate_results(
        self,
        task_id: str,
        results: list[TeamStructuredResult],
        *,
        judge_role: str = "judge",
        at: datetime | None = None,
    ) -> TeamTopologyExecutionState:
        """Persist a bounded candidate round and hand control back to the judge."""
        state = self._require(task_id, expected_substage="candidate_round")
        if not results:
            raise ValueError("debate_judge collection requires at least one candidate result")

        round_index = state.current_checkpoint.round_index
        round_limit = state.current_checkpoint.round_limit
        assert round_index is not None
        expected_roles = list(state.current_checkpoint.active_roles)
        seen_roles: set[str] = set()
        for result in results:
            self._ensure_candidate_result(result)
            if result.worker_role in seen_roles:
                msg = f"candidate '{result.worker_role}' was reported more than once in the same round"
                raise ValueError(msg)
            seen_roles.add(result.worker_role)

        if seen_roles != set(expected_roles):
            missing = sorted(set(expected_roles) - seen_roles)
            extras = sorted(seen_roles - set(expected_roles))
            details: list[str] = []
            if missing:
                details.append(f"missing: {', '.join(missing)}")
            if extras:
                details.append(f"unexpected: {', '.join(extras)}")
            msg = "candidate results must exactly match the active round roles"
            if details:
                msg = f"{msg} ({'; '.join(details)})"
            raise ValueError(msg)

        current_state = state
        for result in results:
            current_state = self._spine.record_checkpoint(
                task_id,
                substage="collecting",
                phase_status="in_progress",
                active_roles=[result.worker_role],
                completed_roles=_unique_roles(
                    list(current_state.current_checkpoint.completed_roles),
                    [result.worker_role],
                ),
                latest_summary=self._result_summary(result),
                artifact_count=current_state.current_checkpoint.artifact_count + len(result.artifacts),
                round_index=round_index,
                round_limit=round_limit,
                result=result,
                at=at,
            )

        collected = self._round_results(current_state, round_index=round_index)
        summary = self._round_rollup_summary(round_index=round_index, results=collected)
        return self._spine.record_checkpoint(
            task_id,
            substage="judging",
            phase_status="in_progress",
            active_roles=[judge_role],
            completed_roles=list(expected_roles),
            latest_summary=_compress_text(summary),
            artifact_count=sum(len(result.artifacts) for result in collected),
            round_index=round_index,
            round_limit=round_limit,
            at=at,
        )

    def record_judge_decision(
        self,
        task_id: str,
        decision: TeamJudgeDecision,
        *,
        parent_question: str | None = None,
        waiting_on: str | None = None,
        at: datetime | None = None,
    ) -> TeamTopologyExecutionState:
        """Persist one typed judge decision and drive the next bounded topology state."""
        state, round_index, round_limit, round_results = self._judge_decision_context(
            task_id,
            decision,
        )
        if decision.decision == "select_winner":
            return self._record_judge_winner(task_id, state, decision, round_results, at=at)
        if decision.decision == "advance_round":
            return self._record_judge_advance_round(task_id, state, decision, at=at)
        if decision.decision == "needs_parent_input":
            return self._record_judge_parent_input(
                task_id,
                state,
                decision,
                parent_question=parent_question,
                waiting_on=waiting_on,
                at=at,
            )
        if decision.decision == "needs_repair":
            return self._record_judge_repair(task_id, state, decision, round_results, at=at)
        if decision.decision == "failed":
            return self._record_judge_failure(task_id, state, decision, round_results, at=at)

        msg = (
            "debate_judge does not recognize decision "
            f"'{decision.decision}' for round {round_index}/{round_limit}"
        )
        raise ValueError(msg)

    def resume_from_parent(
        self,
        task_id: str,
        *,
        parent_input: str,
        latest_summary: str | None = None,
        at: datetime | None = None,
    ) -> TeamTopologyExecutionState:
        """Resume a blocked judge pass without bypassing the Step 2 seam."""
        state = self._require(task_id, expected_substage="waiting_parent")
        requested_by = state.interruption.requested_by_role or self._judge_role(state)
        summary = latest_summary or state.current_checkpoint.latest_summary
        return self._spine.resume_from_parent(
            task_id,
            parent_input=parent_input,
            latest_summary=summary,
            active_roles=[requested_by],
            completed_roles=list(state.current_checkpoint.completed_roles),
            round_index=state.current_checkpoint.round_index,
            round_limit=state.current_checkpoint.round_limit,
            at=at,
        )

    def _require(self, task_id: str, *, expected_substage: str | None = None) -> TeamTopologyExecutionState:
        state = self._spine.read(task_id)
        if state is None:
            msg = f"Topology execution state for task '{task_id}' was not initialized"
            raise ValueError(msg)
        if state.topology != "debate_judge":
            msg = f"Task '{task_id}' is not using the debate_judge topology"
            raise ValueError(msg)
        if expected_substage is not None and state.current_checkpoint.substage != expected_substage:
            msg = (
                f"Task '{task_id}' must be in '{expected_substage}' before this debate step; "
                f"current substage is '{state.current_checkpoint.substage}'"
            )
            raise ValueError(msg)
        return state

    def _ensure_candidate_result(self, result: TeamStructuredResult) -> None:
        if result.topology != "debate_judge":
            raise ValueError("debate_judge runtime only accepts debate_judge structured results")
        if result.substage != "collecting":
            raise ValueError("debate_judge candidates must report collecting-stage structured results")

    def _validate_candidate_roles(self, candidate_roles: list[str]) -> list[str]:
        normalized = [role.strip() for role in candidate_roles if role.strip()]
        if len(normalized) != 2:
            raise ValueError("day-one debate_judge requires exactly two candidate roles")
        if len(set(normalized)) != len(normalized):
            raise ValueError("candidate roles must be unique within one debate round")
        if len(normalized) > self._spine.parallel_limit:
            msg = (
                f"debate_judge requested {len(normalized)} candidates but the bounded "
                f"parallel limit is {self._spine.parallel_limit}"
            )
            raise ValueError(msg)
        return normalized

    def _judge_role(self, state: TeamTopologyExecutionState) -> str:
        if state.checkpoints and state.checkpoints[0].active_roles:
            return state.checkpoints[0].active_roles[0]
        return "judge"

    def _judge_decision_context(
        self,
        task_id: str,
        decision: TeamJudgeDecision,
    ) -> tuple[TeamTopologyExecutionState, int, int, list[TeamStructuredResult]]:
        state = self._require(task_id, expected_substage="judging")
        if decision.topology != "debate_judge":
            raise ValueError("debate_judge runtime only accepts debate_judge judge decisions")

        round_index = state.current_checkpoint.round_index
        round_limit = state.current_checkpoint.round_limit
        if round_index is None or round_limit is None:
            raise ValueError("debate_judge judging requires round metadata on the current checkpoint")
        if decision.round_index != round_index:
            msg = (
                f"judge decision round_index {decision.round_index} does not match the current "
                f"round {round_index}"
            )
            raise ValueError(msg)

        round_results = self._round_results(state, round_index=round_index)
        if not round_results:
            raise ValueError("judge decisions require collected candidate envelopes for the current round")
        return state, round_index, round_limit, round_results

    def _record_judge_winner(
        self,
        task_id: str,
        state: TeamTopologyExecutionState,
        decision: TeamJudgeDecision,
        round_results: list[TeamStructuredResult],
        *,
        at: datetime | None = None,
    ) -> TeamTopologyExecutionState:
        winner_role = decision.winner_role
        assert winner_role is not None
        winner_result = next(
            (result for result in round_results if result.worker_role == winner_role),
            None,
        )
        if winner_result is None:
            msg = f"winner_role '{winner_role}' is not present in the current round envelopes"
            raise ValueError(msg)
        round_index, round_limit = self._round_metadata(state)
        round_roles = [result.worker_role for result in round_results]
        reduced = self._reduce_winner(decision, winner_result)
        return self._spine.record_checkpoint(
            task_id,
            substage="completed",
            phase_status="completed",
            active_roles=[],
            completed_roles=_unique_roles(list(round_roles), [self._judge_role(state)]),
            latest_summary=self._reduced_summary(reduced),
            artifact_count=len(reduced.selected_artifacts),
            round_index=round_index,
            round_limit=round_limit,
            reduced_result=reduced,
            at=at,
        )

    def _record_judge_advance_round(
        self,
        task_id: str,
        state: TeamTopologyExecutionState,
        decision: TeamJudgeDecision,
        *,
        at: datetime | None = None,
    ) -> TeamTopologyExecutionState:
        round_index, round_limit = self._round_metadata(state)
        if round_index >= round_limit:
            raise ValueError("final round judge ties must escalate instead of advancing another round")
        next_roles = self._validate_candidate_roles(decision.next_candidate_roles)
        return self._spine.record_checkpoint(
            task_id,
            substage="candidate_round",
            phase_status="in_progress",
            active_roles=next_roles,
            completed_roles=[self._judge_role(state)],
            latest_summary=self._decision_summary(decision),
            round_index=round_index + 1,
            round_limit=round_limit,
            at=at,
        )

    def _record_judge_parent_input(
        self,
        task_id: str,
        state: TeamTopologyExecutionState,
        decision: TeamJudgeDecision,
        *,
        parent_question: str | None,
        waiting_on: str | None,
        at: datetime | None = None,
    ) -> TeamTopologyExecutionState:
        if parent_question is None or waiting_on is None:
            raise ValueError("parent_question and waiting_on are required for debate_judge interruptions")
        round_index, round_limit = self._round_metadata(state)
        if decision.stop_reason == "final_round_tie" and round_index < round_limit:
            raise ValueError("final_round_tie is only valid when the current round is the final round")
        round_results = self._round_results(state, round_index=round_index)
        round_roles = [result.worker_role for result in round_results]
        return self._spine.interrupt_for_parent(
            task_id,
            requested_by_role=self._judge_role(state),
            question=parent_question,
            waiting_on=waiting_on,
            latest_summary=self._decision_summary(decision),
            completed_roles=list(round_roles),
            artifact_count=self._decision_artifact_count(decision, round_results),
            round_index=round_index,
            round_limit=round_limit,
            at=at,
        )

    def _record_judge_repair(
        self,
        task_id: str,
        state: TeamTopologyExecutionState,
        decision: TeamJudgeDecision,
        round_results: list[TeamStructuredResult],
        *,
        at: datetime | None = None,
    ) -> TeamTopologyExecutionState:
        round_index, round_limit = self._round_metadata(state)
        round_roles = [result.worker_role for result in round_results]
        return self._spine.record_checkpoint(
            task_id,
            substage="repairing",
            phase_status="in_progress",
            active_roles=list(round_roles),
            completed_roles=[self._judge_role(state)],
            latest_summary=self._decision_summary(decision),
            artifact_count=self._decision_artifact_count(decision, round_results),
            repair_state=decision.repair_hint,
            round_index=round_index,
            round_limit=round_limit,
            at=at,
        )

    def _record_judge_failure(
        self,
        task_id: str,
        state: TeamTopologyExecutionState,
        decision: TeamJudgeDecision,
        round_results: list[TeamStructuredResult],
        *,
        at: datetime | None = None,
    ) -> TeamTopologyExecutionState:
        round_index, round_limit = self._round_metadata(state)
        round_roles = [result.worker_role for result in round_results]
        reduced = self._reduce_failure(decision, round_results)
        return self._spine.record_checkpoint(
            task_id,
            substage="failed",
            phase_status="failed",
            active_roles=[],
            completed_roles=_unique_roles(list(round_roles), [self._judge_role(state)]),
            latest_summary=self._reduced_summary(reduced),
            artifact_count=len(reduced.selected_artifacts),
            round_index=round_index,
            round_limit=round_limit,
            reduced_result=reduced,
            at=at,
        )

    def _round_metadata(self, state: TeamTopologyExecutionState) -> tuple[int, int]:
        round_index = state.current_checkpoint.round_index
        round_limit = state.current_checkpoint.round_limit
        assert round_index is not None
        assert round_limit is not None
        return round_index, round_limit

    def _round_results(
        self,
        state: TeamTopologyExecutionState,
        *,
        round_index: int,
    ) -> list[TeamStructuredResult]:
        return [
            checkpoint.result
            for checkpoint in state.checkpoints
            if checkpoint.result is not None
            and checkpoint.topology == "debate_judge"
            and checkpoint.substage == "collecting"
            and checkpoint.round_index == round_index
        ]

    def _candidate_round_summary(
        self,
        *,
        round_index: int,
        candidate_roles: list[str],
        round_limit: int | None,
    ) -> str:
        roles = ", ".join(candidate_roles)
        if round_limit is None:
            return f"Starting candidate round {round_index}: {roles}."
        return f"Starting candidate round {round_index}/{round_limit}: {roles}."

    def _round_rollup_summary(
        self,
        *,
        round_index: int,
        results: list[TeamStructuredResult],
    ) -> str:
        completed = [result.worker_role for result in results if result.status == "completed"]
        failed = [result.worker_role for result in results if result.status == "failed"]
        repairing = [result.worker_role for result in results if result.status == "needs_repair"]
        parts = [f"Round {round_index} collected {len(results)} candidate envelopes."]
        if completed:
            parts.append(f"completed: {', '.join(completed)}")
        if failed:
            parts.append(f"failed: {', '.join(failed)}")
        if repairing:
            parts.append(f"repair: {', '.join(repairing)}")
        return " ".join(parts)

    def _reduce_winner(
        self,
        decision: TeamJudgeDecision,
        winner_result: TeamStructuredResult,
    ) -> TeamReducedTopologyResult:
        return TeamReducedTopologyResult(
            topology="debate_judge",
            final_status="completed",
            reduced_summary=decision.summary,
            selected_evidence=list(decision.evidence or winner_result.evidence),
            selected_artifacts=list(decision.artifacts or winner_result.artifacts),
            next_action=decision.next_action,
        )

    def _reduce_failure(
        self,
        decision: TeamJudgeDecision,
        round_results: list[TeamStructuredResult],
    ) -> TeamReducedTopologyResult:
        return TeamReducedTopologyResult(
            topology="debate_judge",
            final_status="failed",
            reduced_summary=decision.summary,
            selected_evidence=list(decision.evidence or [
                evidence
                for result in round_results
                for evidence in result.evidence
            ]),
            selected_artifacts=list(decision.artifacts or [
                artifact
                for result in round_results
                for artifact in result.artifacts
            ]),
            next_action=decision.next_action,
        )

    def _decision_artifact_count(
        self,
        decision: TeamJudgeDecision,
        round_results: list[TeamStructuredResult],
    ) -> int:
        if decision.artifacts:
            return len(decision.artifacts)
        return sum(len(result.artifacts) for result in round_results)

    def _decision_summary(self, decision: TeamJudgeDecision) -> str:
        parts = [_compress_text(decision.summary, limit=104)]
        if decision.evidence:
            parts.append(f"{len(decision.evidence)} evidence")
        if decision.artifacts:
            parts.append(f"{len(decision.artifacts)} artifacts")
        if decision.decision == "needs_repair" and decision.repair_hint is not None:
            parts.append(f"repair: {_compress_text(decision.repair_hint, limit=40)}")
        elif decision.next_action is not None:
            parts.append(_compress_text(decision.next_action, limit=40))
        return " | ".join(parts)

    def _result_summary(self, result: TeamStructuredResult) -> str:
        parts = [f"{result.worker_role}: {_compress_text(result.summary, limit=96)}"]
        if result.evidence:
            parts.append(f"{len(result.evidence)} evidence")
        if result.artifacts:
            parts.append(f"{len(result.artifacts)} artifacts")
        if result.status == "needs_repair" and result.repair_hint is not None:
            parts.append(f"repair: {_compress_text(result.repair_hint, limit=40)}")
        elif result.next_action is not None:
            parts.append(_compress_text(result.next_action, limit=40))
        return " | ".join(parts)

    def _reduced_summary(self, reduced: TeamReducedTopologyResult) -> str:
        parts = [_compress_text(reduced.reduced_summary, limit=104)]
        if reduced.selected_evidence:
            parts.append(f"{len(reduced.selected_evidence)} evidence")
        if reduced.selected_artifacts:
            parts.append(f"{len(reduced.selected_artifacts)} artifacts")
        if reduced.next_action is not None:
            parts.append(_compress_text(reduced.next_action, limit=40))
        return " | ".join(parts)


__all__ = [
    "TeamDebateJudgeRuntime",
    "TeamDirectorWorkerRuntime",
    "TeamFanoutMergeRuntime",
    "TeamPipelineRuntime",
    "TeamTopologyExecutionSpine",
]
