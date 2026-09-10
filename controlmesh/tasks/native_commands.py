"""Local terminal controls for native session discovery and TaskHub admission."""
from __future__ import annotations

import argparse
import asyncio
import json
import shlex
from typing import TYPE_CHECKING, NoReturn

from controlmesh.bus.envelope import SourceScope, current_execution_context
from controlmesh.tasks.models import TaskSubmit
from controlmesh.tasks.native_sessions import read_native_session, viewer_candidates

if TYPE_CHECKING:
    from controlmesh.session import SessionKey
    from controlmesh.tasks.hub import TaskHub


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ValueError(message)


async def native_task_command(hub: TaskHub, key: SessionKey, text: str) -> str:
    context = current_execution_context()
    if context is None or context.source_scope is not SourceScope.LOCAL_FOREGROUND:
        return "Native history access/adoption requires the local CM terminal."
    try:
        args = shlex.split(text)[1:]
        action = args.pop(0)
        if action == "sessions":
            refs = await asyncio.to_thread(viewer_candidates, " ".join(args))
            return json.dumps([ref.to_dict() for ref in refs], ensure_ascii=False, indent=2) + (
                "\nInspect a candidate: /tasks inspect <session_id>\n"
                "Adopt: /tasks adopt --session <id> --revision <revision> --directory <native-cwd> "
                "--repo <target-repo> --model <provider/model> -- <new instruction>"
            )
        if action == "inspect":
            if len(args) != 1:
                raise ValueError("Usage: /tasks inspect <OpenCode session_id>")
            ref = await asyncio.to_thread(read_native_session, args[0])
            return json.dumps(ref.to_dict(), ensure_ascii=False, indent=2)
        if action == "recover":
            parser = _Parser(prog="/tasks recover", add_help=False)
            parser.add_argument("--task", required=True)
            parser.add_argument("--revision", required=True)
            parser.add_argument("prompt", nargs="+")
            parsed = parser.parse_args(args)
            task_id = hub.recover_native(parsed.task, parsed.revision, " ".join(parsed.prompt))
            return f"TaskHub task {task_id} recovery admitted; native preflight/execution pending."
        parser = _Parser(prog="/tasks adopt", add_help=False)
        for flag in ("session", "revision", "directory", "repo", "model"):
            parser.add_argument(f"--{flag}", required=True)
        parser.add_argument("prompt", nargs="+")
        parsed = parser.parse_args(args)
        ref = await asyncio.to_thread(read_native_session, parsed.session)
        if ref.revision != parsed.revision or ref.directory != parsed.directory:
            raise ValueError("Native session changed or directory mismatch; inspect again")
        task_id = hub.submit(TaskSubmit(
            chat_id=key.chat_id, message_id=0, thread_id=key.topic_id, parent_agent="main",
            transport=key.transport, prompt=" ".join(parsed.prompt), name=f"Native {ref.session_id}",
            provider_override="opencode", model_override=parsed.model, repo_root=parsed.repo,
            native_session=ref, execution_context=context,
        ))
    except (ValueError, OSError) as exc:
        return f"Native session command failed: {exc}"
    else:
        return f"TaskHub task {task_id} adopted native session {ref.session_id}; model preflight/execution pending."
