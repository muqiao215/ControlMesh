# ControlMesh Enhanced Terminal

`controlmesh` now opens the enhanced terminal when stdin/stdout are interactive.

```bash
controlmesh
```

The default prompt is:

```text
cm>
```

Normal input runs through the existing ControlMesh orchestrator, so `/status`,
`/model`, `/memory`, `/tasks`, `/cron`, route selection, session history, and
provider streaming remain the same control surface used by chat transports.

## Native Mode

Use `/cm` from enhanced mode to enter the configured provider CLI:

```text
cm> /cm
codex>
```

Use `/back` in native mode to terminate the line-mode native session and return
to enhanced mode:

```text
codex> /back
cm>
```

Native mode does not inject ControlMesh memory or rewrite provider slash
commands. It only intercepts the configured back command.

## Legacy Bot Runtime

The chat transport runtime is still available:

```bash
controlmesh bot
```

All existing service, cron, tasks, API, Feishu, and install subcommands keep
their previous CLI surface.
