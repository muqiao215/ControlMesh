# Native session adoption

## Objective
Personally implement History Viewer candidate discovery and explicit OpenCode native session adoption by CM TaskHub. Preserve native dialogue independently of SpecMesh project truth.

## Requirements
- Validate native identity, directory, model and source before dispatch.
- Persist provenance and resume the same session; no silent new-session fallback.
- Preserve existing execution grants and ingress policy.
- Exercise completion, cancellation, recovery and duplicate admission.
- Validate real contextual continuation without running WeChat or changing application code.

## Phases
1. Investigate native CLI output/exit and TaskHub ownership — complete.
2. Implement bounded discovery, admission, persistence and provider execution — complete.
3. Verify targeted lifecycle/security tests and real native continuation — complete.
4. Document boundaries, review and publish authorized changes — complete.

## Non-goals
No new automation, cancelled-task recovery, private runtime mutation by Viewer, or promise of lossless model memory.

## Acceptance
Explicit existing session reaches provider, output completes, source survives persistence/recovery; stale/missing/mismatched/duplicate sources fail; grants are unchanged. Viewer candidate metadata is evidence, not authority.

## Rollback
Stop adopted tasks before reverting feature commits. Do not resume adopted tasks with older CM builds that cannot interpret native provenance/cwd. Existing tasks without native provenance retain previous semantics.

## Next Step
Continue terminal product and A.1 work under their own plans.

## Release verification (2026-09-11)

PR #28 merged as c2c4e3f. Main CI 34505610074 passed (5,707 tests on each Python version); publish 34505704112 passed. GitHub/PyPI v0.42.2 and local `cm --version` agreed; daemon health returned HTTP 200 after restart. Local deployment observations are dated evidence, not a guarantee about future installations.
