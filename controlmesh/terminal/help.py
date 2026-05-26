"""Local help text for the ControlMesh terminal."""

from __future__ import annotations


TERMINAL_HELP = """ControlMesh Terminal

Core:
  help                 Show this help
  status               Show ControlMesh status
  model                Show or change the active model
  diagnose             Run diagnostics
  exit                 Quit the terminal

Runtime:
  tasks list           List tasks
  tasks doctor         Check task runtime health
  agents               List agents
  cron list            List cron jobs

Memory/history:
  memory today         Show today's memory
  memory search <query>
  history
  sessions

Interaction:
  <message>            Chat with the selected model
  chat <message>       Chat with the model
  /chat <message>      Chat with the model
  native               Enter the provider-native CLI
  /native              Enter the provider-native CLI
  inbox                Show terminal inbox
"""
