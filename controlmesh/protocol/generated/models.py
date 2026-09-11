"""Generated protocol models from schemas/controlmesh/v1.

Do not edit manually. Regenerate with:

    uv run python scripts/generate_protocol.py
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

class AgentEvent(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.agent_event.v1"]
    event_id: str
    agent_id: str
    parent_agent: str | None = None
    role: str | None = None
    task_id: str | None = None
    event_type: str
    created_at: str
    payload: dict[str, Any] | None = None


class AgentMailboxMessage(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.agent_mailbox_message.v1"]
    message_id: str
    recipient_task: str
    sender_task: str | None
    sender_principal: str
    sequence: int
    correlation_id: str
    causation_id: str | None
    origin: Literal["human_request", "agent_message", "schedule", "recovery", "internal"]
    kind: Literal["tell", "ask_parent", "answer", "handoff"]
    remaining_hops: int
    created_at: int
    expires_at: int
    payload: dict[str, Any]
    status: Literal["pending", "received", "consumed", "expired"]


class Artifact(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.artifact.v1"]
    task_id: str
    relative_path: str
    name: str | None = None
    mime: str | None = None
    size: int | None = None
    sha256: str | None = None
    created_at: str | None = None


class AskParentResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.ask_parent_response.v1"]
    response_id: str
    request_id: str
    task_id: str
    text: str
    created_at: str


class AskParentRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.ask_parent_request.v1"]
    request_id: str
    task_id: str
    tool_use_id: str | None = None
    parent_agent: str | None = None
    question: str
    created_at: str
    routing: dict[str, Any] | None = None


class ControlMeshConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.config.v1"]
    providers: dict[str, Any] | None = None
    api: dict[str, Any] | None = None
    messengers: dict[str, Any] | None = None
    workspace: dict[str, Any] | None = None


class DeviceCommand(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.device_command.v1"]
    request_id: str
    operation: Literal["queue", "inspect", "claim", "start", "renew", "dispatch", "observe", "complete", "unknown", "messages", "send", "ack", "release", "reconciliation", "reconcile"]
    arguments: dict[str, Any]


class DeviceEvidenceRef(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.device_evidence.v1"]
    device_id: str
    task_id: str
    episode_id: str
    effect_id: str
    fence: int
    assignment_digest: str
    manifest_digest: str
    observation_digest: str | None = None
    result_digest: str | None = None


class DeviceLeaseWindow(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.device_lease_window.v1"]
    lease: ExecutionLease
    remaining_ms: int


class DeviceNativeResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.device_native_result.v1"]
    text: str
    output_digest: str
    read_count: int
    evidence: DeviceEvidenceRef
    native_session: DeviceNativeSession


class DeviceNativeSession(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.device_native_session.v1"]
    device_id: str
    evidence: DeviceEvidenceRef


class DeviceObservation(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.device_observation.v1"]
    evidence: DeviceEvidenceRef
    terminal: bool


class DeviceReconciliationChallenge(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.device_reconciliation_challenge.v1"]
    challenge_id: str
    task_revision: int
    task_fence: int
    manifest: DeviceEvidenceRef
    execution_digest: str
    workspace_id: str
    capability: str
    expires_at: int


class DeviceReconciliationReport(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.device_reconciliation_report.v1"]
    challenge_id: str
    challenge_digest: str
    observation: DeviceObservation
    result: DeviceNativeResult


class DeviceResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.device_response.v1"]
    request_id: str | None
    ok: bool
    data: Any | None = None
    error: str | None = None


class DoctorResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.doctor_result.v1"]
    code: str
    severity: Literal["info", "warning", "error"]
    message: str
    fix_hint: str | None = None
    details: dict[str, Any] | None = None


class ControlMeshError(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.error.v1"]
    code: str
    message: str
    retryable: bool | None = None
    correlation_id: str | None = None
    python_trace_id: str | None = None
    details: dict[str, Any] | None = None


class ExecutionLease(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.execution_lease.v1"]
    task_id: str
    episode_id: str
    device_id: str
    fence: int
    lease_until: int


class LogEvent(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.log_event.v1"]
    level: Literal["debug", "info", "warning", "error"]
    source: str
    task_id: str | None = None
    message: str
    timestamp: float | str
    correlation_id: str | None = None


class MemoryRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.memory_record.v1"]
    record_id: str
    source_file: str
    section: str | None = None
    text: str | None = None
    promotion_state: str | None = None
    created_at: str
    metadata: dict[str, Any] | None = None


class ProviderCapability(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.provider_capability.v1"]
    name: str
    available: bool
    version: str | None = None
    last_checked_at: float | str | None = None
    health: Literal["ok", "degraded", "unavailable"]
    detail: str | None = None
    capabilities: dict[str, Any] | None = None


class ProviderEvent(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.provider_event.v1"]
    provider: str
    kind: str
    phase: str | None = None
    created_at: float | str
    pid: int | None = None
    command: list[str] | None = None
    text: str | None = None
    event_type: str | None = None
    payload: Any | None = None
    idle_for_s: float | None = None
    elapsed_s: float | None = None
    exit_code: int | None = None
    reason: str | None = None
    message: str | None = None
    timed_out: bool | None = None


class RuntimeEvent(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.runtime_event.v1"]
    event_id: str
    session_key: str
    event_type: str
    payload: dict[str, Any] | None = None
    created_at: str
    transport: str
    chat_id: str | int
    topic_id: str | int | None = None


class TaskEvent(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.task_event.v1"]
    event_id: str
    task_id: str
    event_type: str
    status: TaskState | None = None
    created_at: str
    transport: str | None = None
    chat_id: str | int | None = None
    topic_id: str | int | None = None
    payload: dict[str, Any] | None = None


TaskState = Literal["running", "done", "failed", "cancelled", "waiting", "detached", "recovering", "stale", "timeout"]


class Task(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.task.v1"]
    task_id: str
    source_kind: str | None = None
    chat_id: str | int
    thread_id: str | int | None = None
    parent_agent: str
    name: str | None = None
    prompt_preview: str | None = None
    provider: str | None = None
    model: str | None = None
    status: TaskState
    transport: str | None = None
    topology: str | None = None
    session_id: str | None = None
    created_at: float | str
    completed_at: float | str | None = None
    elapsed_seconds: float | None = None
    result_preview: str | None = None
    last_question: str | None = None


class Topology(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.topology.v1"]
    topology_id: str
    name: str | None = None
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


class TransportMessage(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.transport_message.v1"]
    transport: str
    message_id: str | int
    chat_id: str | int
    thread_id: str | int | None = None
    sender_id: str | int | None = None
    text: str | None = None
    command: str | None = None
    raw_payload: Any | None = None
    created_at: str


class WorkspaceManifest(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.workspace_manifest.v1"]
    workspace_root: str
    paths: dict[str, str]
