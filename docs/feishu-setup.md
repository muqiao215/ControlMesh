# Feishu Setup

ControlMesh currently supports an early Feishu app-bot path.

Important boundary:

- `controlmesh auth feishu login` does **not** create a Feishu bot for you.
- It only runs optional device-flow user auth **after** you already have a Feishu self-built app with `app_id` and `app_secret`.

If you have never created a Feishu bot before, do this first:

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
controlmesh auth feishu status
controlmesh auth feishu login
```

Use them like this:

- `setup`: prints the zero-app prerequisite and the next steps.
- `status`: shows whether `app_id/app_secret` are configured and whether device-flow auth is active.
- `login`: runs device-flow auth against the already-configured app. It does not replace app creation.

Official Feishu self-built app guide:

- <https://open.feishu.cn/document/home/introduction-to-custom-app-development/self-built-application-development-process>
