# Task: Execution Tool Grants (Unit A)

## Goal

Deliver the pre-implementation review for the queued safety unit A from
`plans/weekly-report-followthrough/`: a per-provider enforceable tool-boundary
matrix and the minimal persistence + recovery contract for tool grants, so the
implementation can start with real enforcement instead of descriptive fields.

## Scope

- Audit `controlmesh/execution_policy.py`, `tasks/models.py`, `bus/envelope.py`,
  `orchestrator/core.py`, provider launch/adapters, and recovery entry points.
- Determine which tool restrictions each installed provider CLI (claude, codex,
  gemini, opencode) can natively enforce, using installed `--help` as evidence.
- Define the grant snapshot, persistence shape, and recovery/rebind contract.

## Non-goals

- No production code changes in this review step.
- No public API/mutation surface; Mutation API admission stays deferred.
- No new sandbox work (source sandbox gate already landed).

## Phases

### Phase 1: Current-boundary audit (policy, task model, envelope, orchestrator)
Status: complete

### Phase 2: Per-provider enforceability matrix (installed CLI evidence)
Status: complete

### Phase 3: Recovery/episode persistence channel review
Status: complete

### Phase 4: Contract design + findings record
Status: complete

## Success

- A written enforceability matrix: per provider, which limits are CLI-enforced,
  which need the CM tool boundary or sandbox, and which providers must reject
  restricted tasks.
- A minimal contract draft: grant snapshot fields, persistence location,
  recovery rebind rules, fail-closed defaults, rollback constraints.
- All claims carry file:line or CLI-help evidence.

## Status

Pre-implementation review complete AND Unit A v1 implemented: grant model +
issuance, per-adapter mapping/rejection (claude/codex enforced; gemini/
opencode/claw/openai_agents fail closed), task-record persistence, recovery
rebind, golden/drift gate wired into `pnpm test:golden`. See `progress.md`.

## Next Step

Full-suite confirmation, commit, push, CI. Follow-up waves: opencode config
overlay, gemini policy-engine config, claw/openai_agents hard-gate proof,
one-shot cron/webhook grant wiring, request-side restriction surface.
