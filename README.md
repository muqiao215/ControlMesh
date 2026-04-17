# ControlMesh

中文 | [English](#english)

ControlMesh is a runtime-first agent harness for real work over chat.

It does not wrap one model API. It runs official coding CLIs such as `claude`,
`codex`, and `gemini`, then adds chat ingress, persistent workspace state,
background tasks, sub-agents, runtime controls, and auditable write-back.

The current spine is **ControlMesh Runtime**.

![ControlMesh runtime and Feishu native/bridge modes](docs/assets/controlmesh-feishu-runtime.svg)

## 中文

### 一句话

ControlMesh 把聊天入口变成一个可长期运行的 agent runtime。

你可以在 Telegram、Matrix、Feishu 等入口里驱动官方 CLI，让长任务、自动化、子代理和同一个工作区协同，而不是只得到一个一次性的聊天壳。

### 现在能做什么

| 能力 | 状态 |
|---|---|
| 官方 CLI 执行 | Claude、Codex、Gemini |
| 聊天入口 | Telegram、Matrix、Feishu |
| 上下文隔离 | 单聊、群 topic、room、named session |
| 长任务 | background task、cron、webhook、heartbeat |
| 多代理 | sub-agent 和 shared memory |
| 工作区 | 文件型 runtime state，默认 `~/.controlmesh/` |
| 控制面 | `signal`、`query`、`update` |
| Feishu native | 官方扫码创建机器人、CardKit 真流式卡片、权限编排原语 |
| Feishu bridge | 复用已有 `app_id/app_secret` 的轻量消息桥 |

### Feishu: native 和 bridge

ControlMesh 现在把 Feishu 拆成两条明确路径。

#### `native`

适合从 0 开始配一个能直接用的 Feishu 机器人。

这条线通过独立的 [`feishu-auth-kit`](https://github.com/muqiao215/feishu-auth-kit)
消费官方 scan-to-create 能力，拿到新 app/bot 的 credentials，并写回
ControlMesh 配置。

`native` 能力面：

- 官方扫码创建 app/bot
- 自动写回 `feishu.app_id` 和 `feishu.app_secret`
- 自动写回 `feishu.runtime_mode=native`
- 自动启用 `feishu.progress_mode=card_stream`
- probe app readiness
- 使用 Feishu CardKit 真流式卡片
- 复用 auth-kit 的权限规划、continuation 和 synthetic retry 原语
- MVP 已接上 native-only Feishu OAPI tools：
  `contact.search_user`、`contact.get_user`、`im.get_messages`、`drive.list_files`
- 缺 app scope / user token / user scope 时会抛标准
  `FeishuNativeToolAuthRequiredError`，由 runtime auth seam 路由权限卡或 device auth
- 新增 `/feishu_auth_all` 飞书内批量授权入口：优先走权限卡/设备授权，
  不再把“去开发者后台”作为唯一交互；当前只覆盖 native-only OAPI MVP
- native runtime 现在有第一版 agent-selectable Feishu tool seam：
  模型可先选 `contact` / `im` / `drive` native tools，再由 ControlMesh 执行并把结果回灌同一回答链
- `card_stream` 已升级为结构化单卡：状态、工具步骤、输出、终态写在同一张 CardKit 卡里
- Feishu inbound context v1 已补一阶语义：
  `post` 文本提取、`thread/root/parent` 元数据、reply/quote 摘要
- ControlMesh 现在开始薄接 `feishu-auth-kit` native runtime contract：
  入站 context 先走 `agent parse-inbound`，授权卡点击后的 retry 走
  `agent bind-continuation` / `agent action-to-retry`，`card_stream` 兼容
  `AgentEvent` / `SingleCardRun` 负载
- 当前 smoke 入口是 `/feishu-native ...`，只在 `runtime_mode=native` 可用

```bash
controlmesh auth feishu register-begin
controlmesh auth feishu register-poll --device-code "<device_code>" --interval 5 --expires-in 600
controlmesh auth feishu probe
```

#### `bridge`

适合你已经有一个 Feishu app，只想把 Feishu 当消息入口。

这条线复用手工配置的 `app_id/app_secret`，保持更小的运行时假设。

`bridge` 能力面：

- 使用已有 app credentials
- 普通文本回复
- 单卡 preview 模式
- 可做基础 auth/status/doctor
- 不承诺完整 Feishu SDK 能力面
- 不启用 CardKit 真流式

示例：

```json
{
  "transport": "feishu",
  "feishu": {
    "mode": "bot_only",
    "runtime_mode": "bridge",
    "progress_mode": "card_preview",
    "brand": "feishu",
    "app_id": "cli_xxx",
    "app_secret": "xxx"
  }
}
```

配置校验会拒绝 `runtime_mode=bridge` 和 `progress_mode=card_stream` 的混用。

### 快速开始

```bash
pipx install controlmesh
controlmesh
```

首次启动会引导你完成：

- 官方 CLI 检查
- Telegram 或 Matrix 配置
- 时区设置
- 可选 Docker
- 可选 systemd 服务安装

Matrix 额外依赖：

```bash
controlmesh install matrix
```

### Feishu 从 0 到可用

如果你没有现成 app，走 native：

```bash
controlmesh auth feishu setup
controlmesh auth feishu register-begin
controlmesh auth feishu register-poll --device-code "<device_code>" --interval 5 --expires-in 600
controlmesh auth feishu doctor
controlmesh auth feishu probe
```

如果你已经有 app，走 bridge：

```bash
controlmesh auth feishu status
controlmesh auth feishu doctor
controlmesh auth feishu login
```

`login` 是复用已有 app 做用户 OAuth，不负责创建机器人。

更完整说明见 [`docs/feishu-setup.md`](docs/feishu-setup.md)。

### 核心交互模型

ControlMesh 当前支持五层使用方式：

1. 单聊主代理
2. 群 topic 或多 room 隔离上下文
3. named session
4. background task
5. sub-agent

它们共享同一个工作区，但不共享同一个对话上下文：

```text
~/.controlmesh/
```

### Runtime 控制面

ControlMesh Runtime 已经形成一条可验证的运行时链路：

- execution evidence
- task summary / line summary
- controller-approved promotion
- controlled canonical write-back

控制面入口：

```bash
controlmesh status
controlmesh restart
controlmesh service install
controlmesh agents add NAME
controlmesh api enable
```

### 当前不是什么

- 不是大而全的云编排平台
- 不是多 worker 集群调度系统
- 不是数据库优先的重基础设施框架
- 不是 UI-first 产品
- 不是绕过 Feishu/Lark 官方平台规则的工具

当前方向是先把 runtime 语义、控制边界、可审计写回和真实聊天入口做硬，再继续扩展执行面。

### 文档入口

- 安装说明：[`docs/installation.md`](docs/installation.md)
- 文档总览：[`docs/README.md`](docs/README.md)
- Feishu 设置：[`docs/feishu-setup.md`](docs/feishu-setup.md)
- Harness / Runtime 设计：[`docs/modules/harness.md`](docs/modules/harness.md)
- 计划与控制面文件：[`plans/README.md`](plans/README.md)

### 许可证

MIT License. See [`LICENSE`](LICENSE).

---

## English

ControlMesh is a runtime-first agent harness.

It runs official coding CLIs as execution units, then layers chat ingress,
background tasks, shared workspaces, runtime controls, and auditable write-back
on top.

### What It Does

| Area | Status |
|---|---|
| CLI providers | Claude, Codex, Gemini |
| Chat transports | Telegram, Matrix, Feishu |
| Context isolation | Direct chat, group topics, rooms, named sessions |
| Long-running work | Background tasks, cron, webhooks, heartbeat |
| Multi-agent | Sub-agents and shared memory |
| Runtime state | File-backed workspace under `~/.controlmesh/` |
| Control plane | `signal`, `query`, `update` |
| Feishu native | Scan-create bot onboarding, CardKit streaming, auth orchestration primitives |
| Feishu bridge | Reuse an existing `app_id/app_secret` as a lightweight chat bridge |

### Feishu Runtime Modes

`native` is the Feishu-first path. It consumes the standalone
[`feishu-auth-kit`](https://github.com/muqiao215/feishu-auth-kit), runs the
official scan-to-create flow, writes credentials back to ControlMesh config,
probes readiness, and enables CardKit streaming cards.

The current MVP also wires native-only read OAPI tools:
`contact.search_user`, `contact.get_user`, `im.get_messages`, and
`drive.list_files`. Missing app scope, user token, or user scope is surfaced as
`FeishuNativeToolAuthRequiredError`, so the runtime can route into permission
cards or retryable device auth. `/feishu_auth_all` is the current in-chat batch
auth entry for these native-only tools: app-scope gaps still require app
owner/admin approval, while user OAuth gaps stay inside Feishu device-auth
cards with retry. The explicit smoke entry is `/feishu-native ...`, and bridge
mode does not support either native tool execution or `/feishu_auth_all`.

ControlMesh also now has a first in-runtime agent-selectable Feishu tool seam:
the model can select one native Feishu read tool before the main answer, the
runtime executes it, and the tool result is fed back into the final response
prompt. `card_stream` now renders a structured single card with status, tool
steps, output, and terminal state. Inbound Feishu parsing also carries a first
semantic layer for `post`, reply/quote summary, and thread/root/parent IDs.
ControlMesh now consumes `feishu-auth-kit` native runtime contracts on three
seams: `agent parse-inbound` for base message context, `agent action-to-retry`
for permission-card continuation clicks, and `AgentEvent`/`SingleCardRun`
compatible card rendering in `card_stream`.

```bash
controlmesh auth feishu register-begin
controlmesh auth feishu register-poll --device-code "<device_code>" --interval 5 --expires-in 600
controlmesh auth feishu probe
```

`bridge` is the compatibility path. It reuses a manually managed
`app_id/app_secret` and treats Feishu mainly as the message bridge. It supports
ordinary text and single-card preview mode, but it does not claim the full
native Feishu SDK surface.

```json
{
  "transport": "feishu",
  "feishu": {
    "mode": "bot_only",
    "runtime_mode": "bridge",
    "progress_mode": "card_preview",
    "brand": "feishu",
    "app_id": "cli_xxx",
    "app_secret": "xxx"
  }
}
```

`progress_mode=card_stream` requires `runtime_mode=native`.

### Feishu Status Today

The Feishu path is now **usable**, but it is not feature-complete yet.

What is already landed:

- scan-to-create onboarding through `feishu-auth-kit`
- config write-back, probe, readiness checks
- native vs bridge runtime split
- CardKit streaming in native mode
- native auth seam for app scope, user OAuth, and synthetic retry
- native-only read tools: `contact.search_user`, `contact.get_user`, `im.get_messages`
- in-chat batch auth entry: `/feishu_auth_all`
- media ingress/egress for text, images, files, audio, and video

What is still incomplete:

- native tools are still exposed through explicit smoke commands instead of the
  general agent tool registry
- CardKit streaming is still a text-first stream, not yet a fully structured
  task card with tool steps, confirmations, and rich status blocks
- Feishu deep message semantics are still partial: `post`, quote/reply context,
  merge-forward, interactive payloads, and richer thread semantics need more work
- the native OAPI surface is still MVP-level, not yet comparable to a full
  Feishu workspace agent

Practical summary: ControlMesh Feishu native is past the “can it work at all”
stage and now in the “make the native agent experience complete” stage.

### Live Deployment Checklist

When deploying a Feishu native release to a live host, do not treat the git
checkout alone as sufficient. The release also needs the runtime dependencies
that the native auth flow expects.

Minimum checks:

- the running service must point to the intended release path and venv
- `feishu-auth-kit` must be resolvable by ControlMesh
- if `feishu-auth-kit` is not in `PATH`, set
  `CONTROLMESH_FEISHU_AUTH_KIT_BIN=/abs/path/to/feishu-auth-kit`
- if using a sibling checkout instead of an installed binary, make sure the
  sibling repo and its `uv`-managed environment are present on the live host
- after cutover, verify that `/feishu-native ...` is handled by the native tool
  path rather than falling through to the normal model turn

The most common live-host failure mode is not Feishu API breakage, but missing
runtime wiring after cutover: wrong release path, stale editable install,
missing `feishu-auth-kit`, or a service environment that cannot resolve it.

### Quick Start

```bash
pipx install controlmesh
controlmesh
```

Requirements:

- Python 3.11+
- at least one official CLI: `claude`, `codex`, or `gemini`
- at least one transport: Telegram, Matrix, or Feishu

Install Matrix support:

```bash
controlmesh install matrix
```

### Common Commands

```bash
controlmesh
controlmesh status
controlmesh restart
controlmesh service install
controlmesh agents add NAME
controlmesh api enable
controlmesh auth feishu setup
```

### Docs

- Installation: [`docs/installation.md`](docs/installation.md)
- Docs index: [`docs/README.md`](docs/README.md)
- Feishu setup: [`docs/feishu-setup.md`](docs/feishu-setup.md)
- Harness / Runtime design: [`docs/modules/harness.md`](docs/modules/harness.md)
- Plan and control-plane files: [`plans/README.md`](plans/README.md)

### License

MIT License. See [`LICENSE`](LICENSE).
