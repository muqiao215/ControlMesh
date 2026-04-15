# Installation Guide

## Requirements

1. Python 3.11+
2. `pipx` (recommended) or `pip`
3. At least one authenticated provider CLI:
   - Claude Code CLI: `npm install -g @anthropic-ai/claude-code && claude auth`
   - Codex CLI: `npm install -g @openai/codex && codex auth`
   - Gemini CLI: `npm install -g @google/gemini-cli` and authenticate in `gemini`
4. One of these messaging transports:
   - **Telegram**: Bot token from [@BotFather](https://t.me/BotFather) + user ID from [@userinfobot](https://t.me/userinfobot)
   - **Matrix**: install Matrix support first (`controlmesh install matrix` or `pip install \"controlmesh[matrix]\"`), then provide homeserver URL, user ID, and password/access token
5. Docker optional (recommended for sandboxing)

## Install

### pipx (recommended)

```bash
pipx install controlmesh
```

### pip

```bash
pip install controlmesh
```

### from source

```bash
git clone https://github.com/muqiao215/ControlMesh.git
cd controlmesh
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## First run

```bash
controlmesh
```

On first run, onboarding does:

- checks Claude/Codex/Gemini auth status,
- asks which transport to use (Telegram or Matrix),
- collects transport credentials,
- asks timezone,
- offers Docker sandboxing (with optional AI/ML package selection),
- offers service install,
- writes config and seeds `~/.controlmesh/`.

Multiple transports can run in parallel (e.g. Telegram + Matrix
simultaneously). After initial setup, configure the `transports` array
in `config.json`. See [config.md](config.md) for details.

If service install succeeds, onboarding returns without starting foreground bot.

## Platform notes

### Linux

```bash
sudo apt update && sudo apt install python3 python3-pip python3-venv nodejs npm
pip install pipx
pipx ensurepath
pipx install controlmesh
controlmesh
```

Optional Docker:

```bash
sudo apt install docker.io
sudo usermod -aG docker $USER
```

### macOS

```bash
brew install python@3.11 node pipx
pipx ensurepath
pipx install controlmesh
controlmesh
```

### Windows (native)

```powershell
winget install Python.Python.3.11
winget install OpenJS.NodeJS
pip install pipx
pipx ensurepath
pipx install controlmesh
controlmesh
```

Native Windows is fully supported, including service management via Task Scheduler.

### Windows (WSL)

WSL works too. Install like Linux inside WSL.

```bash
sudo apt update && sudo apt install python3 python3-pip python3-venv nodejs npm
pip install pipx
pipx ensurepath
pipx install controlmesh
controlmesh
```

## Docker sandboxing

Enable in config:

```json
{
  "docker": {
    "enabled": true
  }
}
```

Notes:

- Docker image is built on first use when missing.
- Container is reused between calls.
- On Linux, controlmesh maps UID/GID to avoid root-owned files.
- If Docker setup fails at startup, controlmesh logs warning and falls back to host execution.

Docker CLI shortcuts:

```bash
controlmesh docker enable
controlmesh docker disable
controlmesh docker rebuild
controlmesh docker mount /path/to/project
controlmesh docker unmount /path/to/project
controlmesh docker mounts
controlmesh docker extras
controlmesh docker extras-add <id>
controlmesh docker extras-remove <id>
```

- `enable` / `disable` toggles `docker.enabled` in `config.json` (restart bot afterwards).
- `rebuild` stops the bot, removes container + image, and forces fresh build on next start.
- `mount` / `unmount` manage `docker.mounts` entries.
- mounts are available in-container under `/mnt/<name>` (basename-based mapping with collision suffixes).
- run `controlmesh docker mounts` to inspect effective mapping and broken paths.
- `extras` lists all optional packages with their selection status.
- `extras-add` / `extras-remove` manage optional AI/ML packages (Whisper, PyTorch, OpenCV, etc.) in `config.json`. Transitive dependencies are resolved automatically.
- after changing extras, run `controlmesh docker rebuild` to apply. Build output is streamed live to the terminal.

## Direct API server (optional)

Preferred enable path:

```bash
controlmesh api enable
```

This writes/updates the `api` block in `config.json` and generates a token if missing.

`controlmesh api enable` requires PyNaCl (used for E2E encryption). If it is missing:

```bash
# pipx install
pipx inject controlmesh PyNaCl

# pip install
pip install "controlmesh[api]"
```

Manual config equivalent:

```json
{
  "api": {
    "enabled": true,
    "host": "0.0.0.0",
    "port": 8741,
    "token": "",
    "chat_id": 0,
    "allow_public": false
  }
}
```

Notes:

- token is generated and persisted by `controlmesh api enable` (runtime also generates it on API start if still empty).
- WebSocket auth frame must include `type="auth"`, `token`, and `e2e_pk` (client ephemeral public key).
- endpoints:
  - WebSocket: `ws://<host>:8741/ws`
  - health: `GET /health`
  - file download: `GET /files?path=...` (Bearer token)
  - file upload: `POST /upload` (Bearer token, multipart)
- default API session uses `api.chat_id` by truthiness (`0` falls back), else first `allowed_user_ids` entry (fallback `1`); clients can override `chat_id` in auth payload.
- recommended deployment is a private network (for example Tailscale).

## Background service

Install:

```bash
controlmesh service install
```

Manage:

```bash
controlmesh service status
controlmesh service start
controlmesh service stop
controlmesh service logs
controlmesh service uninstall
```

Backend details and platform quirks: [Service Management](modules/service_management.md)

Backends:

- Linux: `systemd --user` service `~/.config/systemd/user/controlmesh.service`
- macOS: Launch Agent `~/Library/LaunchAgents/dev.controlmesh.plist`
- Windows: Task Scheduler task `controlmesh`

Linux note:

- user services survive logout/start on boot only when user linger is enabled (`sudo loginctl enable-linger <user>`). Installer attempts this and prints a hint when it cannot set linger.

Windows note:

- service install prefers `pythonw.exe -m controlmesh` (no visible console window),
- installed Task Scheduler service uses logon trigger + restart-on-failure retries,
- some systems require elevated terminal permissions for Task Scheduler operations.

Log command behavior:

- Linux: live `journalctl --user -u controlmesh -f`
- macOS/Windows: recent lines from `~/.controlmesh/logs/agent.log` (fallback newest `*.log`)

## VPS notes

Small Linux VPS is enough. Typical path:

```bash
ssh user@host
sudo apt update && sudo apt install python3 python3-pip python3-venv nodejs npm docker.io
pip install pipx
pipx ensurepath
pipx install controlmesh
controlmesh
```

Security basics:

- keep SSH key-only auth
- enable Docker sandboxing for unattended automation
- keep `allowed_user_ids` restricted
- use `/upgrade` or `pipx upgrade controlmesh`

## Troubleshooting

### Bot not responding

1. check transport credentials (`telegram_token` / `matrix` block) + allowlists
2. run `controlmesh status`
3. inspect `~/.controlmesh/logs/agent.log`
4. run `/diagnose` in chat

### CLI installed but not authenticated

Authenticate at least one provider and restart:

```bash
claude auth
# or
codex auth
# or
# authenticate in gemini CLI
```

### Docker enabled but not running

```bash
docker info
```

Then validate `docker.enabled` + image/container names in config.

### Webhooks not arriving

- set `webhooks.enabled: true`
- expose `127.0.0.1:8742` through tunnel/proxy when external sender is used
- verify auth settings and hook ID

## Upgrade and uninstall

Upgrade:

```bash
pipx upgrade controlmesh
```

Uninstall:

```bash
pipx uninstall controlmesh
rm -rf ~/.controlmesh  # optional data removal
```
