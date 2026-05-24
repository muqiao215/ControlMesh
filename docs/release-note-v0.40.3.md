# ControlMesh v0.40.3

This release adds the first Feishu group controlled-agent handoff slice.

## Highlights

- Adds per-Feishu-group agent routing policy with `agent_roster`, `default_agent`,
  `allow_interagent_handoff`, and `max_handoff_depth`.
- Supports explicit named-agent routing from Feishu groups with syntaxes such as
  `@coder ...`, `agent:coder ...`, `agent=coder ...`, and `@agent:coder ...`.
- Routes selected group requests through the existing ControlMesh multi-agent bus
  and returns labeled results to the original Feishu group/reply target.
- Keeps v1 bounded to one controlled handoff: the Feishu entry agent consumes the
  allowed hop and sends `remaining_handoff_depth=0` to the selected agent.
- Keeps unknown or out-of-roster agent targets on the normal main-agent path.
- Stops treating Feishu `@all` as an explicit bot mention trigger.
- Documents the v1 product boundary in `docs/feishu-controlled-agent-handoff.md`.

## Verification

- `uv run --extra test python -m pytest tests/test_config.py tests/messenger/feishu/test_bot.py -q`
- `uv run --extra lint ruff check controlmesh/config.py controlmesh/messenger/feishu/bot.py tests/test_config.py tests/messenger/feishu/test_bot.py`
- `git diff --check`

## Upgrade Notes

- Push tag `v0.40.3` to trigger the existing GitHub Actions `Publish to PyPI`
  workflow.
- GitHub Release creation remains gated on successful PyPI publication and PyPI
  visibility.
