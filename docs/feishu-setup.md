# Feishu Setup

ControlMesh currently supports two distinct Feishu runtime tracks:

- `native`: the Feishu-first path. Use the official scan-to-create flow, keep
  SDK/CardKit capabilities available, and prefer true streaming cards.
- `bridge`: the compatibility path. Reuse an existing `app_id/app_secret` and
  treat Feishu mainly as the chat interface.

Product-friendly bootstrap alias:

```bash
controlmesh feishu native bootstrap
```

This is a real runnable alias for `controlmesh auth feishu setup`. Start here
if you want the Feishu-native product path first and the lower-level auth
commands second.

Important boundary:

- ControlMesh includes `feishu-auth-kit` as its bundled Feishu native plugin.
  The standalone repository remains the upstream source of this reusable
  capability, but a ControlMesh release must contain the plugin.
- `controlmesh auth feishu register-begin` / `register-poll` run the official
  Feishu/Lark scan-to-create app registration flow through that plugin.
- This is an official `accounts` registration flow. It does not bypass tenant
  approval, publishing, or Feishu/Lark platform policy.
- `controlmesh auth feishu login` still only runs optional device-flow user auth
  **after** you already have a Feishu app with `app_id` and `app_secret`.

If you have never created a Feishu bot before, try the scan-to-create path first:

```bash
controlmesh feishu native bootstrap
controlmesh auth feishu register-begin
controlmesh auth feishu register-poll --device-code "<device_code>" --interval 5 --expires-in 600
```

`register-begin` prints JSON equivalent to
`feishu-auth-kit register scan-create --no-poll --json`, including `qr_url`,
`device_code`, `user_code`, `interval`, and `expires_in`.
Render or open the QR URL for the user to scan with Feishu/Lark, then call
`register-poll` until it returns `status=success` with `app_id`, `app_secret`,
`domain`, and optionally `open_id`.

ControlMesh now closes the CLI loop on `register-poll`:

- writes `feishu.app_id` and `feishu.app_secret` back into the ControlMesh config
  using atomic JSON save
- writes `feishu.runtime_mode=native`
- writes `feishu.progress_mode=card_stream`
- writes the resolved Open Platform base URL into `feishu.domain`
- preserves unrelated config fields and existing Feishu settings
- initializes `feishu.allow_from` from the returned owner `open_id` only when
  no allowlist already exists
- automatically calls `controlmesh auth feishu probe` logic with the new
  credentials and reports transport readiness

Manual fallback remains available if scan-to-create is unavailable in your
tenant/environment. That path is the `bridge` runtime:

1. Open the Feishu Open Platform app console: <https://open.feishu.cn/app>
2. Create a self-built app for your tenant.
3. Enable the Bot capability for that app.
4. Install or publish the app to the tenant that should receive messages.
5. Enable Feishu message events for the app. ControlMesh currently expects the app-bot style flow; long connection is the preferred delivery mode.
6. Subscribe to at least the message receive event needed for chat ingress, such as `im.message.receive_v1`.
7. Copy the app's `app_id` and `app_secret` into your `config.json` under the `feishu` section.
8. Add the bot into a chat and send a first message to verify inbound and reply behavior.

Example config shape:

```json
{
  "transport": "feishu",
  "feishu": {
    "mode": "bot_only",
    "runtime_mode": "bridge",
    "brand": "feishu",
    "app_id": "cli_xxx",
    "app_secret": "xxx"
  }
}
```

After the app exists, these commands help:

```bash
controlmesh auth feishu setup
controlmesh auth feishu register-begin
controlmesh auth feishu register-poll --device-code "<device_code>" --interval 5 --expires-in 600
controlmesh auth feishu doctor
controlmesh auth feishu probe
controlmesh auth feishu plan --requested-scope im:message --app-scope im:message
controlmesh auth feishu route --error-kind app_scope_missing --required-scope im:message --permission-url "<url>"
controlmesh auth feishu retry --operation-id "<op>" --text "retry original request"
controlmesh auth feishu status
controlmesh auth feishu login
```

Use them like this:

Plugin resolution order:

1. `CONTROLMESH_FEISHU_AUTH_KIT_BIN` for explicit local override.
2. ControlMesh bundled plugin:
   `python -m controlmesh._plugins.feishu_auth_kit.runner`.
3. `feishu-auth-kit` from `PATH`.
4. Sibling development repo `.venv/bin/feishu-auth-kit`.
5. Sibling development repo through `uv run feishu-auth-kit`.

This makes Feishu native auth/runtime a contained ControlMesh capability while
still allowing upstream `feishu-auth-kit` development to override the bundled
snapshot deliberately.

- `setup`: prints the zero-app prerequisite and the next steps through the
  bundled plugin guidance.
- `register-begin`: runs `feishu-auth-kit register scan-create --no-poll --json`
  and exposes the official from-zero QR/link onboarding payload.
- `register-poll`: runs `feishu-auth-kit register poll --json`, writes
  the successful credentials back into ControlMesh config as the `native`
  runtime path, auto-runs probe, and tells you whether Feishu transport is
  ready to start.
- `doctor`: delegates app credential and scope diagnostics to the bundled
  plugin contract while preserving the upstream kit as the reusable source.
