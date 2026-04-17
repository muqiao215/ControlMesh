# ControlMesh

中文 | [English](#english)

ControlMesh is a Feishu-native task runtime for official coding CLIs.

It turns Claude, Codex, Gemini, and other local command-line agents into a
Feishu bot that can run long background tasks, ask the parent chat for missing
input, resume the worker, and return results through Feishu cards. Telegram,
Matrix, sub-agents, cron, and webhooks remain compatible runtime lanes, but the
public product path is now Feishu native + background task loop.

![ControlMesh chat agent overview](docs/assets/controlmesh-feishu-runtime.svg)

## 中文

### 一句话

ControlMesh 是一个开源的 Feishu native task runtime：把官方编码 CLI 接进飞书，
让它们像长期在线的任务机器人一样执行工作。

它不是一次性的聊天壳。主线是飞书里的后台任务闭环：创建任务、任务后台执行、
任务缺信息时通过 `ask_parent` 回问飞书、父会话恢复任务、结果回到同一聊天上下文。

### 适合谁

- 想把 Claude、Codex、Gemini 变成飞书里的长期任务机器人。
- 需要任务超过 30 秒时自动转后台，不阻塞聊天的人。
- 需要 worker 缺信息时能在飞书里优雅回问并 resume 的团队。
- 想把机器人部署到 VPS、NAS 或树莓派，做 24/7 Feishu 工作入口的开发者。

### 产品能力

| 能力 | 说明 |
|---|---|
| 能力 | 说明 |
|---|---|
| Feishu Native Runtime | 扫码创建机器人、CardKit 单卡、权限引导、原生 OAPI 工具 |
| 后台任务闭环 | `/tasks/create`、`ask_parent`、`resume`、`list` 构成可演示任务 runtime |
| 官方 CLI worker | 复用 Claude、Codex、Gemini 等官方命令行工具执行任务 |
| 持久工作区 | 会话、任务记忆、文件、输出和运行状态保存在本机 |
| 文件交付 | 文本、图片、音频、文档等输出可直接发回飞书 |
| 运维友好 | `tasks doctor`、Feishu doctor、systemd、restart、配置校验 |
| 兼容入口 | Telegram、Matrix、API、sub-agent、cron、webhook 仍可用，但不是首页主线 |

### Feishu 体验

ControlMesh 当前公开主线是 Feishu Native 模式。

最小闭环：

- `controlmesh feishu native bootstrap` 进入友好的飞书原生启动入口。
- 通过 [`feishu-auth-kit`](https://github.com/muqiao215/feishu-auth-kit) 完成扫码创建、凭证写回和权限引导。
- Feishu 卡片展示任务状态、工具步骤和最终结果。
- 长任务通过 task runtime 后台执行，缺信息时走 `/tasks/ask_parent`，父会话再 `/tasks/resume`。
- `/feishu_auth_all` 进行当前 MVP 工具所需权限的批量引导。
- 已接入第一批只读原生工具：联系人搜索、用户读取、群消息读取、Drive 文件列表。

Bridge 模式、Telegram、Matrix、sub-agent、cron 和 webhook 仍是兼容能力；
它们不再是 README 第一屏的产品主线。

### Runtime primitives

任务闭环的稳定 runtime primitives：

- `/tasks/create`
- `/tasks/resume`
- `/tasks/ask_parent`
- `/tasks/list`
- `/interagent/send`

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
controlmesh feishu native bootstrap
controlmesh auth feishu setup
controlmesh auth feishu register-begin
controlmesh auth feishu register-poll --device-code "<device_code>" --interval 5 --expires-in 600
controlmesh auth feishu doctor
controlmesh auth feishu probe
```

任务 runtime：

```bash
controlmesh tasks doctor
controlmesh tasks list
```

### 常用命令

```bash
controlmesh status
controlmesh restart
controlmesh service install
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

ControlMesh is an open-source Feishu-native task runtime for command-line
coding agents.

It turns official CLIs such as Claude, Codex, and Gemini into a Feishu bot
that can spawn long background tasks, ask the parent chat for missing context,
resume the worker, and return results through cards. Telegram, Matrix, and
other transports remain compatible, but the product path is Feishu native plus
the task loop.

### Who It Is For

- Developers who want Claude, Codex, or Gemini as long-running Feishu workers.
- Teams that need a task loop: create, ask-parent, resume, return.
- Builders who need agents to work with files and commands, not just produce chat text.
- Operators who want an always-on Feishu task entrypoint on a VPS, NAS, or Raspberry Pi.

### Features

| Feature | Description |
|---|---|
| Feature | Description |
|---|---|
| Feishu Native Runtime | Scan-created bot, CardKit cards, permission onboarding, native OAPI tools |
| Background task loop | `/tasks/create`, `ask_parent`, `resume`, and `list` form the runtime loop |
| Official CLI workers | Run Claude, Codex, Gemini, and other local CLI agents |
| Persistent workspace | Keep sessions, task memory, files, outputs, and runtime state on your machine |
| File delivery | Return text, images, audio, documents, and generated artifacts |
| Operations | `tasks doctor`, Feishu doctor, systemd service, restart, config validation |
| Compatibility lanes | Telegram, Matrix, API, sub-agents, cron, and webhooks remain available |

### Feishu Modes

**Native mode** is the primary product path.

- `controlmesh feishu native bootstrap` is the product-friendly entrypoint.
- Uses [`feishu-auth-kit`](https://github.com/muqiao215/feishu-auth-kit)
  for scan-to-create onboarding, credential write-back, and permission flows.
- Shows status, tool steps, and final output in a single Feishu card.
- Provides `/feishu_auth_all` for guided authorization of the current MVP tools.
- Includes first read-only native tools for contacts, users, group messages, and Drive files.
- Pairs with the background task runtime so long work can ask the parent chat
  for missing input and then resume cleanly.

Bridge mode and non-Feishu transports remain compatibility options, not the
front-page product narrative.

### Runtime primitives

- `/tasks/create`
- `/tasks/resume`
- `/tasks/ask_parent`
- `/tasks/list`
- `/interagent/send`

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
controlmesh feishu native bootstrap
controlmesh auth feishu setup
controlmesh auth feishu register-begin
controlmesh auth feishu register-poll --device-code "<device_code>" --interval 5 --expires-in 600
controlmesh auth feishu doctor
controlmesh auth feishu probe
```

Task runtime:

```bash
controlmesh tasks doctor
controlmesh tasks list
```

### Documentation

- Installation: [`docs/installation.md`](docs/installation.md)
- Feishu setup: [`docs/feishu-setup.md`](docs/feishu-setup.md)
- Documentation index: [`docs/README.md`](docs/README.md)
- Example config: [`config.example.json`](config.example.json)

### License

MIT License. See [`LICENSE`](LICENSE).
