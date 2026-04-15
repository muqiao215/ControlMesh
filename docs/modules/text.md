# text/

Shared user-facing response text helpers used across bot and orchestrator layers.

## Files

- `text/response_format.py`: formatter helpers, status/error text builders, startup/recovery text

## Public API (`response_format.py`)

- `SEP`: shared section separator
- `fmt(*blocks)`: join non-empty blocks with blank lines
- `normalize_tool_name(name)`: normalizes shell-related tool names (`bash`, `powershell`, `cmd`, `sh`, `zsh`, `shell`) to `"Shell"` for display; non-shell tool names are returned unchanged
- `classify_cli_error(raw)`
- `session_error_text(model, cli_detail="")`
- `new_session_text(provider)`
- `stop_text(killed, provider)`
- `timeout_warning_text(remaining)`
- `timeout_extended_text(extension, remaining_ext)`
- `timeout_result_text(elapsed, configured)`
- `timeout_error_text(model, timeout_seconds)`
- `format_technical_footer(model_name, total_tokens, input_tokens, cost_usd, duration_ms)`: formats a `---`-separated footer line with model name, token counts (in/out), cost (when > 0), and duration (when provided)
- `startup_notification_text(kind)`
- `recovery_notification_text(kind, prompt_preview, session_name="")`

## Integration points

- `messenger/telegram/handlers.py`: `/new`, `/stop`
- `messenger/telegram/app.py`: help/info/restart and various user-facing blocks
- `messenger/telegram/file_browser.py`, `messenger/telegram/welcome.py`
- `orchestrator/commands.py`: `/status`, `/memory`, `/diagnose`, `/upgrade`, etc.
- `orchestrator/flows.py`: session error rendering and timeout-facing text
- `orchestrator/selectors/cron_selector.py`: cron selector text blocks
- `messenger/telegram/message_dispatch.py`: maps timeout status labels when emitted, appends technical footer when `config.scene.technical_footer=true`
- `messenger/matrix/bot.py`: appends technical footer for Matrix responses
- `messenger/telegram/edit_streaming.py`, `messenger/telegram/streaming.py`, `messenger/matrix/streaming.py`: use `normalize_tool_name()` for tool activity rendering
- `api/server.py`: uses `normalize_tool_name()` for `tool_activity` WebSocket events

## Behavior notes

- error hints are pattern-based and intentionally conservative
- session error text explicitly states that session context is preserved
- timeout warning/extension helpers exist, but visible status labels depend on emitted system-status events
