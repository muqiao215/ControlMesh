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


class DeliveryReceipt(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.delivery_receipt.v1"]
    delivery_id: str
    envelope_digest: str
    target_digest: str
    adapter_digest: str
    remote_message_id: str


class DeliveryTarget(BaseModel):
    model_config = ConfigDict(extra="allow")
    transport: str
    chat_id: str
    topic_id: str
    thread_id: str


class DeviceCommand(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.device_command.v1"]
    request_id: str
    operation: Literal["queue", "inspect", "claim", "start", "renew", "dispatch", "observe", "complete", "unknown", "messages", "send", "ack", "release", "reconciliation", "reconcile", "native_call", "native_input", "queue_page"]
    arguments: dict[str, Any]


class DeviceCompletionProof(BaseModel):
    model_config = ConfigDict(extra="allow")
    requirements_digest: str
    sha256: list[str]


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
    communication: NativeAgentScope | None = None
    mailbox_delivery: NativeMailboxBinding | None = None
    workspace_write: DeviceWorkspaceBinding | None = None


class DeviceLeaseWindow(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.device_lease_window.v1"]
    lease: ExecutionLease
    remaining_ms: int


class DeviceNativeAdoption(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.device_native_adoption.v1"]
    device_id: str
    adoption_id: str
    context_digest: str


class DeviceNativeResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.device_native_result.v1"]
    text: str
    output_digest: str
    read_count: int
    evidence: DeviceEvidenceRef
    native_session: DeviceNativeSession
    communication: NativeAgentProof | None = None
    mailbox_delivery: NativeMailboxProof | None = None
    workspace_write: DeviceWorkspaceProof | None = None
    completion: DeviceCompletionProof | None = None


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


class DeviceWorkspaceBinding(BaseModel):
    model_config = ConfigDict(extra="allow")
    profile_digest: str
    workflow_binding: str | None


class DeviceWorkspaceProof(BaseModel):
    model_config = ConfigDict(extra="allow")
    profile_digest: str
    proposal_digest: str
    changed_count: int
    specmesh: dict[str, Any] | None = None


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


class FeishuIncomingMessage(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.feishu_incoming.v1"]
    app_id: str
    event_id: str
    message_id: str
    sender_id: str
    chat_id: str
    thread_id: str
    root_id: str
    text: str
    created_at: int
    source_scope: Literal["direct_message", "group_message"]
    mentions_local_bot: bool


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


class NativeAgentCallReceipt(BaseModel):
    model_config = ConfigDict(extra="allow")
    call_id: str
    tool: Literal["controlmesh_send", "controlmesh_ask_parent", "controlmesh_receive", "controlmesh_answer"]
    input_digest: str
    output_digest: str


class NativeAgentProof(BaseModel):
    model_config = ConfigDict(extra="allow")
    call_receipts: list[NativeAgentCallReceipt]


class NativeAgentScope(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.native_agent_scope.v1"]
    task_id: str
    episode_id: str
    fence: int
    peer_tasks: list[str]
    parent_task: str | None
    client_digest: str


class NativeMailboxBatch(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.native_mailbox.v1"]
    task_id: str
    messages: list[AgentMailboxMessage]


class NativeMailboxBinding(BaseModel):
    model_config = ConfigDict(extra="allow")
    delivery_digest: str
    message_ids: list[str]


class NativeMailboxProof(BaseModel):
    model_config = ConfigDict(extra="allow")
    delivery_digest: str
    message_ids: list[str]
    native_user_message_id: str


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


class TaskCompletion(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.task_completion.v1"]
    files: list[dict[str, Any]]


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


class TerminalDelivery(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["controlmesh.terminal_delivery.v1"]
    delivery_id: str
    task_id: str
    event_seq: int
    task_revision: int
    fence: int
    status: Literal["done", "failed", "cancelled"]
    origin: Literal["task_result"]
    command_origin: Literal["human_request", "agent_message", "schedule", "recovery", "internal"]
    execution_context: dict[str, Any]
    target: DeliveryTarget
    text: str
    output_policy: Literal["summarized_only", "full"]
    created_at: int


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
