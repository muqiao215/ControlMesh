# ControlMesh v0.29.2

This release tightens the TaskHub execution boundary so background work no longer accepts unsupported provider surfaces or inherits ambiguous foreground runtimes.

## Fixes

- Restricted TaskHub background execution to explicit supported providers only.
  - Supported background providers are now `claude`, `codex`, `gemini`, and `opencode`.
  - `openai`, `openai_agents`, `claw`, and `claw-code` are rejected before task creation instead of failing later as runtime CLI errors.
- Removed legacy provider alias behavior from TaskHub tool entrypoints.
  - Background task tools no longer normalize `openai -> codex`.
  - Background task tools no longer accept `claw-code` as a compatibility path.
- Hardened TaskHub default-provider resolution.
  - If the foreground runtime is currently on an unsupported background provider, TaskHub no longer inherits it implicitly.
  - Background execution now falls back onto a supported TaskHub provider path instead of leaking unsupported foreground bindings into task execution.
- Added regression coverage for the new boundary.
  - TaskHub now has tests for rejecting unsupported explicit providers.
  - Workspace task tools now have tests for failing early on unsupported provider tokens.

## Why v0.29.2 exists

The `/session` / `/tasks` / `/agents` / `/status` boundary work clarified which surface owns foreground context, background execution, executor policy, and runtime facts.

One hole remained in that split:

1. a background task could still be launched with an ambiguous or unsupported provider token
2. the task would be created successfully
3. execution would fail later as a generic CLI/runtime error

`v0.29.2` closes that hole at the TaskHub boundary itself.

## Impact

- Background task creation fails fast with clear provider errors.
- Unsupported SDK-only or legacy runtime names no longer leak into TaskHub workunits.
- Foreground provider state and background execution policy are now more cleanly separated.
