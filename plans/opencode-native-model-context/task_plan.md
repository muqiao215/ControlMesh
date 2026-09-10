# OpenCode readiness and external-session continuity

## Goal
Fix reproduced OpenCode config/preflight/CLI compatibility defects and submit a PR. Assess History Viewer integration with evidence, selecting a relevant native session and validating non-destructive continuation.

## Scope and non-goals
Python owns task execution and admission. Viewer supplies evidence and candidate references. Do not write private TaskHub state, introduce a public mutation API, replace production installs, or treat conversation history as project truth. External-session adoption is a proposed follow-up, not delivered runtime functionality.

## Phases
1. Reproduce native config and model behavior: complete.
2. Fix JSON/JSONC merge, honest preflight and native permission flag: complete.
3. Run focused regressions and native probes: in_progress.
4. Record integration contract and submit reviewable PR: pending.

## Acceptance
- Schema-only JSONC preserves JSON model; explicit JSONC wins; nested defaults survive.
- Invalid overlay does not select a lower-precedence model; XDG roots remain isolated.
- Static model resolution does not claim live inference; timeout/catalog/empty/error output cannot pass live probe.
- Default OpenCode command uses supported native auto-approval without bypassing tool-grant rejection.
- Record native run and fork outcomes separately from unit tests. Preserve original session.
- Explain missing external adoption and permission gates; do not mark integration implemented.

## Rollback
Revert the focused PR commits. No persisted fields, session databases, production configuration or installed runtime are migrated.

## Next Step
Finish live verification, then publish the PR and local integration report.
