# ControlMesh v0.29.0

This release moves long-running execution and publish-side effects onto durable HostJob authority, so chat transports stop owning process lifetime.

## Highlights

- Added a generic HostJob substrate for durable host execution.
  - Canonical per-job authority now lives under `runtime/host-jobs-state/<job_id>/`.
  - Jobs persist `HOST_JOB.json`, `STEPS.json`, `TOOL_RESULT.json`, `events.jsonl`, and stdout/stderr artifacts.
  - Job and step terminal states are sticky and cannot be rolled back by older reconcile events.
- Established a shared host-execution dispatch boundary.
  - `test_execution`, `long_shell`, `uv_build`, `git_write`, `repo_write`, `repo_publish`, `github_release`, `publish`, and `release_publish` now route to HostJob execution instead of chat-bound CLI worker lifetime.
  - TaskHub remains responsible for metadata, delivery, and reconcile; HostJobRunner owns the real process, exit code, process group, and logs.
- Tightened release approval semantics to explicit step approval.
  - Recommended approval command is now `approve <step_id> <target>`.
  - Broad approvals such as `approve release-vX`, `approve all`, or natural-language acknowledgements no longer trigger side effects.
  - Release publish approval no longer resumes an agent session to run `git push` or `gh release`.
- Added status and log projection for HostJobs.
  - `/mesh status <target>` shows current job state, completed/running/pending steps, and the exact next approval command when applicable.
  - `/mesh tail <target> [lines]` provides bounded log tail access without streaming full stdout into chat.
- Fixed task routing and delivery regressions around provider/model binding.
  - Background tasks reject invalid `provider=codex` plus `model=zhipuai/glm-5.1` combinations early instead of failing deeper in execution.
  - Task result projection now reliably lands back in the foreground chat.
- Included the recent QQ bot task-result delivery regression fix and the Claude root/cron bypass alignment merged through PR #5.

## Release Publish Step Graph

Release publish now uses an explicit HostJob step graph:

1. `pytest_full`
2. `uv_build`
3. `verify_tag_local`
4. `push_main`
5. `push_tag`
6. `verify_remote_tag`
7. `gh_release_create`

Approval is required for:

- `push_main`
- `push_tag`
- `gh_release_create`

`gh_release_create` is executed with `--verify-tag`.

## Impact

- Telegram, Feishu, and other chat entrypoints now act as intent/approval/status projections instead of long-task PTY owners.
- HostJob authority files are the canonical result source for long-running execution and release/publish operations.
- Agent sessions stay responsible for planning, patching, and decision-making, not for durable process lifetime.
