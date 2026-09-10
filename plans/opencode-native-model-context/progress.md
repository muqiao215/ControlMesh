# Progress

## Current
Investigation and focused fixes delivered in PR #26. External-session integration is a proposal, not implemented or accepted runtime behavior.

## Done
- JSON/JSONC merge, truthful static diagnostic, response-validated live probe, closed probe stdin and native --auto mapping.
- 713 CLI, execution-grant, host-policy and golden tests passed (12.62 s). After the stdin change, 23 discovery tests passed (0.42 s).
- Changed-file Ruff, focused auth/discovery mypy and diff whitespace checks passed.
- Real patched OpenCodeCLI command returned CM_WRAPPER_OK, rc=0, is_error=false and a session ID, with native tools denied.
- Real final probe_opencode_model_sync returned True for an explicit model, requiring the native PONG response; no discovery fallback or exit-code-only acceptance.
- Viewer/TaskHub boundaries, candidate-selection rules, proposed admission contract and acceptance gates documented in history-integration.md.
- Relevant source history identified by repository-specific content, not title alone.

## Remaining
Remote CI/review and production rollout are separate. Future external-session implementation needs the listed gates and real lifecycle validation.

## Issues
Native source fork attempts in source and isolated cwd, including closed-stdin retry, returned no events within 55/180-second bounds. Source timestamp/message count stayed unchanged; no child was created. Cause is not established. This is failed continuation acceptance, not proof the model is unavailable. Installed default model differs from the successfully tested explicit model and was not rewritten.

## Next
Review PR #26 and resolve native fork/admission gates before claiming integrated continuation.
