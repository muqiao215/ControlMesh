# ControlMesh v0.30.0

This release moves TaskHub background execution off raw `provider/model` authority and onto explicit assistant-slot binding.

## Highlights

- TaskHub background tasks now resolve through assistant slots.
  - Canonical binding is now `slot -> assistant command -> native assistant config`.
  - Built-in background slots include `codex_default`, `opencode_default`, `claude_default`, and `gemini_default`.
- Raw provider tokens are no longer treated as executable background runners.
  - `openai`, `anthropic`, `zhipuai`, `openrouter`, `litellm`, `ollama`, `openai_agents`, `claw`, and `claw-code` are rejected before task creation.
  - These names may still exist inside a real assistant's native config, but they are no longer ControlMesh TaskHub execution authority.
- Legacy provider hints remain compatibility input only.
  - `provider=codex`, `provider=opencode`, `provider=claude`, and `provider=gemini` now map to assistant slots as legacy hints.
  - Model text such as `gpt-5.5 review` remains only a hint and does not get reinterpreted as `provider=openai`.
- Task records now persist an execution binding snapshot.
  - Task registry artifacts now store `slot`, `assistant`, `command`, `config_authority`, `config_paths`, `config_digests`, `workunit`, `mode`, and `background`.
  - Legacy `provider/model` fields may still exist as observed metadata or hints, but execution no longer starts from them.
- All background creation entrypoints now fail early on invalid binding input.
  - Task tools, internal API, `/tasks new`, auto-routing, webhook observers, and TaskHub core all go through the same slot resolver.
  - Invalid input now fails before any CLI runner starts, instead of surfacing later as a generic runtime error.

## Why v0.30.0 exists

Earlier TaskHub behavior still framed background execution too much like a provider registry:

1. a task could be expressed as raw `provider/model`
2. ControlMesh would try to infer a CLI runner from that pair
3. invalid or ambiguous tokens would fail late and blur the scheduler/runtime boundary

`v0.30.0` fixes that boundary.

ControlMesh is not the authority for model routing, gateway choice, provider compatibility, auth, or endpoint ownership. Those belong to the assistant CLI being launched. ControlMesh is responsible for task lifecycle, risk gates, process isolation, routing, evidence, and result handoff.

## Impact

- Background execution authority is now assistant-slot based instead of provider/model based.
- `openai`-like tokens are treated as native-config provider words, not TaskHub executable slots.
- Foreground runtime state no longer leaks into background execution as an implicit raw provider binding.
- Errors are clearer and earlier:
  - `"<token>" is not an assistant slot`
  - `Model/provider settings are owned by each assistant's native config`
  - `Available slots: ...`

## Verification

- `uv run pytest tests/tasks/test_hub.py -q`
- `uv run pytest tests/workspace/test_task_tools.py -q`
- `uv run pytest tests/orchestrator/test_commands.py tests/orchestrator/test_task_selector.py tests/multiagent/test_commands.py -q -k 'tasks_new or session_prompt_runs_foreground_without_taskhub or status_default_hides_claw_provider or status_all_providers_shows_legacy_claw or phase or taskhub'`
- `uv run pytest tests/test_packaging.py -q`

## Upgrade Notes

- Release this version with tag `v0.30.0`; `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.30.0`.
- Public publishing should continue through the existing GitHub Actions `Publish to PyPI` workflow triggered by pushing `v0.30.0`.

## Release Audit

- `v0.30.0` was initially tagged at `8af08c4`, where the tag-side PyPI publish gate failed before any PyPI artifacts were uploaded.
- The release tag was later corrected to `34d38a9` in the same release window after the CI repair landed on `main`.
- PyPI `0.30.0` is expected to publish from the repaired tag, so GitHub Release `v0.30.0` and PyPI `0.30.0` stay aligned to the same fixed source commit.

## Release Audit Note

- `v0.30.0` was initially tagged on commit `8af08c4`, where the pre-publish main CI gate later failed before any PyPI artifacts were uploaded.
- The tag was then corrected to commit `34d38a9` in the same release window after the CI repair landed on `main`.
- GitHub Release and PyPI publication for `0.30.0` are intended to reflect the repaired tag, not the initial failed pre-publish commit.
