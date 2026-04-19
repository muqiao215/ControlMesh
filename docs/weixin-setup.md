# WeChat / Weixin Setup

ControlMesh includes a Weixin iLink entrypoint for teams that want a WeChat
chat surface in addition to Feishu native and Telegram.

## What You Get

- QR-based Weixin login
- long-poll inbound messages
- plain-text replies through the same WeChat conversation
- restart-safe credential and runtime state under `~/.controlmesh/weixin_store/`

## Setup

Enable the transport in `~/.controlmesh/config/config.json`:

```json
{
  "transports": ["weixin"],
  "weixin": {
    "enabled": true
  }
}
```

Run the QR login flow:

```bash
controlmesh auth weixin setup
```

Scan the QR code, then send the WeChat bot a first message such as `你好`. That
first message establishes the reply context required by Weixin iLink.

Check readiness:

```bash
controlmesh auth weixin status
```

When status reports `Weixin setup complete`, start or restart ControlMesh.

## Common Operations

```bash
controlmesh auth weixin status
controlmesh auth weixin reauth
controlmesh auth weixin logout
```

## Boundaries

- Weixin is disabled by default because it requires QR-derived credentials.
- If login is complete but `transports` does not include `weixin`, ControlMesh
  will not receive or reply through WeChat.
- If status says `waiting_first_message`, send one message to the WeChat bot to
  establish the reply context.
