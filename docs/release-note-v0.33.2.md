# ControlMesh v0.33.2

This patch release removes an operator-hostile OpenCode preflight failure mode and keeps the Telegram/Feishu runtime usable when an OpenCode model probe is slow or temporarily unrunnable.

## Included fixes

- OpenCode explicit model preflight no longer aborts the whole turn when `opencode run` probe times out or fails.
- ControlMesh now keeps the configured OpenCode model and lets the real runtime execution decide the outcome, instead of surfacing a generic internal error before the turn starts.

## Operational impact

- Switching `/model` to `opencode` models such as `zhipuai/glm-5.1` no longer turns the next user message into `An internal error occurred` just because the 15-second preflight probe was too strict.
- Provider/model state remains debuggable without forcing operators to roll back from the selected model immediately.

## Release notes

- This patch is intended to follow `v0.33.1`.
- Release this version with tag `v0.33.2`.
