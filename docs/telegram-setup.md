# Telegram Setup

ControlMesh includes a mature Telegram entrypoint for teams that want a
token-based bot surface alongside Feishu native and WeChat/Weixin.

## What You Get

- personal DM entrypoint
- optional group and topic usage
- file delivery through the same Telegram conversation
- stable long-running bot sessions with the standard ControlMesh runtime

## Setup

Create a bot with [@BotFather](https://t.me/BotFather), then collect:

- the bot token
- your Telegram user ID from [@userinfobot](https://t.me/userinfobot)
- optional group IDs if you want the bot to operate in groups

Enable the transport in `~/.controlmesh/config/config.json`:

```json
{
  "transports": ["telegram"],
  "telegram_token": "<bot_token>",
  "allowed_user_ids": [123456789]
}
```

If you want group access, also set `allowed_group_ids`.

Start ControlMesh:

```bash
controlmesh
```

Then send the bot a direct message in Telegram to confirm the chat path is
live.

## Common Operations

```bash
controlmesh status
controlmesh restart
controlmesh tasks doctor
controlmesh tasks list
```

## Boundaries

- Telegram is the most straightforward token-based entrypoint, but it is not
  the Feishu native/CardKit path.
- Group usage is fail-closed: the group and the sending user both need to be
  allowed.
- For a QR-login entrypoint instead of a bot token, use
  [WeChat / Weixin Setup](weixin-setup.md).
