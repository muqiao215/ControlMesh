# Execution Provenance + Sandbox Gate

## Goal

Establish one Python-owned trusted execution context from every ingress to the provider
process boundary, and fail closed before host execution whenever the authenticated source
policy requires a sandbox but no sandbox is ready.

## Next Step

Commit and push the intended implementation, tests, documentation, and task-memory files
to `origin/main`, then verify the remote ref.

## Context

This is the first implementation unit of `Operational Proof v1`. The completed assessment
is recorded in `plans/operational-proof-v1-assessment/`. Current Docker setup falls back to
host execution globally, while source identity does not survive consistently to
`CLIService`; that makes untrusted and unattended execution policy unenforceable at the
last responsible boundary.

## Requirements

- Keep Python authoritative for provenance, policy, provider processes, persistence, and
  audit behavior.
- Introduce one trusted execution-context model; do not create separate identities for
  Feishu, cron, webhook, inter-agent, TaskHub, and provider execution.
- Generate internal trace identity inside ControlMesh. Never accept a prompt, message body,
  header, or provider response as trace authority.
- Carry authenticated source facts through MessageBus/orchestrator/task paths into
  `AgentRequest` and the final provider-launch decision.
- Preserve transport message/thread references only as bounded diagnostic metadata; do not
  persist message bodies, credentials, absolute paths, or sensitive tool arguments.
- Define source-aware execution policy for sandbox requirement, allowed/disallowed tools,
  network posture, writable roots, and confirmation level using existing policy vocabulary
  where possible.
- Require sandbox execution for untrusted or unattended mutation-capable origins, including
  group messages, configured bot handoffs, cron, and webhook execution.
- When sandbox is required but unavailable, reject before constructing or starting a host
  provider subprocess and emit stable typed diagnostic evidence.
- Preserve explicitly trusted local/foreground compatibility unless the audited policy
  proves a stricter default is required.
- Keep provider fallback policy separate from sandbox/host fallback policy.
- Keep public OpenAPI, SDK, and Web read-only; do not add create, tell, resume, cancel,
  accept, reject, or generic mutation operations.
- Avoid a persisted-format migration unless necessary. Any persisted addition must be
  additive, compatible with existing readers, normalized, and migration-tested.

## Non-goals

- Full cross-server trace storage or `/cm diagnose <message_id>`
- Fleet node-manifest and configuration-drift rollout
- Process-kill/restart fault-injection matrix
- Exactly-once external Feishu delivery
- Public mutation API or TypeScript runtime ownership
- Provider migration, new task types, remote Web, or browser credential work
- Lark CLI/OpenAPI MCP business-tool integration
- Broad Docker/runtime refactoring for architectural symmetry

## Phases

### Phase 1: Baseline and ownership audit

- [x] Confirm live `origin/main`, current branch, recent commits, and preserve all existing
      local changes.
- [x] Read project memory, this plan, the Operational Proof assessment, relevant completed
      plans, and the full production/test call graph.
- [x] Inventory every ingress and classify trusted source facts, execution behavior,
      current Docker fallback, and existing coverage.
- [x] Record the exact missing cases and reject duplicate tests.
- **Status:** complete

### Phase 2: Context and policy contract

- [x] Define the minimal trusted execution-context contract and source taxonomy.
- [x] Define the policy decision/result vocabulary and last responsible enforcement seam.
- [x] Specify compatibility behavior for legacy callers and additive persistence if needed.
- [x] Confirm normalized diagnostic fields and sensitive-data exclusions.
- **Status:** complete

### Phase 3: Production implementation

- [x] Propagate trusted context through each required ingress and execution path.
- [x] Resolve source-aware sandbox/tool/network/write/confirmation policy.
- [x] Enforce sandbox-required denial immediately before provider process creation.
- [x] Emit stable accepted/denied policy evidence without exposing sensitive data.
- **Status:** complete

### Phase 4: Executable safety evidence

- [x] Add focused tests only for missing propagation, policy, compatibility, and denial cases.
- [x] Prove sandbox-required denial creates no host process and no workspace mutation.
- [x] Prove spoofed/user-provided trace or source facts cannot weaken policy.
- [x] Add a deterministic production-Python evidence matrix and CI drift gate if dispersed
      tests cannot provide one machine-comparable contract.
- **Status:** complete

### Phase 5: Verification and memory sync

- [x] Run focused ingress, MessageBus, orchestrator, TaskHub, provider, and Docker tests.
- [x] Run Ruff on the modified scope and the complete Python suite.
- [x] Run protocol/TypeScript/build gates only if their owned inputs change.
- [x] Verify OpenAPI and public SDK remain read-only.
- [x] Inspect the final diff for credentials, absolute paths, caches, generated output, and
      unrelated changes.
- [x] Promote durable ownership/invariant knowledge to architecture/decisions/project memory
      and leave transient evidence in this task directory.
- **Status:** complete

### Phase 6: Release handoff

- [x] Re-fetch `origin/main` and verify it still matches the audited baseline.
- [ ] Commit only the intended implementation, tests, documentation, and task-memory files.
- [ ] Push to `origin/main` and verify the remote commit.
- **Status:** in progress

## Minimum Safety Matrix

1. Trusted local foreground execution preserves its approved compatibility behavior.
2. Feishu group execution requires the configured sandbox policy.
3. Configured bot-to-bot handoff cannot fall back to the host.
4. Cron and webhook execution cannot fall back to the host.
5. A sandbox-required request succeeds only when the sandbox is confirmed ready.
6. Missing Docker binary, unavailable daemon, missing image with auto-build disabled,
   failed build, failed container start, and failed runtime recovery all deny safely.
7. Denial occurs before any provider host subprocess, tool execution, or workspace write.
8. The same source/context yields a deterministic policy decision and normalized evidence.
9. User-controlled text or metadata cannot spoof a trusted source, trace, or relaxed policy.
10. Provider fallback cannot silently convert a sandbox-required denial into host execution.

## Success

- Every production provider launch has a trusted, internally generated execution context or
  an explicitly documented legacy compatibility context.
- Source policy is evaluated at one Python-owned boundary and is not inferred from prompts,
  filenames, process labels, or provider names.
- All sandbox-unavailable variants fail closed for required origins before host execution.
- Focused and full gates pass, with exact results recorded in `progress.md`.
- Public product surfaces remain read-only and Python retains runtime ownership.

## Current Phase

Phase 6 — Release handoff (in progress).

## Completion

Implementation and gates completed on 2026-09-05. The clean environment full Python suite
passed 5574 tests; the default systemd-invoked shell has one unrelated restart expectation
failure (recorded in `progress.md`).

## Decisions Made

| Decision | Rationale |
|---|---|
| Start with provenance and the sandbox gate | Cross-node diagnosis and process fault injection need a trustworthy source/trace carrier first. |
| Enforce at the provider-launch boundary | Earlier routing checks alone can be bypassed by alternate ingress or retry paths. |
| Keep provider fallback separate | Model/provider degradation is not authorization to weaken execution isolation. |
| Use startup-confirmed sandbox state for unattended sources | Direct observer unit construction remains legacy-compatible until lifecycle wiring confirms the empty/active Docker state; production startup always marks the state explicitly. |
| Keep public mutation deferred | This work hardens private Python execution and does not satisfy mutation admission requirements. |

## Errors Encountered

None.
