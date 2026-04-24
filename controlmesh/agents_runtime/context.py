"""Typed runtime context passed into ControlMesh-owned tool adapters."""

from __future__ import annotations

from dataclasses import dataclass

from controlmesh.messenger.address import ChatRef, TopicRef

if False:  # pragma: no cover
    from controlmesh.multiagent.bus import InterAgentBus
    from controlmesh.tasks.hub import TaskHub


@dataclass(frozen=True, slots=True)
class AgentsRuntimeContext:
    """Minimal ControlMesh-owned execution context for one bounded SDK turn."""

    agent_name: str
    chat_id: ChatRef
    topic_id: TopicRef
    process_label: str
    transport: str = "tg"
    provider: str = "openai_agents"
    model: str | None = None
    task_hub: TaskHub | None = None
    interagent_bus: InterAgentBus | None = None

    @property
    def current_task_id(self) -> str | None:
        """Return the current task id when executing inside a TaskHub worker."""
        prefix = "task:"
        if not self.process_label.startswith(prefix):
            return None
        task_id = self.process_label[len(prefix) :].strip()
        return task_id or None
