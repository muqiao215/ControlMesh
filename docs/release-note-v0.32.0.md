# ControlMesh v0.32.0

This release closes a cluster of runtime-boundary bugs that were still leaking through after `v0.31.3`: TaskHub now preserves explicit OpenCode task models, Claude background workers receive the tool allowlist they actually need, release phase bootstrap carries the real repo root into phase 1, and Codex/Telegram no longer spray raw event-stream JSON back into the foreground without better diagnostics.

## Highlights

- Fixed TaskHub OpenCode explicit-model routing.
  - Background tasks that explicitly target OpenCode models such as `zhipuai/glm-5.1` now preserve that model through runtime target resolution instead of falling back into empty default-model discovery.
  - This closes the real `opencode_default_model_unresolved` failure mode seen on production hosts where the foreground default provider was not OpenCode.
- Fixed Claude background-task tool permissions.
  - TaskHub now passes per-task tool allowlists into Claude task execution so background repo-audit and similar tasks can actually read files and run shell commands.
  - Write-capable Claude background tasks also receive edit/write tools only when the task binding or business permissions require them.
- Changed Claude root defaults to highest-permission execution.
  - When ControlMesh runs as root with `permission_mode=bypassPermissions`, the default Claude root behavior now stays on `bypassPermissions` and enables the `IS_SANDBOX=1` escape hatch by default.
  - Operators no longer need to remember extra `claude_root_*` overrides just to stop root-hosted Claude cron/task paths from silently degrading into `dontAsk`.
- Fixed release phase bootstrapping context.
  - The release task entrypoint now resolves and forwards the local repo root into the first release phase when a checkout exists.
  - Phase-1 release work no longer silently defaults to the workspace root when the real repository is under `/root/.controlmesh/dev/<repo>`.
- Hardened Codex and Telegram event-stream handling.
  - Codex structured event-only output without a final assistant message is now converted into a bounded error instead of leaking raw JSONL into the chat.
  - Telegram ingress now detects raw agent event-stream payloads and logs source metadata (`via_bot`, `sender_chat`, `forward_origin`, `reply_to`) for real-world reinjection triage.

## Why v0.32.0 exists

These changes are all about runtime boundaries rather than surface polish:

1. task routing had a real provider/model override loss for OpenCode background execution
2. Claude background workers could be created in a "talk-only" mode without the file/shell tools they needed
3. root-hosted Claude execution still silently degraded into `dontAsk` unless operators knew to set two extra escape-hatch flags
4. phased release execution could start phase 1 without the correct repository root
5. raw structured event payloads could still cross the runtime boundary and show up in chat without enough evidence to identify the upstream source

Taken together, this is a stability line, not a tiny patch. That is why it ships as `v0.32.0`.

## Impact

- OpenCode background tasks are now stable when the task explicitly names a runtime model.
- Claude TaskHub workers are materially more reliable for repo-audit and similar file/shell-backed tasks.
- Root-hosted Claude cron/task paths now default to full-permission execution instead of silent downgrade.
- Release phase 1 runs now start with the right repo context when the checkout exists locally.
- Codex event-only failures stop polluting foreground chat, and Telegram ingress now leaves enough evidence to trace real raw-event reinjection sources.

## Verification

- `uv run pytest tests/cli/test_codex_provider.py tests/cli/test_service_extended.py tests/messenger/telegram/test_app.py tests/security/test_content.py tests/tasks/test_hub.py tests/workspace/test_task_tools.py -q`

## Upgrade Notes

- `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.32.0`.
- Push tag `v0.32.0` to trigger the existing GitHub Actions `Publish to PyPI` workflow.
- Create or update the GitHub Release only after the publish workflow succeeds and PyPI visibility is confirmed.
