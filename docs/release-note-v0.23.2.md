# ControlMesh v0.23.2

This release turns `/cm` into a clean namespace switcher and adds the first
capability-based routing plane for background work.

## Highlights

- `/cm` now opens the Claude native command registry in Telegram and Feishu
  instead of showing ControlMesh-only commands.
- `/back` returns from the Claude native registry to the ControlMesh command
  center.
- Background tasks can now opt into `route=auto`, so ControlMesh classifies
  work as `test_execution`, `code_review`, or `patch_candidate` and selects a
  provider/model/topology from capability metadata.
- New `route_task.py` helper creates capability-routed tasks without forcing
  the foreground controller to choose a specific worker manually.
- Default capability registry seeds foreground/background, Codex CLI, Claude
  Code Codex plugin, and OpenCode-style slots.

## For Operators

- New config block: `agent_routing`.
- New seeded workspace file: `routing/capabilities.yaml`.
- New module docs:
  - `docs/modules/agent_routing.md`
  - `docs/modules/pwf_wave.md`

## Verification

- `python -m compileall controlmesh tests`
- Focused regression suite: 222 passed
- Full local pytest was intentionally skipped because the local machine was
  overloaded; GitHub Actions remains the release gate.
