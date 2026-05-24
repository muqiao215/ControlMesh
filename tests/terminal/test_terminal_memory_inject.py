from __future__ import annotations

from controlmesh.terminal.memory_context import TerminalMemoryContext


def test_memory_inject_affects_next_prompt_only(tmp_path) -> None:
    memory = TerminalMemoryContext(paths=object())  # type: ignore[arg-type]
    memory._last_hits["hit_001"] = "memory block"

    memory.inject("hit_001")

    prompt = memory.consume_for_prompt("hello")
    assert "memory block" in prompt
    assert prompt.endswith("hello")
    assert memory.consume_for_prompt("again") == "again"
