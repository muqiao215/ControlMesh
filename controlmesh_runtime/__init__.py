"""Minimal ControlMesh runtime foundation.

This package is intentionally additive. It starts by owning review semantics
and leaves transport, CLI, and production wiring outside this cut.
"""

from controlmesh_runtime.autonomous_runtime_loop import (
    AutonomousPromotionApproval,
    AutonomousRuntimeLoop,
    AutonomousRuntimeLoopOutcome,
    AutonomousRuntimeLoopRequest,
    AutonomousRuntimeScheduler,
)
from controlmesh_runtime.canonical_section_writer import (
    CanonicalSectionName,
    CanonicalSectionPatch,
    CanonicalSectionWriter,
    CanonicalTargetFile,
    CanonicalWriteShape,
)
from controlmesh_runtime.contracts import (
    ControlEvent,
    ControlEventKind,
    QueryAction,
    ReviewInput,
    ReviewOutcome,
    SignalAction,
    UpdateAction,
)
from controlmesh_runtime.engine import (
    EngineExecution,
    EngineRequest,
    EngineState,
    EngineStopReason,
    EngineTraceEvent,
    ExecutionEventType,
    build_first_engine_plan,
    can_transition_engine_state,
    execute_first_engine_plan,
    run_first_engine,
)
from controlmesh_runtime.events import EventKind, FailureClass, RuntimeEvent
from controlmesh_runtime.evidence_identity import EvidenceSubject, RuntimeEvidenceIdentity
from controlmesh_runtime.execution_evidence_replay_query import (
    ExecutionEpisodeQueryView,
    ExecutionEvidenceReplayQuerySurface,
    ExecutionReplayValidation,
    TaskExecutionReplayQueryView,
)
from controlmesh_runtime.execution_payloads import (
    ExecutionEventPayload,
    ExecutionPayloadEventType,
    ExecutionPlanPayload,
    ExecutionResultPayload,
    ExecutionStepPayload,
    build_execution_payload,
    event_kind_for_execution_payload,
)
from controlmesh_runtime.execution_read_surface import (
    ExecutionEvidenceReadSurface,
    PacketExecutionEpisodeView,
    TaskExecutionReadView,
)
from controlmesh_runtime.execution_runtime_events import (
    build_runtime_event_from_execution_payload,
    extract_execution_payload_from_runtime_event,
)
from controlmesh_runtime.promotion_bridge import (
    PromotionBridge,
    PromotionEligibility,
    PromotionInput,
    PromotionResult,
    PromotionSource,
    PromotionWriteIntent,
    SummaryPromotionInput,
)
from controlmesh_runtime.promotion_controller import PromotionController, PromotionControllerResult
from controlmesh_runtime.promotion_receipt import PromotionReceipt
from controlmesh_runtime.records import ReviewRecord
from controlmesh_runtime.recovery import (
    EscalationLevel,
    RecoveryContext,
    RecoveryDecision,
    RecoveryExecutionAction,
    RecoveryExecutionPlan,
    RecoveryExecutionResult,
    RecoveryExecutionStatus,
    RecoveryExecutionStep,
    RecoveryIntent,
    RecoveryPolicy,
    RecoveryReason,
    evaluate_recovery_policy,
)
from controlmesh_runtime.recovery_thin_loop import (
    RecoveryLoopOutcome,
    RecoveryLoopRequest,
    run_recovery_cycle,
)
from controlmesh_runtime.review import review
from controlmesh_runtime.review_handoff_packet import (
    ReviewHandoffPacket,
    ReviewHandoffPacketBuilder,
    ReviewHandoffScope,
)
from controlmesh_runtime.runtime import RuntimeStage
from controlmesh_runtime.runtime_execution_checkpoint import (
    RuntimeExecutionCheckpointer,
    RuntimeExecutionCheckpointOutcome,
    RuntimeExecutionCheckpointRequest,
)
from controlmesh_runtime.runtime_message_api import query, signal, update
from controlmesh_runtime.store import RuntimeStore, StoreDecodeError
from controlmesh_runtime.summary import (
    CompressionDecision,
    CompressionPolicy,
    SummaryInput,
    SummaryKind,
    SummaryMaterializationRequest,
    SummaryMaterializationResult,
    SummaryRecord,
    SummaryRuntime,
    SummaryTrigger,
    build_summary_record,
    evaluate_compression_policy,
)
from controlmesh_runtime.task_packet import TaskPacket, TaskPacketMode
from controlmesh_runtime.thin_orchestrator import (
    OrchestratorRequest,
    OrchestratorRun,
    ThinOrchestrator,
)
from controlmesh_runtime.thin_runtime_loop import (
    ThinRuntimeLoop,
    ThinRuntimeLoopOutcome,
    ThinRuntimeLoopRequest,
)
from controlmesh_runtime.tracing import TraceContext, child_trace, root_trace
from controlmesh_runtime.worker_controller import (
    ControlMeshWorkerController,
    WorkerController,
    WorkerControllerError,
    WorkerControllerErrorCode,
)
from controlmesh_runtime.worker_state import (
    DEGRADED_WORKER_STATUSES,
    NORMAL_WORKER_STATUSES,
    TERMINAL_WORKER_STATUSES,
    WorkerState,
    WorkerStatus,
    can_transition,
    transition_worker_state,
)

