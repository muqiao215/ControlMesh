# Feishu Setup

ControlMesh currently supports an early Feishu app-bot path.

Important boundary:

- `controlmesh auth feishu register-begin` / `register-poll` delegate the
  official Feishu/Lark scan-to-create app registration flow to the standalone
  `feishu-auth-kit`.
- This is an official `accounts` registration flow. It does not bypass tenant
  approval, publishing, or Feishu/Lark platform policy.
- `controlmesh auth feishu login` still only runs optional device-flow user auth
  **after** you already have a Feishu app with `app_id` and `app_secret`.

If you have never created a Feishu bot before, try the scan-to-create path first:

```bash
controlmesh auth feishu register-begin
controlmesh auth feishu register-poll --device-code "<device_code>" --interval 5 --expires-in 600
```

`register-begin` prints JSON from `feishu-auth-kit register scan-create --no-poll --json`,
including `qr_url`, `device_code`, `user_code`, `interval`, and `expires_in`.
Render or open the QR URL for the user to scan with Feishu/Lark, then call
`register-poll` until it returns `status=success` with `app_id`, `app_secret`,
`domain`, and optionally `open_id`.

Manual fallback remains available if scan-to-create is unavailable in your
tenant/environment:

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

- `setup`: prints the zero-app prerequisite and the next steps. When the standalone
  `feishu-auth-kit` CLI is available, ControlMesh reuses its setup guidance
  instead of maintaining a separate copy only.
- `register-begin`: delegates to `feishu-auth-kit register scan-create --no-poll --json`
  and exposes the official from-zero QR/link onboarding payload.
- `register-poll`: delegates to `feishu-auth-kit register poll --json` and returns
  the registered app credentials once the user finishes the QR flow.
- `doctor`: delegates app credential and scope diagnostics to the standalone
  `feishu-auth-kit` repo/CLI while keeping ControlMesh itself independent from
  Feishu onboarding internals.
- `probe`: delegates to `feishu-auth-kit register probe --json`, validating
  configured credentials and registering/checking the app as an AI agent through
  the official OpenClaw bot ping endpoint.
- `plan`: delegates to `feishu-auth-kit orchestration plan` and produces an
  OpenClaw-style missing-scope/batch authorization plan from explicit scope
  inputs.
- `route`: delegates to `feishu-auth-kit orchestration route` and stores generic
  continuation state under `feishu_store/auth/` for permission-missing or
  user-auth-required flows. ControlMesh still owns the actual Feishu card send
  and callback ingress.
- `retry`: delegates to `feishu-auth-kit orchestration retry` and turns a saved
  continuation into a messenger-agnostic synthetic retry artifact.
- `status`: shows whether `app_id/app_secret` are configured and whether device-flow auth is active.
- `login`: runs device-flow auth against the already-configured app. It does not replace app creation.

This is the ControlMesh side of the OpenClaw-style auth split:

- `feishu-auth-kit` owns app/scope inspection, permission URL/card payloads,
  continuation schemas, batching, and synthetic retry artifacts.
- ControlMesh owns Feishu transport delivery, card action callbacks, session
  binding, and reinjecting a synthetic retry into the ControlMesh runtime.

The current integration is intentionally narrow: it consumes the standalone kit
through its CLI and does not copy the OpenClaw implementation into ControlMesh.

Runtime bridge:

- ControlMesh now has a Feishu runtime orchestration runner that can send an
  auth-kit-derived permission card, persist continuation metadata, accept
  `card.action.trigger` callbacks, and inject a synthetic retry back into the
  same Feishu chat/session after the user clicks "I have granted permissions".
- For development and live smoke tests, the runner accepts:

```bash
/feishu_permission --scope im:message --url "https://open.feishu.cn/..." --text "continue original task"
```

- The command is a bridge hook, not the final product UX. The final automatic
  path should call the same runner from Feishu API/tool error handling when an
  app-scope-missing error is detected.

Official Feishu self-built app guide:

- <https://open.feishu.cn/document/home/introduction-to-custom-app-development/self-built-application-development-process>
