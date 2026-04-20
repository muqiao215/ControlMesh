"""Optional OpenAI Agents SDK backend behind the BaseCLI seam."""

from __future__ import annotations

import inspect
import logging
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

from controlmesh.agents_runtime.manager import AgentsRuntimeManager
from controlmesh.cli.base import BaseCLI, CLIConfig
from controlmesh.cli.stream_events import (
    AssistantTextDelta,
    ResultEvent,
    StreamEvent,
    SystemInitEvent,
)
from controlmesh.cli.types import CLIResponse

if TYPE_CHECKING:
    from controlmesh.cli.timeout_controller import TimeoutController

logger = logging.getLogger(__name__)

_MISSING_SDK_MESSAGE = (
    "OpenAI Agents SDK backend is not installed. "
    "Install the optional extra with: pip install controlmesh[openai-agents]"
)


class OpenAIAgentsCLI(BaseCLI):
    """Conservative one-turn adapter for the optional OpenAI Agents SDK.

    This backend intentionally does not own ControlMesh sessions, task lifecycle,
    transports, or process state. It is only an opt-in BaseCLI implementation
    that can run one bounded SDK turn and normalize the result back into the
    existing ControlMesh CLI response/event contracts.
    """

    def __init__(self, config: CLIConfig) -> None:
        self._config = config

    async def send(
        self,
        prompt: str,
        resume_session: str | None = None,
        continue_session: bool = False,
        timeout_seconds: float | None = None,
        timeout_controller: TimeoutController | None = None,
    ) -> CLIResponse:
        """Run one SDK turn and return a normalized CLIResponse."""
        if resume_session or continue_session:
            logger.debug(
                "OpenAI Agents backend ignores durable session controls "
                "resume=%s continue=%s",
                bool(resume_session),
                continue_session,
            )

        try:
            run_result = await self._run_with_timeout(
                prompt,
                timeout_seconds=timeout_seconds,
                timeout_controller=timeout_controller,
            )
        except ImportError:
            logger.info("OpenAI Agents SDK unavailable")
            return CLIResponse(result=_MISSING_SDK_MESSAGE, is_error=True, returncode=1)
        except TimeoutError:
            logger.warning("OpenAI Agents backend timed out")
            return CLIResponse(result="Timeout", is_error=True, returncode=124, timed_out=True)
        except Exception as exc:
            logger.exception("OpenAI Agents backend failed")
            return CLIResponse(result=str(exc), is_error=True, returncode=1)

        return _run_result_to_cli_response(run_result)

    async def send_streaming(
        self,
        prompt: str,
        resume_session: str | None = None,
        continue_session: bool = False,
        timeout_seconds: float | None = None,
        timeout_controller: TimeoutController | None = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Expose a minimal ControlMesh stream envelope for one SDK turn."""
        yield SystemInitEvent(type="system", subtype="init")

        response = await self.send(
            prompt,
            resume_session=resume_session,
            continue_session=continue_session,
            timeout_seconds=timeout_seconds,
            timeout_controller=timeout_controller,
        )
        if response.result and not response.is_error:
            yield AssistantTextDelta(type="assistant", text=response.result)
        yield ResultEvent(
            type="result",
            result=response.result,
            is_error=response.is_error,
            returncode=response.returncode,
            duration_ms=response.duration_ms,
            total_cost_usd=response.total_cost_usd,
            usage=response.usage,
            num_turns=response.num_turns,
        )

    async def _run_with_timeout(
        self,
        prompt: str,
        *,
        timeout_seconds: float | None,
        timeout_controller: TimeoutController | None,
    ) -> Any:
        run_coro = self._run_sdk(prompt)
        if timeout_controller is not None:
            return await timeout_controller.run_with_timeout(run_coro)
        if timeout_seconds is not None:
            return await _wait_for(run_coro, timeout_seconds=timeout_seconds)
        return await run_coro

    async def _run_sdk(self, prompt: str) -> Any:
        """Run the real SDK lazily so importing this module stays optional."""
        agent_cls, runner_cls, function_tool = _load_agents_sdk()
        instructions = self._compose_instructions()
        agent_kwargs: dict[str, Any] = {
            "name": "ControlMesh OpenAI Agents Backend",
            "instructions": instructions,
        }
        if self._config.model:
            agent_kwargs["model"] = self._config.model
        runtime_tools = AgentsRuntimeManager.from_cli_config(self._config).build_sdk_tools(function_tool)
        if runtime_tools:
            agent_kwargs["tools"] = runtime_tools

        agent = agent_cls(**agent_kwargs)
        result = runner_cls.run(agent, prompt)
        if inspect.isawaitable(result):
            return await result
        return result

    def _compose_instructions(self) -> str:
        parts = [part for part in (self._config.system_prompt, self._config.append_system_prompt) if part]
        if not parts:
            return (
                "You are an optional ControlMesh backend adapter. "
                "Handle only this bounded turn and return a concise final answer."
            )
        return "\n\n".join(parts)


def _load_agents_sdk() -> tuple[type[Any], type[Any], Any]:
    """Load SDK classes lazily; the dependency is optional."""
    from agents import Agent, Runner, function_tool

    return Agent, Runner, function_tool


async def _wait_for(awaitable: Any, *, timeout_seconds: float) -> Any:
    import asyncio

    return await asyncio.wait_for(awaitable, timeout=timeout_seconds)


def _run_result_to_cli_response(run_result: Any) -> CLIResponse:
    result_text = _extract_final_output(run_result)
    usage = _extract_usage(run_result)
    return CLIResponse(
        result=result_text,
        is_error=False,
        returncode=0,
        usage=usage,
        num_turns=1,
    )


def _extract_final_output(run_result: Any) -> str:
    output = getattr(run_result, "final_output", None)
    if output is None:
        output = getattr(run_result, "output", None)
    if output is None:
        return str(run_result)
    if isinstance(output, str):
        return output
    return str(output)


def _extract_usage(run_result: Any) -> dict[str, Any]:
    usage = getattr(run_result, "usage", None)
    if usage is None:
        return {}
    if isinstance(usage, dict):
        return usage
    model_dump = getattr(usage, "model_dump", None)
    if callable(model_dump):
        data = model_dump()
        return data if isinstance(data, dict) else {}
    if hasattr(usage, "__dict__"):
        return dict(vars(usage))
    return {}
