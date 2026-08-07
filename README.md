# ControlMesh

ControlMesh is a local-first, chat-native task runtime for official coding CLIs. It connects
Claude, Codex, Gemini, OpenCode, and configured providers to persistent workspaces,
background tasks, multi-agent coordination, messaging transports, and operational tools.

## What

ControlMesh lets you:

- work interactively in an enhanced local terminal;
- run the legacy bot runtime through Feishu, Telegram, WeChat, Matrix, and compatible
  transports;
- create persistent background tasks that can ask for input, resume, recover, and deliver
  results;
- coordinate bounded multi-agent topologies on a shared Python runtime;
- inspect tasks, providers, events, topologies, and artifacts through a local read-only Web
  dashboard.

Python remains the authoritative runtime. The TypeScript workspace provides public protocol
models, runtime validation, an SDK, and the local dashboard.

## Quick Start

Install the released CLI:

```bash
pipx install controlmesh
controlmesh
```

`controlmesh` opens the enhanced terminal. Use `/cm` for provider-native mode and `/back`
to return. Start the legacy messaging runtime with:

```bash
controlmesh bot
```

Develop from source:

```bash
git clone https://github.com/muqiao215/ControlMesh.git
cd ControlMesh
uv sync --locked --all-extras --dev
uv run controlmesh
```

Verify the toolchain:

```bash
python scripts/doctor_toolchain.py --strict --require-bun
```

Evaluate the read-only Alpha from an isolated install:

```bash
pipx install --suffix=-alpha "controlmesh[api]==0.42.0a1"
controlmesh-alpha api serve
```

Open the printed local dashboard URL and enter the printed bearer token. The Alpha server
binds only to `127.0.0.1` and exposes read-only `/api/v1` routes; see the
[read-only Alpha guide](docs/read-only-alpha.md) for the complete five-minute flow.

## Documentation

- [Project Context](PROJECT.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Decisions](docs/DECISIONS.md)
- [Installation](docs/installation.md)
- [Read-only Alpha](docs/read-only-alpha.md)
- [Feishu Setup](docs/feishu-setup.md)
- [Telegram Setup](docs/telegram-setup.md)
- [WeChat Setup](docs/weixin-setup.md)
- [Enhanced Terminal](docs/terminal.md)
- [Full Documentation Index](docs/README.md)

Contributors and coding agents should begin with [AGENTS.md](AGENTS.md).

## Status

The Python terminal, bot, task, provider, memory, transport, and multi-agent runtime is the
stable core. The authenticated `/api/v1` facade, TypeScript SDK, and local Web dashboard are
an additive read-only product layer. TypeScript task mutation and runtime replacement remain
blocked until Python golden parity and rollback gates exist.

## License

MIT. See [LICENSE](LICENSE).
