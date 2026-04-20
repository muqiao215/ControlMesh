"""Narrow ControlMesh runtime adapters for the optional agents backend."""

from controlmesh.agents_runtime.context import AgentsRuntimeContext
from controlmesh.agents_runtime.manager import AgentsRuntimeManager
from controlmesh.agents_runtime.results import ToolErrorDetail, ToolResultEnvelope

__all__ = [
    "AgentsRuntimeContext",
    "AgentsRuntimeManager",
    "ToolErrorDetail",
    "ToolResultEnvelope",
]
