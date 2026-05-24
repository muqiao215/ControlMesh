# ControlMesh v0.41.1

Compared to **v0.41.0**, this patch release stabilizes the Feishu-native setup
and authorization path after real scan-create registration testing.

## Highlights

- Added `controlmesh feishu native setup` as the stable post-install Feishu
  scan-create entrypoint. It prints the official QR/link, stores pending
  registration state, and lets the existing auto-complete helper write config
  after approval.
- Added Feishu-native guidance to `controlmesh install`, first-run onboarding,
  incomplete Feishu config validation, and setup docs so new installs no longer
  need to discover low-level `auth feishu` commands first.
- Fixed `/feishu_auth_useful` so it targets useful native scopes first, sends
  an app-permission card when app scopes are missing, and no longer treats
  `offline_access` alone as a successful useful authorization.

## Upgrade Notes

- Existing Feishu-native installs do not need config changes.
- Operators who want Feishu as the primary chat surface can now run
  `controlmesh feishu native setup` directly after installing ControlMesh and
  authenticating at least one provider CLI.

## Validation

- `uv run --python 3.12 python -m pytest tests/cli/test_feishu_native_cli.py tests/cli/test_feishu_auth_cli.py tests/cli/test_install.py tests/cli/test_init_wizard.py tests/messenger/feishu/test_native_auth_useful_runner.py tests/messenger/feishu/test_native_auth_all_runner.py tests/messenger/feishu/test_auth_orchestration_runner.py tests/messenger/feishu/test_card_auth_runner.py tests/messenger/feishu/test_bot_native_tools.py tests/messenger/feishu/test_bot.py tests/messenger/feishu/test_settings_card.py -q`
- `uv run --python 3.12 ruff check controlmesh/__main__.py controlmesh/cli/init_wizard.py controlmesh/cli_commands/auth.py controlmesh/cli_commands/feishu.py controlmesh/cli_commands/install.py controlmesh/messenger/feishu/auth/native_auth_useful_runner.py controlmesh/messenger/feishu/bot.py controlmesh/messenger/feishu/command_center_card.py tests/cli/test_feishu_native_cli.py tests/cli/test_init_wizard.py tests/cli/test_install.py tests/messenger/feishu/test_native_auth_useful_runner.py`
