"""Tests for task data models."""

from __future__ import annotations

from controlmesh.tasks.models import TaskEntry, TaskResult, TaskSubmit


class TestTaskEntry:
    def test_to_dict_roundtrip(self) -> None:
        entry = TaskEntry(
            task_id="abc123",
            chat_id=42,
            parent_agent="main",
            name="Flugsuche Paris",
            prompt_preview="Suche Flüge nach Paris",
            provider="claude",
            model="opus",
            status="running",
            session_id="sess-1",
            created_at=1000.0,
            question_count=2,
        )
        d = entry.to_dict()
        restored = TaskEntry.from_dict(d)

        assert restored.task_id == "abc123"
        assert restored.chat_id == 42
        assert restored.parent_agent == "main"
        assert restored.name == "Flugsuche Paris"
        assert restored.provider == "claude"
        assert restored.model == "opus"
        assert restored.status == "running"
        assert restored.session_id == "sess-1"
        assert restored.question_count == 2

    def test_from_dict_defaults(self) -> None:
        d = {"task_id": "x", "chat_id": 1}
        entry = TaskEntry.from_dict(d)
        assert entry.parent_agent == "main"
        assert entry.name == ""
        assert entry.status == "running"
        assert entry.question_count == 0

    def test_to_dict_excludes_original_prompt(self) -> None:
        """original_prompt is runtime-only, not persisted."""
        entry = TaskEntry(
            task_id="x",
            chat_id=1,
            parent_agent="main",
            name="test",
            prompt_preview="short",
            provider="claude",
            model="opus",
            status="done",
            original_prompt="very long prompt...",
        )
        d = entry.to_dict()
        assert "original_prompt" not in d

    def test_thread_id_roundtrip(self) -> None:
        entry = TaskEntry(
            task_id="t1",
            chat_id=100,
            parent_agent="main",
            name="topic-task",
            prompt_preview="short",
            provider="claude",
            model="opus",
            status="running",
            thread_id=42,
        )
        d = entry.to_dict()
        assert d["thread_id"] == 42
        restored = TaskEntry.from_dict(d)
        assert restored.thread_id == 42

    def test_thread_id_none_omitted(self) -> None:
        entry = TaskEntry(
            task_id="t2",
            chat_id=1,
            parent_agent="main",
            name="",
            prompt_preview="",
            provider="",
            model="",
            status="running",
        )
        d = entry.to_dict()
        assert "thread_id" not in d
        restored = TaskEntry.from_dict(d)
        assert restored.thread_id is None

    def test_string_refs_roundtrip(self) -> None:
        entry = TaskEntry(
            task_id="qq1",
            chat_id="qqbot:c2c:OPENID",
            parent_agent="main",
            name="qq-task",
            prompt_preview="short",
            provider="claude",
            model="opus",
            status="running",
            transport="qqbot",
            thread_id="qqbot:channel:THREAD",
        )
        restored = TaskEntry.from_dict(entry.to_dict())
        assert restored.chat_id == "qqbot:c2c:OPENID"
        assert restored.thread_id == "qqbot:channel:THREAD"


class TestTaskSubmit:
    def test_default_fields(self) -> None:
        sub = TaskSubmit(
            chat_id=1,
            prompt="do something",
            message_id=10,
            thread_id=None,
            parent_agent="main",
        )
        assert sub.name == ""
        assert sub.provider_override == ""
        assert sub.thinking_override == ""

    def test_string_refs_are_allowed(self) -> None:
        sub = TaskSubmit(
            chat_id="qqbot:group:GROUP_OPENID",
            prompt="do something",
            message_id=10,
            thread_id="qqbot:channel:THREAD",
            parent_agent="main",
            transport="qqbot",
        )
        assert sub.chat_id == "qqbot:group:GROUP_OPENID"
        assert sub.thread_id == "qqbot:channel:THREAD"


class TestTaskResult:
    def test_fields(self) -> None:
        result = TaskResult(
            task_id="abc",
            chat_id=1,
            parent_agent="main",
            name="test",
            prompt_preview="short",
            result_text="done!",
            delivery_text="short done!",
            status="done",
            elapsed_seconds=5.0,
            provider="claude",
            model="opus",
        )
        assert result.status == "done"
        assert result.error == ""
        assert result.delivery_text == "short done!"

    def test_thread_id_default(self) -> None:
        result = TaskResult(
            task_id="x",
            chat_id=1,
            parent_agent="main",
            name="t",
            prompt_preview="p",
            result_text="r",
            status="done",
            elapsed_seconds=0.0,
            provider="c",
            model="m",
        )
        assert result.thread_id is None

    def test_thread_id_set(self) -> None:
        result = TaskResult(
            task_id="x",
            chat_id=1,
            parent_agent="main",
            name="t",
            prompt_preview="p",
            result_text="r",
            status="done",
            elapsed_seconds=0.0,
            provider="c",
            model="m",
            thread_id=99,
        )
        assert result.thread_id == 99

    def test_string_refs_are_allowed(self) -> None:
        result = TaskResult(
            task_id="x",
            chat_id="qqbot:c2c:OPENID",
            parent_agent="main",
            name="t",
            prompt_preview="p",
            result_text="r",
            status="done",
            elapsed_seconds=0.0,
            provider="c",
            model="m",
            transport="qqbot",
            thread_id="qqbot:channel:THREAD",
        )
        assert result.chat_id == "qqbot:c2c:OPENID"
        assert result.thread_id == "qqbot:channel:THREAD"

    def test_delivery_text_defaults_empty(self) -> None:
        result = TaskResult(
            task_id="x",
            chat_id=1,
            parent_agent="main",
            name="t",
            prompt_preview="p",
            result_text="r",
            status="done",
            elapsed_seconds=0.0,
            provider="c",
            model="m",
        )
        assert result.delivery_text == ""
