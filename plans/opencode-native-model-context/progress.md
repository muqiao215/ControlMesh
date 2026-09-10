# Progress

## Current
Fix verified locally; PR preparation. External-history admission remains proposed.

## Done
- JSON/JSONC overlay, truthful static diagnostic, strict live probe result and native --auto mapping.
- 713 tests passed: tests/cli, tests/test_execution_tool_grants.py, tests/runtime/test_host_execution_policy.py, tests/golden/test_tool_grant_golden.py (12.62 s).
- Ruff passed on all six changed Python files; focused mypy passed for auth/discovery; git diff --check passed.
- Actual patched OpenCodeCLI command using native 1.18.29 and explicit model returned CM_WRAPPER_OK, rc=0, parsed is_error=false and a session ID. Native tools were denied in the smoke environment.
- Read-only Viewer/TaskHub boundary investigation and integration acceptance contract.

## Remaining
Publish PR; record bounded native fork retry result; deliver local report. Full CI and installed-runtime upgrade are not established by these local checks.

## Issues
First 55-second history fork timed out without output; source unchanged. Longer retry pending. Production configuration points at a different default than the successful explicit model, and was not rewritten.

## Next
Publish focused PR and finish continuation evidence.
