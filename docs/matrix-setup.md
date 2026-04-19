# Matrix Setup Guide

ControlMesh's primary public chat entrypoints are Feishu native, Telegram, and
WeChat/Weixin. Matrix is an optional secondary compatibility transport you can
add at any time — either as the only transport or running alongside the other
entrypoints.

## 1. Install Matrix support

Matrix requires the `matrix-nio` library, which is not included in the base install.

```bash
# pipx (recommended)
controlmesh install matrix

# pip
pip install "controlmesh[matrix]"

# from source
pip install -e ".[matrix]"
```

## 2. Create a Matrix account for your bot

Create a dedicated account on any Matrix homeserver. You need:

| What | Example |
|---|---|
| Homeserver URL | `https://matrix-client.matrix.org` |
| User ID | `@my_controlmesh:matrix.org` |
| Password | (the account password) |

You can use any homeserver — matrix.org, your own Synapse/Conduit, etc.

## 3. Configure

### Option A: Interactive setup (fresh install)

```bash
controlmesh
```

The onboarding wizard asks which transport to use. Select **Matrix** and follow the prompts for homeserver, user ID, password, and allowed users.

### Option B: Add Matrix to existing Telegram setup

Edit `~/.controlmesh/config/config.json`:

```json
{
  "transports": ["telegram", "matrix"],

  "telegram_token": "YOUR_TELEGRAM_TOKEN",
  "allowed_user_ids": [123456789],

  "matrix": {
    "homeserver": "https://matrix-client.matrix.org",
    "user_id": "@my_controlmesh:matrix.org",
    "password": "YOUR_MATRIX_PASSWORD",
    "allowed_rooms": [],
    "allowed_users": ["@you:matrix.org"],
    "store_path": "matrix_store"
  }
}
```

### Option C: Matrix only

```json
{
  "transport": "matrix",

  "matrix": {
    "homeserver": "https://matrix-client.matrix.org",
    "user_id": "@my_controlmesh:matrix.org",
    "password": "YOUR_MATRIX_PASSWORD",
    "allowed_rooms": [],
    "allowed_users": ["@you:matrix.org"]
  }
}
```

## 4. Start

```bash
controlmesh
```

On first start, controlmesh logs in with the password and saves credentials to `~/.controlmesh/matrix_store/credentials.json`. After that, the password is no longer needed — token-based auth is used automatically.

## Configuration reference

| Field | Required | Description |
|---|---|---|
| `homeserver` | yes | Full URL including `https://` |
| `user_id` | yes | `@botname:homeserver.domain` |
| `password` | first run | Used for initial login, then token takes over |
| `access_token` | auto | Saved after first login, or set manually together with `device_id` |
| `device_id` | auto | Saved after first login, or set manually together with `access_token` |
| `allowed_rooms` | no | Room IDs/aliases to operate in. Empty = all rooms |
| `allowed_users` | no | Matrix user IDs allowed to interact. Empty = all users |
| `store_path` | no | Relative to controlmesh_home. Default: `matrix_store` |

## Authorization

| Setting | Effect |
|---|---|
| `allowed_rooms: []` | Bot operates in all rooms it's invited to |
| `allowed_rooms: ["!abc:server"]` | Bot only operates in listed rooms |
| `allowed_users: ["@you:server"]` | Only listed users can talk to the bot |
| `group_mention_only: true` | In multi-user rooms, bot requires @mention or reply |

When invited to an unauthorized room, the bot auto-rejects and leaves.

## Differences from Telegram

| Feature | Telegram | Matrix |
|---|---|---|
| Streaming | Live message edits | Segment-based (separate messages) |
| Buttons | Inline keyboards | Emoji reactions (1-10) + text input |
| Command prefix | `/command` | `/command` or `!command` |
| Topics | Forum topics (one group) | Separate rooms |
| Media files | Stored in `telegram_files/` | Stored in `matrix_files/` |
| Sub-agent setup | `controlmesh agents add` (interactive) | Manual via `agents.json` |

## Running both transports

With `"transports": ["telegram", "matrix"]`, both run in parallel sharing the same orchestrator, sessions, workspace, and CLI processes. A message sent via Telegram and one via Matrix both reach the same agent.

Session keys are transport-prefixed in persistence (`tg:<chat_id>` vs `mx:<room-int>`), so conversations do not collide across transports. Matrix room IDs are mapped to deterministic ints before persistence.

## Troubleshooting

**Bot not joining rooms:**
- Check `allowed_rooms` — if set, only listed rooms are joined
- Invite the bot from within the room

**"matrix-nio is required" error:**
- Run `controlmesh install matrix` to install the dependency

**Login fails:**
- Verify homeserver URL (must include `https://`)
- Check user ID format: `@name:server.domain`
- Some homeservers require the client API URL (e.g. `https://matrix-client.matrix.org` instead of `https://matrix.org`)

**Token expired / bot stops responding:**
- Delete `~/.controlmesh/matrix_store/credentials.json` and restart — controlmesh will re-login with password
