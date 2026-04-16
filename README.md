# ControlMesh

中文 | [English](#english)

ControlMesh 是一个 runtime-first 的 agent harness。

它的核心不是包装某个单一模型 API，而是把官方 CLI 作为执行单元，把聊天入口、后台任务、文件工作区、受控写回和运行时控制面收进同一个系统里。

当前主干叫 **ControlMesh Runtime**。

公开版本当前已经具备这些能力：

- 通过官方 CLI 驱动 `claude`、`codex`、`gemini`
- Telegram、Matrix，以及一条早期 Feishu bot 接入面
- 单聊、群话题、多上下文 session、后台任务、子代理
- 文件型工作区与运行时状态目录：`~/.controlmesh/`
- 基于 evidence / summary / promotion 的 ControlMesh Runtime 骨架
- 控制面入口：signal / query / update / controlled promotion

## 中文

### 这是什么

ControlMesh 不是“另一个聊天壳”。

它更接近一个面向实际工作的 agent runtime：

- 用你已经安装和订阅的官方 CLI 直接执行
- 让不同聊天上下文共享同一套工作区和工具
- 让长任务、自动化任务和子代理进入同一个运行时
- 把 evidence、summary、promotion 和 canonical write-back 分层处理

这意味着它既能拿来聊天驱动开发，也能逐步长成更强的 runtime control plane。

### 当前能做什么

- 在 Telegram 或 Matrix 中直接驱动官方编码 CLI
- 在一个群里用多个 topic / room 形成隔离上下文
- 开 named session，不污染主上下文
- 把长任务委托到后台任务
- 通过 sub-agent 形成隔离工作区
- 使用 cron / webhook / heartbeat 做轻量自动化
- 使用 ControlMesh Runtime 的 evidence、summary、promotion 基础链路

### 当前不是什么

- 不是大而全的云编排平台
- 不是多 worker 集群调度系统
- 不是数据库优先的重基础设施框架
- 不是 UI-first 产品

当前版本的方向很明确：
先把 runtime 语义、控制边界和可审计写回做硬，再逐步扩执行面。

### 快速开始

```bash
pipx install controlmesh
controlmesh
```

安装包名和 CLI 名都叫 `controlmesh`。

首次启动会引导你完成：

- 官方 CLI 可用性检查
- Telegram / Matrix 入口配置
- 时区设置
- 可选 Docker
- 可选后台服务安装

### 基本要求

- Python 3.11+
- 至少安装一个官方 CLI：`claude`、`codex`、`gemini`
- 至少一种聊天入口：
  - Telegram Bot Token
  - Matrix 账号
  - Feishu 自建应用机器人（早期接入面，需要先在飞书开放平台创建 app）

Matrix 额外安装：

```bash
controlmesh install matrix
```

Feishu 不是 `controlmesh install matrix` 这类依赖安装问题。它需要先有一个飞书自建应用机器人：

```bash
controlmesh auth feishu setup
controlmesh auth feishu doctor
controlmesh auth feishu plan --requested-scope im:message --app-scope im:message
controlmesh auth feishu route --error-kind app_scope_missing --required-scope im:message --permission-url "<url>"
```

`setup` 会说明零 app 用户如何先创建 Feishu app；`doctor` 会在可用时委托独立的 `feishu-auth-kit` 做 app/scopes 诊断；`plan/route/retry` 复用 `feishu-auth-kit orchestration` 的 OpenClaw 式授权编排原语。`controlmesh auth feishu login` 仍然只是复用已有 app 做认证，不会替你创建机器人。详见 [`docs/feishu-setup.md`](docs/feishu-setup.md)。

### 核心交互模型

ControlMesh 当前支持五层使用方式：

1. 单聊主代理
2. 群 topic / 多 room 隔离上下文
3. named session
4. 后台任务
5. sub-agent

它们共享的不是上下文，而是同一个工作区：

```text
~/.controlmesh/
```

上下文隔离，工具与文件共享；子代理则可以拥有自己的隔离工作区。

### 运行时与控制面

当前仓库里的新主干是 **ControlMesh Runtime**。

它已经开始形成一条可验证的运行时链路：

- execution evidence
- task summary / line summary
- controller-approved promotion
- controlled write-back to canonical

并且已经有最薄的一层 control surface：

- `signal`
- `query`
- `update`

这不是最终形态，但已经不是“只会聊天”的壳。

### 文档入口

- 安装说明：[`docs/installation.md`](docs/installation.md)
- 文档总览：[`docs/README.md`](docs/README.md)
- Harness / Runtime 设计：[`docs/modules/harness.md`](docs/modules/harness.md)
- 计划与控制面文件：[`plans/README.md`](plans/README.md)

### 命令示例

```bash
controlmesh
controlmesh status
controlmesh restart
controlmesh service install
controlmesh agents add NAME
controlmesh api enable
controlmesh install matrix
```

### 许可证

本仓库采用 MIT License。见 [`LICENSE`](LICENSE)。

---

## English

ControlMesh is a runtime-first agent harness.

It is built around official coding CLIs as execution units, then layers chat ingress, background tasks, shared workspaces, controlled promotion, and a runtime control surface on top.

The new core spine is **ControlMesh Runtime**.

### What it does today

- Runs official `claude`, `codex`, and `gemini` CLIs
- Supports Telegram, Matrix, and an early Feishu bot-only path
- Supports single chat, topic-based isolation, named sessions, background tasks, and sub-agents
- Uses a file-backed workspace and runtime state under `~/.controlmesh/`
- Ships the first ControlMesh Runtime chain for evidence, summaries, promotion, and controlled canonical write-back
- Exposes a thin runtime control surface with `signal`, `query`, and `update`

### What it is not

- Not a heavyweight cloud orchestration platform
- Not a multi-worker cluster scheduler
- Not a database-first infrastructure framework
- Not a UI-first product

The current direction is deliberate:
make runtime semantics, control boundaries, and auditable write-back solid first, then expand outward.

### Quick start

```bash
pipx install controlmesh
controlmesh
```

The package name and CLI entrypoint are both `controlmesh`.

On first run, ControlMesh guides you through:

- official CLI checks
- Telegram or Matrix setup
- timezone
- optional Docker
- optional background service installation

### Requirements

- Python 3.11+
- At least one official CLI installed: `claude`, `codex`, or `gemini`
- At least one transport:
  - Telegram Bot Token
  - Matrix account
  - Feishu self-built app bot (early path; create the app in Feishu Open Platform first)

Install Matrix support with:

```bash
controlmesh install matrix
```

Feishu is not an optional dependency like `controlmesh install matrix`. You need an existing Feishu self-built app bot first:

```bash
controlmesh auth feishu setup
controlmesh auth feishu doctor
controlmesh auth feishu plan --requested-scope im:message --app-scope im:message
```

These commands explain the zero-app setup boundary, delegate app diagnostics to the standalone `feishu-auth-kit`, and expose OpenClaw-style auth orchestration planning. `controlmesh auth feishu login` reuses an existing app; it does not create the bot. See [`docs/feishu-setup.md`](docs/feishu-setup.md).

### Interaction model

ControlMesh currently supports five layers of use:

1. Main single-chat agent
2. Group topics / multiple rooms as isolated contexts
3. Named sessions
4. Background tasks
5. Sub-agents

Most of these share one workspace:

```text
~/.controlmesh/
```

Contexts are isolated; tools and files are shared. Sub-agents can have fully isolated workspaces.

### Runtime control plane

The new spine inside this repository is **ControlMesh Runtime**.

It already supports a structured runtime path:

- execution evidence
- task summary / line summary
- controller-approved promotion
- controlled canonical write-back

And it now exposes a thin control surface:

- `signal`
- `query`
- `update`

This is still an early runtime, but it is no longer just a chat wrapper.

### Docs

- Installation: [`docs/installation.md`](docs/installation.md)
- Docs index: [`docs/README.md`](docs/README.md)
- Harness / Runtime design: [`docs/modules/harness.md`](docs/modules/harness.md)
- Plan and control-plane files: [`plans/README.md`](plans/README.md)

### Common commands

```bash
controlmesh
controlmesh status
controlmesh restart
controlmesh service install
controlmesh agents add NAME
controlmesh api enable
controlmesh install matrix
```

### License

This repository is released under the MIT License. See [`LICENSE`](LICENSE).
