"""Production-Python oracle for result writeback and promotion safety."""

from __future__ import annotations

import tempfile
import json
from pathlib import Path

from controlmesh_runtime.contracts import ReviewOutcome
from controlmesh_runtime.evidence_identity import EvidenceSubject, RuntimeEvidenceIdentity
from controlmesh_runtime.execution_payloads import ExecutionPlanPayload, ExecutionResultPayload
from controlmesh_runtime.execution_runtime_events import build_runtime_event_from_execution_payload
from controlmesh_runtime.promotion_controller import PromotionController
from controlmesh_runtime.recovery import RecoveryExecutionStatus, RecoveryIntent
from controlmesh_runtime.store import RuntimeStore
from controlmesh_runtime.summary import SummaryKind, SummaryRecord

SCHEMA_VERSION = "controlmesh.result_writeback_promotion_golden.v1"
REQUIRED_CASES = (
    "writeback.first_success",
    "writeback.identical_retry",
    "writeback.conflicting_retry",
    "writeback.wrong_owner",
    "writeback.stale_episode",
    "promotion.crosswired_identity",
    "promotion.non_success_statuses",
    "promotion.prewrite_freshness",
    "promotion.controller_accept",
    "delivery.safe_retry",
)


def _identity(packet: str = "packet-1", *, line: str = "golden-line", plan: str = "plan-1") -> RuntimeEvidenceIdentity:
    return RuntimeEvidenceIdentity(packet_id=packet, task_id="task-1", line=line, plan_id=plan)


def _event(identity: RuntimeEvidenceIdentity, kind: str, *, worker: str = "worker-1", status: RecoveryExecutionStatus = RecoveryExecutionStatus.COMPLETED, completed: int = 1):
    if kind == "plan":
        payload = ExecutionPlanPayload(
            execution_event_type="execution.plan_created", plan_id=identity.plan_id,
            task_id=identity.task_id, line=identity.line, worker_id=worker,
            intent=RecoveryIntent.RESTART_WORKER, requires_human_gate=False,
            next_step_token=RecoveryIntent.RESTART_WORKER.value, step_count=1,
        )
    else:
        payload = ExecutionResultPayload(
            plan_id=identity.plan_id, task_id=identity.task_id, line=identity.line,
            worker_id=worker, result_status=status, completed_step_count=completed,
            requires_human_gate=False,
        )
    return build_runtime_event_from_execution_payload(payload, packet_id=identity.packet_id, message=kind)


def _error(call) -> str:
    try:
        call()
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    raise AssertionError("golden operation unexpectedly succeeded")


def _line(root: Path, identity: RuntimeEvidenceIdentity) -> None:
    target = root / "plans" / identity.line
    target.mkdir(parents=True)
    (target / "task_plan.md").write_text("# Current Status\nnot_started\n", encoding="utf-8")
    (target / "progress.md").write_text(
        "# Latest Completed\nnone\n\n# Current State\nnot_started\n\n# Next Action\nwait\n\n# Latest Checkpoint\nnone\n\n# Notes\nnone\n",
        encoding="utf-8",
    )


def _summaries(store: RuntimeStore, identity: RuntimeEvidenceIdentity) -> None:
    for subject, kind in ((EvidenceSubject.TASK, SummaryKind.TASK_HANDOFF), (EvidenceSubject.LINE, SummaryKind.LINE_CHECKPOINT)):
        store.save_summary_record(SummaryRecord(
            summary_kind=kind, subject=subject, evidence_identity=identity,
            entity_id=identity.entity_id_for(subject), token_budget=200,
            source_refs=("golden:evidence",), key_facts=("verified",),
            next_step_hint="continue",
        ))


def _promote(root: Path, identity: RuntimeEvidenceIdentity):
    return PromotionController(root).reconcile(
        episode=identity, review_outcome=ReviewOutcome.PASS,
        review_reason=("golden verified",), latest_completed="verified result",
        next_action="continue",
    )


