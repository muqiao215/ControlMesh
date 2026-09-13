# Reuse CM parent TaskHub for external CLI workers

Status: implemented, review-2 and review-3 repairs applied by CBC (isolated + live
evidence, awaiting primary acceptance). Review 3 added intent-integrity fail-closed
behaviour (no rebinding/adoption without a valid dispatch intent, provenance binding,
step-id validation), retained review + unknown execution quiescence for vanished
wrappers, a bounded structured `needs_review` answer (CLI exit 4) instead of an
unbounded wait, and `dispatcher_lost_before_worker_start` detection. 22 focused tests
pass. Result:
[taskhub-parent-bridge-result.md](taskhub-parent-bridge-result.md) — new
`controlmesh/runtime/host_job_bridge.py` + `controlmesh hostjob run|wait|consume|status`
CLI + additive `HostJobStore.lock` / `HostJobRunner.detach`. Review 2 added durable
single dispatch (flock + persisted dispatch intent), persisted parent/command/workspace
binding with identifier validation, atomic cross-process consume, and an explicit
`unknown`-process review outcome. 14 isolated tests pass
(log `/tmp/cm-parent-bridge-r2-tests.log`); live CLI evidence in
`/tmp/hj_live_r2_final.log` against a scratch `CONTROLMESH_HOME`. No commits/push. User confirms current Codex is the
supervising parent; do not replace CM with another task system or a periodic model-prompt
automation. Conserve Codex tokens.

CBC owns this bounded task: inspect the EXISTING parent/result chain and implement the
smallest missing non-model bridge, if required, so this external controller can supervise
CBC/AGY execution via CM records and retrieve one terminal event per attempt.

Observed anchors:
- tasks/hub.py: set_result_handler, read_agent_inbox_filtered, consume_tool_results,
  _deliver, _append_agent_inbox_result.
- multiagent/plan_review_loop.py consumes canonical results.
- Installed task tools use localhost:8799; installed version 0.43.0.
- No ControlMesh tool is exposed in current Codex tool inventory. This is not proof no
  supported CLI/API exists. Inspect the current server routes and actual installed source.
- Prior doctor shows background/native policies denied; distinguish local package doctor
  configuration from running server's actual configuration. Do not turn off policy gates.

First check existing runtime endpoint/listener and parent binding read-only. Never infer
that CM parent 'main' maps to this Codex desktop task. Determine what explicit binding or
poll/long-poll command allows the current controller to receive its own job results.
Prefer existing TaskHub/HostJob external tool-result mechanisms to a new process registry.
Find/run an isolated integration test with a fake worker: completion persists once,
parent consumes once, process failure retained, duplicate wake/restart causes no repeat
execution. Do not merely monitor markdown for the word PASS.

You may modify relevant CM source/tests and only these task docs:
- delegation/taskhub-parent-bridge-result.md
- delegation/taskhub-parent-bridge.md (status/evidence)
Do not edit sibling worker files or global progress/architecture until main acceptance.
No commits/push, production writes, actual account sends, browser automation, service
restart, scheduled model wakeups, or cancelled task revival. Do not silently downgrade
native-session continuation to pasted text. Stop on account quota/auth errors.

If existing APIs already satisfy the requirement, use them in isolated proof and provide
exact invocation/binding instead of adding redundant code. If a real desktop wake-up is
not exposed, implement/verify the existing-parent result wait/consume path and state the
remaining boundary exactly; do not forge human messages or edit Codex private databases.

Report actual APIs, source lines, edits, test logs, exit codes, native CLI session ID, and
live vs isolated evidence. Scope completion is a verified parent result channel, not the
whole TS migration. Existing cheap-worker defaults are globally configured; do not pass
acceptEdits (overrides CBC bypassPermissions) and do not run a full runtime suite.
