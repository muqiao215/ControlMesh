# Progress

## Current
Implementation and real terminal acceptance complete; published as v0.42.2 and installed locally.

## Done
- Isolated branch feat/native-session-adoption from fe1ef45.
- Explicit native --dir produces JSON output and exit 0 on installed OpenCode 1.18.29.
- Added local terminal Viewer search, native inspection and TaskHub adoption.
- Persisted native identity/revision; retained explicit model/cwd and CM runtime home.
- Added supervised model preflight, stale/duplicate rejection, CM advisory lease, cancellation checkpoints and resume persistence.
- 5,703 full-suite tests passed (Python 3.12). Final recovery and transport changes passed 379 targeted tests, including 21 native-adoption cases. Ruff, CI Mypy smoke and new-module Mypy passed.
- Real isolated TaskHub acceptance: Viewer found the original SpecMesh session; MiniMax preflight and native continuation completed in 15.86 seconds. Same native ID, old qiao-wechat context correctly recalled. Provider tools denied via native configuration; no application code or WeChat operations.

- Terminal/native suite: 50 tests passed after real terminal wiring; release-contract checks rerun after version expectation update.

- Final real terminal run: Viewer search, native adoption, model preflight, task completion and terminal inbox delivery all succeeded in 15.99 seconds without mocked runtime components.
- Final command-routing/probe/native/terminal regression set: 220 tests passed; Ruff passed.

## Remaining
None for this delivery.

## Issues
- Terminal startup had no main transport stack, so its TaskHub lacked a main CLI service/result handler. Explicit terminal service/inbox wiring is now covered by a regression.
- Initial PR CI found the release contract still pinned to 0.42.1 after the version bump. Updated the explicit release expectation to 0.42.2; no runtime failures were reported.
- Lease applies to CM processes only; independent native clients must be stopped first.
- Native grants unsupported by OpenCode mapping remain rejected; this feature does not close grant enforcement unit A.1.
- Initial acceptance harness import collided with an unrelated work/inspect.py; corrected with Python safe-path mode. A harness method name was corrected to set_result_handler before execution.

## Next
Continue terminal product and A.1 work under their own plans.

## Release verification (2026-09-11)

PR #28 merged as c2c4e3f. Main CI 34505610074 passed (5,707 tests on each Python version); publish 34505704112 passed. GitHub/PyPI v0.42.2 and local `cm --version` agreed; daemon health returned HTTP 200 after restart. Local deployment observations are dated evidence, not a guarantee about future installations.
