# ControlMesh v0.41.9

Compared to **v0.41.8**, this patch release streamlines the enhanced
terminal entry experience and adds in-terminal model switching.

## Highlights

- Added `/model` commands to the terminal command router: `model` shows the
  current model and available switch commands, `model <provider>` switches to
  a provider default, and `model <provider> <model>` selects a specific model.
- The enhanced shell banner now shows the active provider/model label on
  startup and a concise one-line hint of available commands.
- Reworked the terminal help text to lead with chat and model commands and to
  group legacy `/`-prefixed forms under a Compatibility section.

## Upgrade Notes

- No configuration changes are required.
- Existing terminal workflows keep working; `chat`, `/chat`, `/native`, and
  `/help` remain available as compatibility aliases.

## Validation

- `uv run pytest tests/terminal/ -q`
