# ControlMesh v0.40.0

This release introduces unified supervision for provider CLI subprocesses, making Codex, Claude, and OpenCode failures visible instead of allowing empty error paths or stale-message guards to hide diagnostics.

## Highlights

- Adds provider-run diagnostics with user-visible provider, exit code, timeout state, phase, stdout tail, stderr tail, last event type, duration, and fallback message.
- Adds provider-run supervisor primitives, event models, and foreground/background liveness policies.
- Drains stderr line-by-line while provider processes run, so startup, auth, sandbox, MCP, and network failures reach the diagnostic buffer immediately.
- Keeps foreground chat protected by idle timeout while allowing background TaskHub/named-session work to use max-runtime backstops instead of being killed for normal silent polling.
- Ensures Telegram critical errors, timeout diagnostics, provider crashes, and process-exit diagnostics bypass freshness guard delivery.
- Reuses Codex execution flags on resume so sandbox, model, reasoning, instruction, image, and custom CLI parameters do not drift across resumed turns.

## Verification

- `ruff check controlmesh tests/background/test_observer.py tests/test_cli_supervisor.py tests/test_cli_error_visibility.py tests/fixtures/fake_cli tests/cli/test_executor_timeout.py tests/cli/test_claude_provider.py tests/cli/test_codex_provider.py tests/messenger/telegram/test_message_dispatch.py`
- `pytest tests`: 5376 passed, 3 skipped, 1 warning

## Upgrade Notes

- Push tag `v0.40.0` to trigger the existing GitHub Actions `Publish to PyPI` workflow.
- GitHub Release creation remains gated on successful PyPI publication and PyPI visibility.
