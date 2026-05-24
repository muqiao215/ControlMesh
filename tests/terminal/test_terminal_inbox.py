from __future__ import annotations

from controlmesh.terminal.inbox import TerminalInbox, TerminalInboxItem


def test_inbox_round_trips_and_marks_read(tmp_path) -> None:
    inbox = TerminalInbox(tmp_path / "terminal_inbox.jsonl")
    item = TerminalInboxItem(kind="agent_message", title="Coder", body="ready")

    inbox.append(item)

    unread = inbox.list_unread()
    assert len(unread) == 1
    assert unread[0].title == "Coder"

    inbox.mark_read(item.id)

    assert inbox.list_unread() == []
    assert inbox.list_all()[0].read is True
