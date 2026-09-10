# Findings

## Verified
- Baseline 751c4c9; installed runtime is a separate older version. Work isolated from an unrelated dirty checkout.
- OpenCode 1.18.29 loads global JSON then JSONC as an overlay. A schema-only JSONC exposed CM's single-file lookup defect. Native precedence: https://opencode.ai/docs/config/ and upstream packages/opencode/src/config/config.ts.
- Static discovery alias never ran inference by default, despite diagnostic wording. The live probe also accepted timeout plus catalog presence and successful exit without a response. Fixed to require a native text sentinel and reject error events.
- Current native run exposes --auto, not Claude's --dangerously-skip-permissions. --auto approves otherwise unspecified permissions; explicit native denials still apply. https://opencode.ai/docs/cli/.
- Explicit zai-coding-plan/glm-5.3 answered a fresh sentinel. Local configured default references a different model; this fix must not silently rewrite operator model choices.
- Viewer buildResumeInvocation currently generates commands for Codex and Claude only; OpenCode indexing does not establish an OpenCode resume UI.
- Viewer audit/handoff.py produces a v1 source-qualified session, cwd, goal, constraints, changed files, verification and evidence bundle.
- TaskHub.resume requires an existing registered task, resumable status, provider and session ID. TaskSubmit lacks an external session reference. Public API remains read-only.
- OpenCode tool-grant mapping currently rejects config_overlay_unverified. Native direct continuation does not prove a constrained TaskHub launch is admitted.

## Proposed integration
See history-integration.md. This is a bounded design, not an implemented public mutation surface.

## Investigation issues
A native fork did not return within the initial 55-second bound; source metadata and message count were unchanged. A longer tool-disabled retry is recorded in progress. Two cancelled investigatory workers were stopped before root edits. Initial focused mypy exposed pre-existing unchecked JSON returns; parser now validates object shape. An incorrect test-directory argument was corrected before recording test results.
