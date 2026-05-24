# ControlMesh v0.41.2

Compared to **v0.41.1**, this patch release fixes the Feishu native
app-permission handoff copy and card affordances for the useful/all auth flows.

## Highlights

- Updated `/feishu_auth_useful` and `/feishu_auth_all` app-permission prompts
  so the in-chat card is the primary action surface. The fallback raw URL is
  still shown only for cases where the card button cannot be opened.
- Renamed the Feishu permission-card buttons to `去申请权限` and `已完成，继续`,
  matching the intended one-click permission completion flow.
- Clarified that app-permission completion is not user OAuth. After the app
  permissions are applied and approved, users return to the same card/session
  to continue into the user authorization step.

## Upgrade Notes

- Existing Feishu-native installs do not need config changes.
- Operators who saw `/feishu_auth_useful` point them toward the wrong mental
  model can rerun the command after upgrading to get the corrected card flow.

## Validation

- `uv run --python 3.12 python -m pytest tests/messenger/feishu/test_auth_orchestration_runner.py tests/messenger/feishu/test_native_auth_useful_runner.py tests/messenger/feishu/test_native_auth_all_runner.py -q`
- `uv run --python 3.12 ruff check controlmesh/messenger/feishu/auth/orchestration_runner.py controlmesh/messenger/feishu/auth/native_auth_useful_runner.py controlmesh/messenger/feishu/auth/native_auth_all_runner.py tests/messenger/feishu/test_auth_orchestration_runner.py tests/messenger/feishu/test_native_auth_useful_runner.py tests/messenger/feishu/test_native_auth_all_runner.py`
