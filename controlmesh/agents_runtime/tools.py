"""Conservative ControlMesh tool adapters for the optional agents backend."""

from __future__ import annotations

from controlmesh.agents_runtime.context import AgentsRuntimeContext
from controlmesh.agents_runtime.results import ToolResultEnvelope
from controlmesh.multiagent.bus import AsyncSendOptions
from controlmesh.tasks.models import TaskSubmit


async def create_background_task(  # noqa: PLR0913
    ctx: AgentsRuntimeContext,
    *,
    prompt: str,
    name: str = "",
    provider_override: str = "",
    model_override: str = "",
    thinking_override: str = "",
) -> ToolResultEnvelope:
    """Create a background task via the existing TaskHub."""
    if ctx.task_hub is None:
        return ToolResultEnvelope.failure(
            "create_background_task",
            code="task_hub_unavailable",
            message="TaskHub is not available for this runtime.",
        )

    try:
        task_id = ctx.task_hub.submit(
            TaskSubmit(
                chat_id=ctx.chat_id,
                prompt=prompt,
                message_id=0,
                thread_id=ctx.topic_id,
                parent_agent=ctx.agent_name,
                name=name,
                provider_override=provider_override,
                model_override=model_override,
                thinking_override=thinking_override,
            )
        )
    except Exception as exc:
        return ToolResultEnvelope.failure(
            "create_background_task",
            code="task_create_failed",
            message=str(exc),
        )

    return ToolResultEnvelope.success(
        "create_background_task",
        summary=f"Created background task {task_id}.",
        data={"task_id": task_id},
    )


async def resume_background_task(
    ctx: AgentsRuntimeContext,
    *,
    task_id: str,
    follow_up: str,
) -> ToolResultEnvelope:
    """Resume an existing background task via the existing TaskHub."""
    if ctx.task_hub is None:
        return ToolResultEnvelope.failure(
            "resume_background_task",
            code="task_hub_unavailable",
            message="TaskHub is not available for this runtime.",
        )

    try:
        resumed_id = ctx.task_hub.resume(task_id, follow_up, parent_agent=ctx.agent_name)
    except Exception as exc:
        return ToolResultEnvelope.failure(
            "resume_background_task",
            code="task_resume_failed",
            message=str(exc),
            data={"task_id": task_id},
        )

    return ToolResultEnvelope.success(
        "resume_background_task",
        summary=f"Resumed background task {resumed_id}.",
        data={"task_id": resumed_id},
    )


async def ask_parent(
    ctx: AgentsRuntimeContext,
    *,
    question: str,
) -> ToolResultEnvelope:
    """Forward a question to the parent agent from inside a running task."""
    if ctx.task_hub is None:
        return ToolResultEnvelope.failure(
            "ask_parent",
            code="task_hub_unavailable",
            message="TaskHub is not available for this runtime.",
        )

    task_id = ctx.current_task_id
    if task_id is None:
        return ToolResultEnvelope.failure(
            "ask_parent",
            code="task_context_required",
            message="ask_parent is only available from a running background task context.",
        )

    try:
        detail = await ctx.task_hub.forward_question(task_id, question)
    except Exception as exc:
        return ToolResultEnvelope.failure(
            "ask_parent",
            code="ask_parent_failed",
            message=str(exc),
            data={"task_id": task_id},
        )

    return ToolResultEnvelope.success(
        "ask_parent",
        summary=detail,
        data={"task_id": task_id},
    )


async def send_async_to_agent(
    ctx: AgentsRuntimeContext,
    *,
    recipient: str,
    message: str,
    summary: str = "",
    new_session: bool = False,
) -> ToolResultEnvelope:
    """Send an async inter-agent request through the existing InterAgentBus."""
    if ctx.interagent_bus is None:
        return ToolResultEnvelope.failure(
            "send_async_to_agent",
            code="interagent_bus_unavailable",
            message="InterAgentBus is not available for this runtime.",
        )

    task_id = ctx.interagent_bus.send_async(
        ctx.agent_name,
        recipient,
        message,
        opts=AsyncSendOptions(
            new_session=new_session,
            summary=summary,
            chat_id=ctx.chat_id,
            topic_id=ctx.topic_id,
        ),
    )
    if task_id is None:
        return ToolResultEnvelope.failure(
            "send_async_to_agent",
            code="recipient_not_found",
            message=f"Agent '{recipient}' is not available.",
            data={"recipient": recipient},
        )

    return ToolResultEnvelope.success(
        "send_async_to_agent",
        summary=f"Queued async inter-agent task {task_id} for {recipient}.",
        data={"task_id": task_id, "recipient": recipient},
    )
