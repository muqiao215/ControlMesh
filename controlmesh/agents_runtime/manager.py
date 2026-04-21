"""Bridge ControlMesh-owned tool adapters into SDK function tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from controlmesh.agents_runtime.context import AgentsRuntimeContext
from controlmesh.agents_runtime.tools import (
    ask_parent as ask_parent_tool,
)
from controlmesh.agents_runtime.tools import (
    create_background_task as create_background_task_tool,
)
from controlmesh.agents_runtime.tools import (
    resume_background_task as resume_background_task_tool,
)
from controlmesh.agents_runtime.tools import (
    send_async_to_agent as send_async_to_agent_tool,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from controlmesh.cli.base import CLIConfig


class AgentsRuntimeManager:
    """Build SDK tool callables from stable ControlMesh seams only."""

    def __init__(self, ctx: AgentsRuntimeContext) -> None:
        self._ctx = ctx

    @classmethod
    def from_cli_config(cls, config: CLIConfig) -> AgentsRuntimeManager:
        return cls(
            AgentsRuntimeContext(
                agent_name=config.agent_name,
                chat_id=config.chat_id,
                topic_id=config.topic_id,
                process_label=config.process_label,
                provider=config.provider,
                model=config.model,
                task_hub=config.task_hub,
                interagent_bus=config.interagent_bus,
            )
        )

    def build_sdk_tools(self, function_tool: Callable[[Any], Any]) -> list[Any]:
        """Return SDK-wrapped tools available for this runtime context."""
        tools: list[Any] = []

        if self._ctx.task_hub is not None:
            async def create_background_task(  # noqa: PLR0913
                prompt: str,
                name: str = "",
                provider_override: str = "",
                model_override: str = "",
                thinking_override: str = "",
                topology: str = "",
            ) -> dict[str, Any]:
                """Create a ControlMesh background task through the existing TaskHub."""
                result = await create_background_task_tool(
                    self._ctx,
                    prompt=prompt,
                    name=name,
                    provider_override=provider_override,
                    model_override=model_override,
                    thinking_override=thinking_override,
                    topology=topology,
                )
                return result.model_dump(mode="json")

            async def resume_background_task(task_id: str, follow_up: str) -> dict[str, Any]:
                """Resume a ControlMesh background task through the existing TaskHub."""
                result = await resume_background_task_tool(
                    self._ctx,
                    task_id=task_id,
                    follow_up=follow_up,
                )
                return result.model_dump(mode="json")

            tools.extend(
                [
                    function_tool(create_background_task),
                    function_tool(resume_background_task),
                ]
            )

            if self._ctx.current_task_id is not None:
                async def ask_parent(question: str) -> dict[str, Any]:
                    """Forward a question to the parent agent from a running task context."""
                    result = await ask_parent_tool(self._ctx, question=question)
                    return result.model_dump(mode="json")

                tools.append(function_tool(ask_parent))

        if self._ctx.interagent_bus is not None:
            async def send_async_to_agent(
                recipient: str,
                message: str,
                summary: str = "",
                new_session: bool = False,
            ) -> dict[str, Any]:
                """Queue an async inter-agent request through the existing InterAgentBus."""
                result = await send_async_to_agent_tool(
                    self._ctx,
                    recipient=recipient,
                    message=message,
                    summary=summary,
                    new_session=new_session,
                )
                return result.model_dump(mode="json")

            tools.append(function_tool(send_async_to_agent))

        return tools
