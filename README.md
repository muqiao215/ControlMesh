# ControlMesh

中文 | [English](#english)

ControlMesh turns official coding CLIs into always-on chat agents for real work.

Use Claude, Codex, Gemini, and other local command-line agents from Telegram,
Matrix, or Feishu. ControlMesh gives them a persistent workspace, long-running
tasks, file output, Feishu cards, and operator-friendly service controls.

![ControlMesh chat agent overview](docs/assets/controlmesh-feishu-runtime.svg)

## 中文

### 一句话

ControlMesh 是一个开源的聊天式 AI 工作台：把官方编码 CLI 接进
Telegram、Matrix 和 Feishu，让它们像长期在线的工作机器人一样执行任务。

它不是一次性的聊天壳。它面向真实工作流：持续上下文、后台任务、文件交付、
服务重启、Feishu 卡片、权限引导，以及可部署到 VPS / 树莓派的常驻运行。

### 适合谁

- 想把 Claude、Codex、Gemini 放进 Telegram 或 Feishu 里长期使用的个人和小团队。
- 想在一台 VPS、NAS 或树莓派上运行 24/7 AI 工作入口的开发者。
- 需要让 AI 在同一个工作区里读写文件、跑命令、交付结果，而不是只回答文本的人。
- 需要 Feishu 原生体验：机器人、卡片、权限引导、群消息和文件/媒体回复。

### 产品能力

| 能力 | 说明 |
|---|---|
| 官方 CLI 接入 | 复用 Claude、Codex、Gemini 等官方命令行工具 |
| 多聊天入口 | Telegram、Matrix、Feishu |
| 持久工作区 | 会话、文件、输出和运行状态保存在本机 |
| 长任务 | 后台任务、定时任务、webhook、运行状态检查 |
| 多会话 | 单聊、群组、topic、room、named session 隔离上下文 |
| 文件交付 | 文本、图片、音频、文档等输出可直接发回聊天 |
| Feishu Native | 扫码创建机器人、CardKit 单卡、权限引导、原生 OAPI 工具 |
| Feishu Bridge | 复用已有 app credentials，快速接入 Feishu 消息入口 |
| 运维友好 | systemd、status、doctor、restart、配置校验 |

### Feishu 体验

ControlMesh 提供两种 Feishu 模式：

**Native 模式**适合从零创建一个更完整的 Feishu 工作机器人。

- 通过 [`feishu-auth-kit`](https://github.com/muqiao215/feishu-auth-kit)
  完成扫码创建、凭证写回和权限引导。
- 支持 CardKit 单卡展示运行状态、工具步骤和最终结果。
- 支持 `/feishu_auth_all` 进行当前 MVP 工具所需权限的批量引导。
- 已接入第一批只读原生工具：联系人搜索、用户读取、群消息读取、Drive 文件列表。

**Bridge 模式**适合已经有 Feishu app，只想把 Feishu 当作消息入口。

- 使用已有 `app_id` / `app_secret`。
- 更轻量，适合文本回复和基础卡片预览。
- 不要求从零创建新机器人。

### 快速开始

```bash
pipx install controlmesh
controlmesh
```

从源码运行：

```bash
git clone https://github.com/muqiao215/ControlMesh.git
cd ControlMesh
python -m venv .venv
. .venv/bin/activate
pip install -e ".[matrix,api]"
controlmesh
```

首次启动会引导你完成 CLI 检查、聊天入口配置、时区设置和可选服务安装。

### Feishu 从零配置

Native 模式：

```bash
controlmesh auth feishu setup
controlmesh auth feishu register-begin
controlmesh auth feishu register-poll --device-code "<device_code>" --interval 5 --expires-in 600
controlmesh auth feishu doctor
controlmesh auth feishu probe
```

Bridge 模式：

```bash
controlmesh auth feishu status
controlmesh auth feishu doctor
controlmesh auth feishu login
```

### 常用命令

```bash
controlmesh status
controlmesh restart
controlmesh service install
controlmesh agents add NAME
controlmesh api enable
```

### 文档

- 安装：[`docs/installation.md`](docs/installation.md)
- Feishu 设置：[`docs/feishu-setup.md`](docs/feishu-setup.md)
- 文档总览：[`docs/README.md`](docs/README.md)
- 配置示例：[`config.example.json`](config.example.json)

### 许可证

MIT License. See [`LICENSE`](LICENSE).

---

## English

ControlMesh is an open-source chat workbench for command-line coding agents.

It connects official CLIs such as Claude, Codex, and Gemini to Telegram,
Matrix, and Feishu, then gives them persistent workspaces, long-running jobs,
file delivery, Feishu cards, and service controls.

### Who It Is For

- Developers who want Claude, Codex, or Gemini inside Telegram or Feishu.
- Small teams that want an always-on AI work entrypoint on a VPS, NAS, or Raspberry Pi.
- Builders who need agents to work with files and commands, not just produce chat text.
- Feishu users who want native bot onboarding, cards, permission flows, and read-only OAPI tools.

### Features

| Feature | Description |
|---|---|
| Official CLI support | Run Claude, Codex, Gemini, and other local CLI agents |
| Chat transports | Telegram, Matrix, Feishu |
| Persistent workspace | Keep sessions, files, outputs, and runtime state on your machine |
| Long-running work | Background tasks, cron jobs, webhooks, and health checks |
| Session isolation | Direct chats, group topics, rooms, and named sessions |
| File delivery | Return text, images, audio, documents, and generated artifacts |
| Feishu Native | Scan-created bot, CardKit cards, permission onboarding, native OAPI tools |
| Feishu Bridge | Reuse an existing Feishu app as a lightweight chat bridge |
| Operations | systemd service, status, doctor, restart, config validation |

### Feishu Modes

**Native mode** is for a full Feishu-first bot experience.

- Uses [`feishu-auth-kit`](https://github.com/muqiao215/feishu-auth-kit)
  for scan-to-create onboarding, credential write-back, and permission flows.
- Shows status, tool steps, and final output in a single Feishu card.
- Provides `/feishu_auth_all` for guided authorization of the current MVP tools.
- Includes first read-only native tools for contacts, users, group messages, and Drive files.

**Bridge mode** is for existing Feishu apps.

- Reuses your current `app_id` and `app_secret`.
- Keeps the runtime lightweight.
- Works well when Feishu is only one of several chat entrypoints.

### Quick Start

```bash
pipx install controlmesh
controlmesh
```

Run from source:

```bash
git clone https://github.com/muqiao215/ControlMesh.git
cd ControlMesh
python -m venv .venv
. .venv/bin/activate
pip install -e ".[matrix,api]"
controlmesh
```

### Feishu Setup

Native mode:

```bash
controlmesh auth feishu setup
controlmesh auth feishu register-begin
controlmesh auth feishu register-poll --device-code "<device_code>" --interval 5 --expires-in 600
controlmesh auth feishu doctor
controlmesh auth feishu probe
```

Bridge mode:

```bash
controlmesh auth feishu status
controlmesh auth feishu doctor
controlmesh auth feishu login
```

### Documentation

- Installation: [`docs/installation.md`](docs/installation.md)
- Feishu setup: [`docs/feishu-setup.md`](docs/feishu-setup.md)
- Documentation index: [`docs/README.md`](docs/README.md)
- Example config: [`config.example.json`](config.example.json)

### License

MIT License. See [`LICENSE`](LICENSE).