__all__ = [
    "DEGRADED_WORKER_STATUSES",
    "NORMAL_WORKER_STATUSES",
    "TERMINAL_WORKER_STATUSES",
    "AutonomousPromotionApproval",
    "AutonomousRuntimeLoop",
    "AutonomousRuntimeLoopOutcome",
    "AutonomousRuntimeLoopRequest",
    "AutonomousRuntimeScheduler",
    "CanonicalSectionName",
    "CanonicalSectionPatch",
    "CanonicalSectionWriter",
    "CanonicalTargetFile",
    "CanonicalWriteShape",
    "CompressionDecision",
    "CompressionPolicy",
    "ControlEvent",
    "ControlEventKind",
    "ControlMeshWorkerController",
    "EngineExecution",
    "EngineRequest",
    "EngineState",
    "EngineStopReason",
    "EngineTraceEvent",
    "EscalationLevel",
    "EventKind",
    "EvidenceSubject",
    "ExecutionEpisodeQueryView",
    "ExecutionEventPayload",
    "ExecutionEventType",
    "ExecutionEvidenceReadSurface",
    "ExecutionEvidenceReplayQuerySurface",
    "ExecutionPayloadEventType",
    "ExecutionPlanPayload",
    "ExecutionReplayValidation",
    "ExecutionResultPayload",
    "ExecutionStepPayload",
    "FailureClass",
    "OrchestratorRequest",
    "OrchestratorRun",
    "PacketExecutionEpisodeView",
    "PromotionBridge",
    "PromotionController",
    "PromotionControllerResult",
    "PromotionEligibility",
    "PromotionInput",
    "PromotionReceipt",
    "PromotionResult",
    "PromotionSource",
    "PromotionWriteIntent",
    "QueryAction",
    "RecoveryContext",
    "RecoveryDecision",
    "RecoveryExecutionAction",
    "RecoveryExecutionPlan",
    "RecoveryExecutionResult",
    "RecoveryExecutionStatus",
    "RecoveryExecutionStep",
    "RecoveryIntent",
    "RecoveryLoopOutcome",
    "RecoveryLoopRequest",
    "RecoveryPolicy",
    "RecoveryReason",
    "ReviewHandoffPacket",
    "ReviewHandoffPacketBuilder",
    "ReviewHandoffScope",
    "ReviewInput",
    "ReviewOutcome",
    "ReviewRecord",
    "RuntimeEvent",
    "RuntimeEvidenceIdentity",
    "RuntimeExecutionCheckpointOutcome",
    "RuntimeExecutionCheckpointRequest",
    "RuntimeExecutionCheckpointer",
    "RuntimeStage",
    "RuntimeStore",
    "SignalAction",
    "StoreDecodeError",
    "SummaryInput",
    "SummaryKind",
    "SummaryMaterializationRequest",
    "SummaryMaterializationResult",
    "SummaryPromotionInput",
    "SummaryRecord",
    "SummaryRuntime",
    "SummaryTrigger",
    "TaskExecutionReadView",
    "TaskExecutionReplayQueryView",
    "TaskPacket",
    "TaskPacketMode",
    "ThinOrchestrator",
    "ThinRuntimeLoop",
    "ThinRuntimeLoopOutcome",
    "ThinRuntimeLoopRequest",
    "TraceContext",
    "UpdateAction",
    "WorkerController",
    "WorkerControllerError",
    "WorkerControllerErrorCode",
    "WorkerState",
    "WorkerStatus",
    "build_execution_payload",
    "build_first_engine_plan",
    "build_runtime_event_from_execution_payload",
    "build_summary_record",
    "can_transition",
    "can_transition_engine_state",
    "child_trace",
    "evaluate_compression_policy",
    "evaluate_recovery_policy",
    "event_kind_for_execution_payload",
    "execute_first_engine_plan",
    "extract_execution_payload_from_runtime_event",
    "query",
    "review",
    "root_trace",
    "run_first_engine",
    "run_recovery_cycle",
    "signal",
    "transition_worker_state",
    "update",
]
