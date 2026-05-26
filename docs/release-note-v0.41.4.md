# Release v0.41.4

- Make the default `controlmesh` interactive entry a command-first ControlMesh terminal instead of a chat-first shell.
- Add local terminal help for `help` and `/help`; unknown plain text now stays local and does not call the model.
- Require explicit model chat via `chat <message>` or `/chat <message>`, and prefer `native` / `/native` for provider-native CLI entry while keeping `/cm` as compatibility guidance.
- Reduce optional terminal background runtime startup noise so foreground terminal commands remain usable when background services cannot start.
