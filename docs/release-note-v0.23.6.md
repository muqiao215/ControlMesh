# ControlMesh v0.23.6

This hotfix hardens slash-command ownership so Telegram and Feishu stay aligned
with the same ControlMesh command boundary.

## Fixes

- Added a shared command ownership registry for ControlMesh-owned slash
  commands, including visible commands, hidden reserved commands, and transport
  classification.
- Kept `get_bot_commands()` display-only, so popup/help menus no longer double
  as the source of command ownership truth.
- Made Telegram native slash passthrough check the shared ownership registry
  before forwarding unknown `/xxx` commands to the active CLI.
- Aligned Feishu command-center cards, native-command cards, and native runtime
  guide text with the same shared command registry, including worker/main-agent
  visibility boundaries.
- Added regression coverage for hidden owned commands such as `/history` so they
  cannot leak into native passthrough.

## Verification

- `uv run pytest tests/test_commands.py tests/messenger/test_commands.py tests/messenger/telegram/test_app.py -q`
- `uv run pytest tests/orchestrator/test_core.py -k "unknown_slash_command or controlmesh_commands_win_inside_native_menu or hidden_owned_commands_win_inside_native_menu or back_command_returns_from_claude_command_menu or command_menu_routes_slash_commands_to_selected_provider" -q`
- `uv run pytest tests/messenger/feishu/test_bot.py -q`
