# ControlMesh v0.23.3

This hotfix release follows v0.23.2 and keeps the same user-facing features:
Claude native command switching, `/back`, and capability-routed WorkUnits.

## Fixes

- Fixed ruff failures in the new routing modules.
- Added routing test package metadata.
- Reset i18n language state around tests so language-switch tests do not leak
  into unrelated English assertions.
- Updated the OpenAI Agents provider test expectation for the full registered
  runtime tool set.

## Verification

- `uv run --extra lint ruff check .`
- Focused regression suite: 44 passed
- `python -m compileall controlmesh tests`
