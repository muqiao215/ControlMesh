# messenger/matrix/

Matrix/Element transport layer (`matrix-nio`): message handling, streaming, buttons, formatting, credentials.

Alternative to Telegram via `config.transport = "matrix"`, or run in parallel with Telegram via `config.transports`.
For shared messenger protocols and the transport registry, see
[messenger.md](messenger.md).

## Files

- `messenger/matrix/bot.py`: `MatrixBot` class implementing `BotProtocol`; message ingestion, command routing, authorization, streaming
- `messenger/matrix/transport.py`: `MatrixTransport` adapter for `MessageBus`; maps envelopes to Matrix room messages
- `messenger/matrix/sender.py`: message formatting and sending; Markdown→HTML, file upload, message splitting, redaction helpers
- `messenger/matrix/credentials.py`: login flow (saved credentials → config token → password login)
- `messenger/matrix/id_map.py`: bidirectional `room_id` ↔ `int` mapping (deterministic SHA256)
- `messenger/matrix/buttons.py`: reaction-based button replacement; emoji digits + numbered text fallback
- `messenger/matrix/formatting.py`: Markdown → Matrix HTML conversion
- `messenger/matrix/typing.py`: typing indicator context manager with periodic keep-alive (5s interval)
- `messenger/matrix/media.py`: incoming media handler; downloads files from homeserver, builds agent prompts via `files/prompt.py`
- `messenger/matrix/startup.py`: Matrix-specific startup (orchestrator, observers, restart sentinel)

## Incoming media

Matrix media (images, audio, video, files) is handled by `messenger/matrix/media.py`:

1. `MatrixBot` registers `_on_media` callbacks for `RoomMessageImage`, `RoomMessageAudio`, `RoomMessageVideo`, `RoomMessageFile`
2. `resolve_matrix_media()` downloads the file via `client.download(mxc=...)` to `workspace/matrix_files/YYYY-MM-DD/`
3. A transport-agnostic prompt is built via `files/prompt.py` (`build_media_prompt`) and injected into the conversation

Files are auto-cleaned by `CleanupObserver` using the same retention as Telegram files.

## Streaming

Matrix uses **segment-based streaming**: text is buffered and flushed as separate messages at tool/system boundaries.

- `_on_delta()`: accumulates text into buffer
- `_on_tool()`: flushes buffer as message; tool/system markers are suppressed (not sent to chat) to keep the conversation clean
- `_on_system()`: flushes buffer; status markers are also suppressed
- Final segment gets button extraction via `ButtonTracker`

### Typing indicator

`MatrixTypingContext` runs a background keep-alive task that re-sends the typing notification every 5 seconds. This is necessary because:

1. Matrix clients (Element) clear the indicator when the bot sends a message
2. The server expires it after 30 seconds

The keep-alive ensures the indicator stays visible throughout the entire response, even when intermediate messages (reasoning segments, tool tags) are sent.

## Buttons

Matrix lacks inline keyboards. Workaround:

- Emoji digit reactions (1️⃣–🔟) on selector messages
- Numbered text list as visual fallback
- Text input matching (`1`, `2`, etc.) for clients without reaction support
- One active button set per room

## Authorization

- **Room-level**: `allowed_rooms` filter (empty = all rooms)
- **User-level**: `allowed_users` filter (empty = all users)
- **Group mention-only**: in multi-user rooms, bot responds only to @mentions or replies to its own messages
- **Important nuance**: when `group_mention_only=true` in non-DM rooms, `allowed_users` is bypassed and room allowlist + mention/reply become the effective gate
- Auto-join allowed rooms on invite; reject + leave unauthorized rooms

## Command routing

Same command set as Telegram, with `!` or `/` prefix:

- Transport-level: `!stop`, `!stop_all`, `!interrupt`, `!restart`, `!new`, `!help`, `!info`, `!session`, `!showfiles`, `!agent_commands`
- Orchestrator-routed: `!status`, `!model`, `!memory`, `!cron`, `!diagnose`, `!upgrade`, `!sessions`, `!tasks`
- Main-agent only: `!agents`, `!agent_start`, `!agent_stop`, `!agent_restart`

## Setup

Matrix can be configured via the interactive setup wizard (`controlmesh onboarding`) or manually in `config.json`.

The wizard prompts for: homeserver URL, bot user ID, password, and allowed users. See [setup_wizard.md](setup_wizard.md).

Runtime support for Matrix sub-agents is built in, but there is one CLI caveat:

- `controlmesh agents add <name>` currently scaffolds Telegram sub-agents only
- Matrix sub-agents are added through `agents.json` or `create_agent.py --transport matrix` (see agent tools `RULES.md`)

## Configuration

```toml
# pyproject.toml
[project.optional-dependencies]
matrix = ["matrix-nio>=0.25.0"]
```

```json
{
  "transport": "matrix",
  "matrix": {
    "homeserver": "https://matrix.example.com",
    "user_id": "@bot:matrix.example.com",
    "password": "...",
    "allowed_rooms": [],
    "allowed_users": ["@user:matrix.example.com"],
    "store_path": "matrix_store"
  }
}
```

### Credential flow

1. On first start, the bot logs in with the `password` and saves credentials to `~/.controlmesh/<store_path>/credentials.json` (mode `0o600`)
2. On subsequent starts, the saved token is restored — password is no longer needed
3. If `access_token` and `device_id` are both set in config instead of password, they are used directly and mirrored into the credentials store
