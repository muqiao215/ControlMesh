"""Thin file-backed persisted store for ControlMesh runtime objects."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from controlmesh_runtime.contracts import ControlEvent, ControlEventKind
from controlmesh_runtime.events import RuntimeEvent
from controlmesh_runtime.evidence_identity import RuntimeEvidenceIdentity
from controlmesh_runtime.execution_runtime_events import (
    extract_execution_payload_from_runtime_event,
)
from controlmesh_runtime.promotion_receipt import PromotionReceipt
from controlmesh_runtime.records import ReviewRecord
from controlmesh_runtime.serde import (
    StoreDecodeError,
    append_jsonl_record,
    read_json_model,
    read_jsonl_models,
    write_json_atomic,
)
from controlmesh_runtime.summary import SummaryRecord
from controlmesh_runtime.task_packet import TaskPacket
from controlmesh_runtime.worker_state import WorkerState


@dataclass(frozen=True)
class RuntimeStorePaths:
    """Stable directory layout for persisted runtime state."""

    root: Path

    @property
    def state_root(self) -> Path:
        return self.root / "controlmesh_state"

    @property
    def tasks_dir(self) -> Path:
        return self.state_root / "tasks"

    @property
    def workers_dir(self) -> Path:
        return self.state_root / "workers"

    @property
    def reviews_dir(self) -> Path:
        return self.state_root / "reviews"

    @property
    def events_dir(self) -> Path:
        return self.state_root / "events"

    @property
    def execution_evidence_dir(self) -> Path:
        return self.state_root / "execution_evidence"

    @property
    def control_events_dir(self) -> Path:
        return self.state_root / "control_events"

    @property
    def summaries_dir(self) -> Path:
        return self.state_root / "summaries"

    @property
    def promotion_receipts_dir(self) -> Path:
        return self.state_root / "promotion_receipts"

    def task_path(self, packet_id: str) -> Path:
        return self.tasks_dir / f"{packet_id}.json"

    def worker_path(self, worker_id: str) -> Path:
        return self.workers_dir / f"{worker_id}.json"

    def review_path(self, task_id: str) -> Path:
        return self.reviews_dir / f"{task_id}.json"

    def events_path(self, packet_id: str) -> Path:
        return self.events_dir / f"{packet_id}.jsonl"

    def execution_evidence_path(self, packet_id: str) -> Path:
        return self.execution_evidence_dir / f"{packet_id}.jsonl"

    def control_events_path(self, packet_id: str) -> Path:
        return self.control_events_dir / f"{packet_id}.jsonl"

    def summary_path(self, entity_id: str) -> Path:
        if ":" in entity_id:
            subject, raw_entity_id = entity_id.split(":", 1)
            safe_subject = subject.strip()
            safe_entity_id = raw_entity_id.replace("/", "__")
            return self.summaries_dir / safe_subject / f"{safe_entity_id}.json"
        safe_entity_id = entity_id.replace("/", "__")
        return self.summaries_dir / f"{safe_entity_id}.json"

    def promotion_receipt_path(self, receipt_id: str) -> Path:
        return self.promotion_receipts_dir / f"{receipt_id}.json"


class RuntimeStore:
    """Persist typed runtime objects without adding recovery or control logic."""

    def __init__(self, root: Path | str) -> None:
        self.paths = RuntimeStorePaths(Path(root))

    @property
    def root(self) -> Path:
        """Expose the runtime root for read-surface callers."""
        return self.paths.root

    def save_task_packet(self, packet: TaskPacket) -> TaskPacket:
        write_json_atomic(self.paths.task_path(packet.packet_id), packet)
        return packet

    def load_task_packet(self, packet_id: str) -> TaskPacket:
        return read_json_model(self.paths.task_path(packet_id), TaskPacket)

    def save_worker_state(self, state: WorkerState) -> WorkerState:
        write_json_atomic(self.paths.worker_path(state.worker_id), state)
        return state

    def load_worker_state(self, worker_id: str) -> WorkerState:
        return read_json_model(self.paths.worker_path(worker_id), WorkerState)

    def save_review_record(self, record: ReviewRecord) -> ReviewRecord:
        write_json_atomic(self.paths.review_path(record.task_id), record)
        return record

    def load_review_record(self, task_id: str) -> ReviewRecord:
        return read_json_model(self.paths.review_path(task_id), ReviewRecord)

    def append_event(self, event: RuntimeEvent) -> RuntimeEvent:
        append_jsonl_record(self.paths.events_path(event.packet_id), event)
        return event

    def load_events(self, packet_id: str) -> list[RuntimeEvent]:
        return read_jsonl_models(self.paths.events_path(packet_id), RuntimeEvent)

    def append_execution_evidence(self, event: RuntimeEvent) -> RuntimeEvent:
        extract_execution_payload_from_runtime_event(event)
        append_jsonl_record(self.paths.execution_evidence_path(event.packet_id), event)
        return event

    def load_execution_evidence(self, packet_id: str) -> list[RuntimeEvent]:
        events = read_jsonl_models(self.paths.execution_evidence_path(packet_id), RuntimeEvent)
        for event in events:
            try:
                extract_execution_payload_from_runtime_event(event)
            except Exception as exc:
                msg = f"failed to decode {self.paths.execution_evidence_path(packet_id)}: schema validation failed"
                raise StoreDecodeError(msg) from exc
        return events

    def append_control_event(self, event: ControlEvent) -> ControlEvent:
        append_jsonl_record(self.paths.control_events_path(event.evidence_identity.packet_id), event)
        return event

    def load_control_events(self, packet_id: str) -> list[ControlEvent]:
        return read_jsonl_models(self.paths.control_events_path(packet_id), ControlEvent)

    def list_control_events_by_identity(
        self,
        identity: RuntimeEvidenceIdentity,
    ) -> list[ControlEvent]:
        return [
            event
            for event in self.load_control_events(identity.packet_id)
            if event.evidence_identity == identity
        ]

    def latest_control_event(
        self,
        identity: RuntimeEvidenceIdentity,
        kind: ControlEventKind | str,
    ) -> ControlEvent | None:
        target_kind = ControlEventKind(kind)
        events = [
            event
            for event in self.list_control_events_by_identity(identity)
            if event.kind is target_kind
        ]
        return events[-1] if events else None

    def save_summary_record(self, record: SummaryRecord) -> SummaryRecord:
        write_json_atomic(self.paths.summary_path(record.entity_id), record)
        return record

    def load_summary_record(self, entity_id: str) -> SummaryRecord:
        return read_json_model(self.paths.summary_path(entity_id), SummaryRecord)

    def save_promotion_receipt(self, receipt: PromotionReceipt) -> PromotionReceipt:
        write_json_atomic(self.paths.promotion_receipt_path(receipt.receipt_id), receipt)
        return receipt

    def load_promotion_receipt(self, receipt_id: str) -> PromotionReceipt:
        return read_json_model(self.paths.promotion_receipt_path(receipt_id), PromotionReceipt)

    def list_promotion_receipts_by_identity(
        self,
        identity: RuntimeEvidenceIdentity,
    ) -> list[PromotionReceipt]:
        if not self.paths.promotion_receipts_dir.exists():
            return []
        receipts: list[PromotionReceipt] = []
        for path in sorted(self.paths.promotion_receipts_dir.glob("*.json")):
            receipt = read_json_model(path, PromotionReceipt)
            if receipt.evidence_identity == identity:
                receipts.append(receipt)
        return receipts

    def latest_promotion_receipt(self, identity: RuntimeEvidenceIdentity) -> PromotionReceipt | None:
        receipts = self.list_promotion_receipts_by_identity(identity)
        if not receipts:
            return None
        return max(receipts, key=lambda receipt: receipt.recorded_at)


__all__ = ["RuntimeStore", "RuntimeStorePaths", "StoreDecodeError"]