- `probe`: runs `feishu-auth-kit register probe --json`, validating
  configured credentials and registering/checking the app as an AI agent through
  the official OpenClaw bot ping endpoint.
- `plan`: runs `feishu-auth-kit orchestration plan` and produces an
  OpenClaw-style missing-scope/batch authorization plan from explicit scope
  inputs.
- `route`: runs `feishu-auth-kit orchestration route` and stores generic
  continuation state under `feishu_store/auth/` for permission-missing or
  user-auth-required flows. ControlMesh still owns the actual Feishu card send
  and callback ingress.
- `retry`: runs `feishu-auth-kit orchestration retry` and turns a saved
  continuation into a messenger-agnostic synthetic retry artifact.
- `status`: shows whether `app_id/app_secret` are configured and whether device-flow auth is active.
- `login`: runs device-flow auth against the already-configured app. It does not replace app creation; this is primarily the `bridge` companion path when you already manage the app manually.

This is the ControlMesh side of the OpenClaw-style auth split:

- `feishu-auth-kit` owns app/scope inspection, permission URL/card payloads,
  continuation schemas, batching, and synthetic retry artifacts.
- ControlMesh owns Feishu transport delivery, card action callbacks, session
  binding, and reinjecting a synthetic retry into the ControlMesh runtime.

The current integration is intentionally narrow: ControlMesh contains the
`feishu-auth-kit` plugin snapshot and talks to it through the same CLI contract
used by the standalone upstream repo. It still does not copy the OpenClaw
implementation wholesale into ControlMesh.

Runtime bridge:

- ControlMesh now has a Feishu runtime orchestration runner that can send an
  auth-kit-derived permission card, persist continuation metadata, accept
  `card.action.trigger` callbacks, and inject a synthetic retry back into the
  same Feishu chat/session after the user clicks "I have granted permissions".
- ControlMesh now consumes `feishu-auth-kit` native runtime contracts instead
  of extending a separate Feishu core:
  - inbound message normalization first calls `feishu-auth-kit agent parse-inbound`
  - permission-card continuation now binds a native continuation and resolves
    card clicks through `feishu-auth-kit agent action-to-retry`
  - `card_stream` can consume `feishu-auth-kit` `AgentEvent` and
    `SingleCardRun` payloads
- For development and live smoke tests, the runner accepts:

```bash
/feishu_permission --scope im:message --url "https://open.feishu.cn/..." --text "continue original task"
```

- The command is a bridge hook, not the final product UX. The final automatic
  path should call the same runner from Feishu API/tool error handling when an
  app-scope-missing error is detected.

Native-only OAPI MVP:

- ControlMesh now ships a narrow native-only executor for read tools:
  `contact.search_user`, `contact.get_user`, `im.get_messages`, and
  `drive.list_files`.
- These tools are intentionally scoped to `feishu.runtime_mode=native`.
  `bridge` does not expose them.
- Missing app scope, missing user token, and missing user scope are normalized
  into `FeishuNativeToolAuthRequiredError`, which is already handled by the
  Feishu bot runtime and routed to permission-card or retryable device-auth
  flows.
- Native runtime now has a first agent-selectable seam for these tools:
  ControlMesh asks the model to select at most one Feishu native tool for the
  current message, executes it inside the Feishu runtime, and feeds the result
  into the final answer prompt. This is a ControlMesh runtime seam, not full
  provider-native MCP registration yet.
- `card_stream` now renders a structured single CardKit card with:
  - overall status
  - tool step list (`running` / `success` / `error`)
  - output body
  - terminal state
- Feishu inbound context v1 now adds:
  - `post` rich-text extraction
  - `thread_id` / `root_id` / `parent_id`
  - reply / quote summary when present in inbound content
  - minimal `interactive` / `merge_forward` text extraction fallback for agent context
- There is now an explicit native-only auth UX entry for this MVP:

```bash
/feishu_auth_all
```

- `/feishu_auth_all` calls `feishu-auth-kit orchestration plan` over the
  existing subprocess JSON seam, then:
  - if app scopes are still unavailable, sends a Feishu permission card with
    continue/retry actions and explicit app-owner/admin wording;
  - if app scopes are ready but user OAuth scopes are missing, starts the first
    retryable device-auth batch in-chat;
  - if current native MVP scopes are already granted, replies that native OAPI
    permissions are ready.
- Boundary split:
  - app scope = app/platform boundary; user cannot self-grant it, so the card
    explains that admin/app-owner action is still required;
  - user OAuth = per-user boundary; ControlMesh keeps this inside Feishu via
    the existing card/device-auth flow.
- This wrapper currently targets the native-only MVP scopes behind
  `contact.search_user`, `contact.get_user`, and `im.get_messages`. `bridge`
  does not support it.
- Current manual smoke entry:

```bash
/feishu-native contact.search_user Alice
/feishu-native contact.get_user ou_xxx
/feishu-native im.get_messages oc_xxx 20
/feishu-native drive.list_files fld_root 20
```

Official Feishu self-built app guide:

- <https://open.feishu.cn/document/home/introduction-to-custom-app-development/self-built-application-development-process>
