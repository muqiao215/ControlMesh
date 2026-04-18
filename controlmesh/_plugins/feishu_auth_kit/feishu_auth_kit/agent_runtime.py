from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from .message_context import FeishuMessageContext

AgentEventKind = Literal[
    "status",
    "start",
    "running",
    "completed",
    "error",
    "stderr_warning",
    "tool_call",
    "tool_result",
    "assistant_message",
]


@dataclass(frozen=True)
class AgentEvent:
    kind: AgentEventKind
    text: str | None = None
    tool_name: str | None = None
    tool_input: dict[str, Any] | str | None = None
    detail: str | None = None
    state: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def status(cls, text: str, *, metadata: dict[str, Any] | None = None) -> AgentEvent:
        return cls(kind="status", text=text, state="completed", metadata=metadata or {})

    @classmethod
    def tool_call(
        cls,
        tool_name: str,
        tool_input: dict[str, Any] | str | None = None,
        *,
        detail: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentEvent:
        return cls(
            kind="tool_call",
            tool_name=tool_name,
            tool_input=tool_input,
            detail=detail,
            state="running",
            metadata=metadata or {},
        )

    @classmethod
    def tool_result(
        cls,
        tool_name: str,
        text: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> AgentEvent:
        return cls(
            kind="tool_result",
            tool_name=tool_name,
            text=text,
            state="completed",
            metadata=metadata or {},
        )

    @classmethod
    def assistant_message(
        cls,
        text: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> AgentEvent:
        return cls(
            kind="assistant_message",
            text=text,
            state="completed",
            metadata=metadata or {},
        )

    @classmethod
    def start(cls, text: str, *, metadata: dict[str, Any] | None = None) -> AgentEvent:
        return cls(kind="start", text=text, state="start", metadata=metadata or {})

    @classmethod
    def running(cls, text: str, *, metadata: dict[str, Any] | None = None) -> AgentEvent:
        return cls(kind="running", text=text, state="running", metadata=metadata or {})

    @classmethod
    def completed(cls, text: str, *, metadata: dict[str, Any] | None = None) -> AgentEvent:
        return cls(kind="completed", text=text, state="completed", metadata=metadata or {})

    @classmethod
    def error(
        cls,
        text: str,
        *,
        detail: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentEvent:
        return cls(
            kind="error",
            text=text,
            detail=detail,
            state="error",
            metadata=metadata or {},
        )

    @classmethod
    def stderr_warning(
        cls,
        text: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> AgentEvent:
        return cls(
            kind="stderr_warning",
            text=text,
            state="completed",
            metadata=metadata or {},
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.kind,
            "status": self.state,
            "text": self.text,
            "tool_name": self.tool_name,
            "tool_input": self.tool_input,
            "detail": self.detail,
            "metadata": self.metadata,
        }
        return {key: value for key, value in payload.items() if value not in (None, {})}


@dataclass(frozen=True)
class AgentTurnRequest:
    context: FeishuMessageContext
    prompt: str
    system_prompt: str | None = None
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_message_context(
        cls,
        context: FeishuMessageContext,
        *,
        prompt: str | None = None,
        system_prompt: str | None = None,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentTurnRequest:
        return cls(
            context=context,
            prompt=prompt if prompt is not None else context.prompt_text(),
            system_prompt=system_prompt,
            session_id=session_id,
            metadata=metadata or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "feishu-auth-kit.agent-turn-request.v1",
            "prompt": self.prompt,
            "system_prompt": self.system_prompt,
            "session_id": self.session_id,
            "context": self.context.to_dict(),
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class AgentTurnResult:
    runner: str
    output_text: str
    status: str = "completed"
    events: list[AgentEvent] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "feishu-auth-kit.agent-turn-result.v1",
            "runner": self.runner,
            "output_text": self.output_text,
            "status": self.status,
            "events": [event.to_dict() for event in self.events],
            "metadata": self.metadata,
        }


class AgentRunner(Protocol):
    name: str

    def run(self, request: AgentTurnRequest) -> AgentTurnResult:
        raise NotImplementedError


class EchoRunner:
    name = "echo"

    def __init__(self, *, prefix: str = "Echo") -> None:
        self.prefix = prefix

    def run(self, request: AgentTurnRequest) -> AgentTurnResult:
        output_text = f"{self.prefix}: {request.prompt}"
        return AgentTurnResult(
            runner=self.name,
            output_text=output_text,
            events=[
                AgentEvent.status("Message context normalized"),
                AgentEvent.assistant_message(output_text),
            ],
            metadata={"message_id": request.context.message_id},
        )


def build_codex_prompt(request: AgentTurnRequest) -> str:
    parts = [
        "You are running inside a Feishu native agent runtime adapter.",
        "Return the final reply text for the Feishu user.",
        "",
        "Feishu message context:",
        f"- event_type: {request.context.event_type or '(unknown)'}",
        f"- message_id: {request.context.message_id or '(unknown)'}",
        f"- chat_id: {request.context.chat_id or '(unknown)'}",
        f"- sender_open_id: {request.context.sender_open_id or '(unknown)'}",
    ]
    if request.session_id:
        parts.append(f"- session_id: {request.session_id}")
    if request.system_prompt:
        parts.extend(["", "Runtime instructions:", request.system_prompt.strip()])
    parts.extend(["", "User message:", request.prompt])
    return "\n".join(parts).strip()


class CodexCliRunner:
    name = "codex_cli"

    def __init__(
        self,
        *,
        codex_bin: str = "codex",
        model: str | None = None,
        cwd: str | Path | None = None,
        extra_args: list[str] | None = None,
        timeout: int = 180,
    ) -> None:
        self.codex_bin = codex_bin
        self.model = model
        self.cwd = Path(cwd).expanduser() if cwd else None
        self.extra_args = extra_args or []
        self.timeout = timeout

    def _command(self, output_path: str) -> list[str]:
        command = [
            self.codex_bin,
            "exec",
            "--json",
            "--skip-git-repo-check",
            "--color",
            "never",
            "-o",
            output_path,
        ]
        if self.model:
            command.extend(["-m", self.model])
        if self.cwd:
            command.extend(["-C", str(self.cwd)])
        command.extend(self.extra_args)
        command.append("-")
        return command

    def _parse_json_events(self, stdout: str) -> list[AgentEvent]:
        events: list[AgentEvent] = []
        for raw_line in stdout.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            event_type = payload.get("type")
            if event_type == "thread.started":
                events.append(
                    AgentEvent.start(
                        "Codex thread started",
                        metadata={"thread_id": payload.get("thread_id")},
                    )
                )
            elif event_type == "turn.started":
                events.append(AgentEvent.running("Codex turn started"))
            elif event_type == "item.started":
                item = payload.get("item") or {}
                if item.get("type") == "command_execution":
                    command = str(item.get("command") or "")
                    events.append(
                        AgentEvent.tool_call(
                            "shell.command",
                            {"command": command},
                            detail=command,
                            metadata={"item_id": item.get("id"), "status": item.get("status")},
                        )
                    )
            elif event_type == "item.completed":
                item = payload.get("item") or {}
                item_type = item.get("type")
                if item_type == "command_execution":
                    events.append(
                        AgentEvent.tool_result(
                            "shell.command",
                            str(item.get("aggregated_output") or "").rstrip(),
                            metadata={
                                "item_id": item.get("id"),
                                "exit_code": item.get("exit_code"),
                                "status": item.get("status"),
                                "command": item.get("command"),
                            },
                        )
                    )
                elif item_type == "agent_message":
                    events.append(
                        AgentEvent.assistant_message(
                            str(item.get("text") or ""),
                            metadata={"item_id": item.get("id")},
                        )
                    )
            elif event_type == "turn.completed":
                events.append(
                    AgentEvent.completed(
                        "Codex turn completed",
                        metadata={"usage": payload.get("usage") or {}},
                    )
                )
        return events

    def run(self, request: AgentTurnRequest) -> AgentTurnResult:
        prompt = build_codex_prompt(request)
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=True) as last_message:
            command = self._command(last_message.name)
            completed = subprocess.run(
                command,
                input=prompt,
                text=True,
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
            last_message.seek(0)
            output_text = last_message.read().strip() or completed.stdout.strip()
        events = self._parse_json_events(completed.stdout)
        stderr_text = completed.stderr.strip()
        if not events:
            events = [
                AgentEvent.start("Codex run started"),
                AgentEvent.running("Codex run executing"),
            ]
            if output_text:
                events.append(AgentEvent.assistant_message(output_text))
        if completed.returncode == 0 and not any(event.kind == "completed" for event in events):
            events.append(AgentEvent.completed("Codex run completed"))
        if completed.returncode != 0:
            events.append(
                AgentEvent.error(
                    "Codex CLI failed",
                    detail=stderr_text or completed.stdout.strip(),
                    metadata={"returncode": completed.returncode},
                )
            )
        if stderr_text:
            events.append(
                AgentEvent.stderr_warning(
                    stderr_text.splitlines()[0],
                    metadata={"line_count": len(stderr_text.splitlines())},
                )
            )
        return AgentTurnResult(
            runner=self.name,
            output_text=output_text,
            status="completed" if completed.returncode == 0 else "error",
            events=events,
            metadata={
                "codex_bin": self.codex_bin,
                "model": self.model,
                "cwd": str(self.cwd) if self.cwd else None,
                "returncode": completed.returncode,
                "stderr_present": bool(completed.stderr.strip()),
                "json_event_count": len(events),
            },
        )
