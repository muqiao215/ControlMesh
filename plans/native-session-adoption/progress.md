# Progress

## Current
Implementation complete; regression review and publication in progress.

## Done
- Isolated branch feat/native-session-adoption from fe1ef45.
- Explicit native --dir produces JSON output and exit 0 on installed OpenCode 1.18.29.
- Added local terminal Viewer search, native inspection and TaskHub adoption.
- Persisted native identity/revision; retained explicit model/cwd and CM runtime home.
- Added supervised model preflight, stale/duplicate rejection, CM advisory lease, cancellation checkpoints and resume persistence.
- 5,703 full-suite tests passed (Python 3.12). Final recovery and transport changes passed 379 targeted tests, including 21 native-adoption cases. Ruff, CI Mypy smoke and new-module Mypy passed.
- Real isolated TaskHub acceptance: Viewer found the original SpecMesh session; MiniMax preflight and native continuation completed in 15.86 seconds. Same native ID, old qiao-wechat context correctly recalled. Provider tools denied via native configuration; no application code or WeChat operations.

## Remaining
PR/merge CI, v0.42.2 publication and local installation verification.

## Issues
- Lease applies to CM processes only; independent native clients must be stopped first.
- Native grants unsupported by OpenCode mapping remain rejected; this feature does not close grant enforcement unit A.1.
- Initial acceptance harness import collided with an unrelated work/inspect.py; corrected with Python safe-path mode. A harness method name was corrected to set_result_handler before execution.

## Next
Complete broader regression checks and publish reviewed changes.
