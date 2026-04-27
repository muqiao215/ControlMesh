"""Conservative ControlMesh tool adapters for the optional agents backend."""

from __future__ import annotations

from controlmesh.agents_runtime.context import AgentsRuntimeContext
from controlmesh.agents_runtime.results import ToolResultEnvelope
from controlmesh.multiagent.bus import AsyncSendOptions
from controlmesh.tasks.models import TaskSubmit


async def create_background_task(
    ctx: AgentsRuntimeContext,
    *,
    prompt: str,
    name: str = "",
    provider_override: str = "",
    model_override: str = "",
    thinking_override: str = "",
    topology: str = "",
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
                transport=ctx.transport,
                parent_agent=ctx.agent_name,
                name=name,
                provider_override=provider_override,
                model_override=model_override,
                thinking_override=thinking_override,
                topology=topology,
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


async def tell_background_task(
    ctx: AgentsRuntimeContext,
    *,
    task_id: str,
    message: str,
) -> ToolResultEnvelope:
    """Queue one parent update for a running background task."""
    if ctx.task_hub is None:
        return ToolResultEnvelope.failure(
            "tell_background_task",
            code="task_hub_unavailable",
            message="TaskHub is not available for this runtime.",
        )

    try:
        sequence = ctx.task_hub.tell(task_id, message, parent_agent=ctx.agent_name)
    except Exception as exc:
        return ToolResultEnvelope.failure(
            "tell_background_task",
            code="task_tell_failed",
            message=str(exc),
            data={"task_id": task_id},
        )

    return ToolResultEnvelope.success(
        "tell_background_task",
        summary=f"Queued parent update {sequence} for background task {task_id}.",
        data={"task_id": task_id, "sequence": sequence},
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


async def check_parent_updates(
    ctx: AgentsRuntimeContext,
    *,
    mark_read: bool = True,
) -> ToolResultEnvelope:
    """Read queued parent updates from inside a running background task."""
    if ctx.task_hub is None:
        return ToolResultEnvelope.failure(
            "check_parent_updates",
            code="task_hub_unavailable",
            message="TaskHub is not available for this runtime.",
        )

    task_id = ctx.current_task_id
    if task_id is None:
        return ToolResultEnvelope.failure(
            "check_parent_updates",
            code="task_context_required",
            message="check_parent_updates is only available from a running background task context.",
        )

    try:
        updates = ctx.task_hub.pull_updates(task_id, mark_read=mark_read)
    except Exception as exc:
        return ToolResultEnvelope.failure(
            "check_parent_updates",
            code="task_updates_failed",
            message=str(exc),
            data={"task_id": task_id},
        )

    count = len(updates)
    summary = "No new parent updates." if count == 0 else f"Read {count} parent update(s)."
    return ToolResultEnvelope.success(
        "check_parent_updates",
        summary=summary,
        data={"task_id": task_id, "count": count, "updates": updates},
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