def generate_matrix() -> dict[str, object]:
    cases: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="controlmesh-result-golden-") as raw:
        root = Path(raw)
        store = RuntimeStore(root)
        identity = _identity()
        store.append_execution_evidence(_event(identity, "plan"))
        first = store.append_execution_evidence(_event(identity, "result"))
        cases.append({"id": "writeback.first_success", "accepted": True, "event_count": len(store.load_execution_evidence(identity.packet_id)), "result_event_id": "<stable>" if first.event_id else None})

        duplicate = store.append_execution_evidence(_event(identity, "result"))
        cases.append({"id": "writeback.identical_retry", "accepted": True, "same_event": duplicate.event_id == first.event_id, "event_count": len(store.load_execution_evidence(identity.packet_id))})
        cases.append({"id": "writeback.conflicting_retry", "accepted": False, "error": _error(lambda: store.append_execution_evidence(_event(identity, "result", completed=2))), "event_count": len(store.load_execution_evidence(identity.packet_id))})

        wrong = _identity("packet-owner", plan="plan-owner")
        store.append_execution_evidence(_event(wrong, "plan"))
        cases.append({"id": "writeback.wrong_owner", "accepted": False, "error": _error(lambda: store.append_execution_evidence(_event(wrong, "result", worker="worker-2")))})

        old = _identity("packet-old", plan="plan-old")
        new = _identity("packet-new", plan="plan-new")
        old_plan = _event(old, "plan").model_copy(update={"created_at": "2026-01-01T00:00:00Z"})
        new_plan = _event(new, "plan").model_copy(update={"created_at": "2026-01-02T00:00:00Z"})
        store.append_execution_evidence(old_plan)
        store.append_execution_evidence(new_plan)
        cases.append({"id": "writeback.stale_episode", "accepted": False, "error": _error(lambda: store.append_execution_evidence(_event(old, "result")))})

        cases.append({"id": "promotion.crosswired_identity", "accepted": False, "error": _error(lambda: store.validate_promotable_execution(_identity(line="other-line")))})
        rejected: dict[str, str] = {}
        for status in (RecoveryExecutionStatus.FAILED, RecoveryExecutionStatus.CANCELLED, RecoveryExecutionStatus.DELIVERY_FAILED):
            item = _identity(f"packet-{status.value}", plan=f"plan-{status.value}")
            store.append_execution_evidence(_event(item, "plan"))
            store.append_execution_evidence(_event(item, "result", status=status, completed=0))
            rejected[status.value] = _error(lambda item=item: store.validate_promotable_execution(item))
        cases.append({"id": "promotion.non_success_statuses", "accepted": False, "rejected": rejected})

        promote_root = root / "promotion"
        promote_store = RuntimeStore(promote_root)
        promote_identity = _identity()
        _line(promote_root, promote_identity)
        _summaries(promote_store, promote_identity)
        promote_store.append_execution_evidence(_event(promote_identity, "plan"))
        promote_store.append_execution_evidence(_event(promote_identity, "result"))
        task_evidence = promote_root / "plans" / "tasks" / promote_identity.task_id / "generated" / "EVIDENCE.json"
        task_evidence.parent.mkdir(parents=True)
        evidence_payload = {
            "task_id": promote_identity.task_id,
            "workunit_kind": "patch_candidate",
            "status": "done",
            "summary": "candidate retained for controller review",
            "verification_commands": ["uv run pytest -q"],
            "proposed_files": ["proposed_plan_delta.md"],
        }
        task_evidence.write_text(json.dumps(evidence_payload, sort_keys=True), encoding="utf-8")
        evidence_before = task_evidence.read_text(encoding="utf-8")
        accepted = _promote(promote_root, promote_identity)
        receipt_count = len(promote_store.list_promotion_receipts_by_identity(promote_identity))
        control_count = len(promote_store.list_control_events_by_identity(promote_identity))
        canonical_text = (promote_root / "plans" / promote_identity.line / "progress.md").read_text(encoding="utf-8")
        cases.append({"id": "promotion.controller_accept", "accepted": accepted.ok, "receipt_count": receipt_count, "control_event_count": control_count, "review_source": accepted.review_record.source if accepted.review_record else None, "task_evidence_unchanged": task_evidence.read_text(encoding="utf-8") == evidence_before, "verification_commands": evidence_payload["verification_commands"], "proposed_files_remain_task_local": "proposed_plan_delta.md" not in canonical_text})
        retried = _promote(promote_root, promote_identity)
        cases.append({"id": "delivery.safe_retry", "accepted": retried.ok, "reason": retried.reason, "receipt_count": len(promote_store.list_promotion_receipts_by_identity(promote_identity)), "control_event_count": len(promote_store.list_control_events_by_identity(promote_identity))})

        race_root = root / "race"
        race_store = RuntimeStore(race_root)
        race_identity = _identity()
        _line(race_root, race_identity)
        _summaries(race_store, race_identity)
        race_store.append_execution_evidence(_event(race_identity, "plan"))
        race_store.append_execution_evidence(_event(race_identity, "result"))
        controller = PromotionController(race_root)
        original = controller._bridge._writer.write
        def race_write(*, line, patches, pre_write_check=None):
            replacement = _identity("packet-race-new", plan="plan-race-new")
            race_store.append_execution_evidence(_event(replacement, "plan").model_copy(update={"created_at": "9999-01-01T00:00:00Z"}))
            return original(line=line, patches=patches, pre_write_check=pre_write_check)
        controller._bridge._writer.write = race_write
        before = (race_root / "plans" / race_identity.line / "task_plan.md").read_text(encoding="utf-8")
        error = _error(lambda: controller.reconcile(episode=race_identity, review_outcome=ReviewOutcome.PASS, review_reason=("race",), latest_completed="bad", next_action="bad"))
        after = (race_root / "plans" / race_identity.line / "task_plan.md").read_text(encoding="utf-8")
        cases.append({"id": "promotion.prewrite_freshness", "accepted": False, "canonical_unchanged": before == after, "error": error})

    order = {case_id: index for index, case_id in enumerate(REQUIRED_CASES)}
    cases.sort(key=lambda case: order[str(case["id"])])
    return {"schema_version": SCHEMA_VERSION, "production_owner": "python", "identity_fields": ["packet_id", "task_id", "line", "plan_id"], "cases": cases}
