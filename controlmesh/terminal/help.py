"""Local help text for the ControlMesh terminal."""

from __future__ import annotations


TERMINAL_HELP = """ControlMesh

Core:
  <message>            Chat with the selected model
  model                Show current model and switch commands
  model <provider>     Switch to provider default model
  model <provider> <model>
  status               Show runtime status
  native               Open the raw provider CLI
  help                 Show this help
  exit                 Quit

Runtime:
  tasks list           List tasks
  tasks doctor         Check task runtime health
  tasks sessions <query>
                       Find OpenCode history through local History Viewer
  tasks inspect <session_id>
                       Inspect native identity and revision
  tasks adopt --session <id> --revision <rev> --directory <cwd>
              --repo <repo> --model <provider/model> -- <instruction>
                       Adopt an inspected native session into TaskHub
  tasks recover --task <id> --revision <rev> -- <instruction>
                       Recover an interrupted native task after inspection
  agents               List agents
  cron list            List cron jobs

Memory:
  memory today         Show today's memory
  memory search <query>
  history
  sessions

Compatibility:
  chat <message>       Explicit chat form
  /chat <message>      Explicit chat form
  /native              Same as native
  /help                Same as help
  inbox                Show terminal inbox
"""
