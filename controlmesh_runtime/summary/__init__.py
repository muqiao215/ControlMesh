"""Summary compression contracts and pure policy mapping."""

from controlmesh_runtime.evidence_identity import EvidenceSubject, RuntimeEvidenceIdentity
from controlmesh_runtime.summary.contracts import (
    CompressionDecision,
    SummaryInput,
    SummaryKind,
    SummaryRecord,
)
from controlmesh_runtime.summary.policy import CompressionPolicy, evaluate_compression_policy
from controlmesh_runtime.summary.runtime import (
    SummaryMaterializationRequest,
    SummaryMaterializationResult,
    SummaryRuntime,
    SummaryTrigger,
    build_summary_record,
)

__all__ = [
    "CompressionDecision",
    "CompressionPolicy",
    "EvidenceSubject",
    "RuntimeEvidenceIdentity",
    "SummaryInput",
    "SummaryKind",
    "SummaryMaterializationRequest",
    "SummaryMaterializationResult",
    "SummaryRecord",
    "SummaryRuntime",
    "SummaryTrigger",
    "build_summary_record",
    "evaluate_compression_policy",
]
