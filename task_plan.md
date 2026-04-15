# Task Plan: ControlMesh Harness System

## Goal
Define a concrete design and implementation direction for the ControlMesh harness system: file-driven control plane, controller/worker write boundaries, automatic adjudication, explicit state vocabulary, and frontstage-history separation from runtime events.

## Current Phase
Phase 3

## Phases

### Phase 1: Requirements and Evidence Capture
- [x] Confirm the product boundary: history is frontstage-only, runtime/task events are separate
- [x] Capture current ControlMesh session persistence behavior
- [x] Capture cc-connect evidence for user-facing session/history semantics
- [x] Capture user-authored harness patterns from `my-programming-world`
- [x] Record findings in `findings.md`
- **Status:** complete

### Phase 2: Harness Architecture and Data Model
- [x] Define the harness as a project state machine, not a chat workflow
- [x] Define the control plane three-file model: `task_plan` / `findings` / `progress`
- [x] Define controller/worker write boundaries and proposal promotion
- [x] Define the canonical history object: visible transcript turns
- [x] Define non-goals: heartbeats, retries, task lifecycle, provider chatter, internal agent dialogue
- [x] Choose storage direction: dedicated transcript store, not `sessions.json` or `named_sessions.json`
- [x] Lock the minimal turn schema and storage layout
- [x] Write a canonical design document under `docs/modules/harness.md`
- **Status:** complete

### Phase 3: Read/Write Surface Design
- [x] Scaffold `plans/` control-plane skeleton
- [x] Define the write points for frontstage transcript events in normal chat flows
- [x] Define the read/query surface for recent history and session browsing
- [ ] Define attachment/result send-back handling as visible transcript entries
- [x] Define the separate runtime/event panel source and boundary
- **Status:** in_progress

### Phase 4: Incremental Implementation Plan
- [x] Identify the smallest first cut that ships value without broad migration
- [ ] Define migration/compatibility stance for existing session metadata
- [x] Define tests for transcript correctness and runtime-history separation
- [x] Define evaluation/exception trigger artifacts for the harness control plane
- [ ] Record rollout and fallback plan
- **Status:** pending

### Phase 5: Delivery
- [ ] Review the plan for scope control and correctness
- [ ] Make sure the plan is implementation-ready rather than aspirational
- [ ] Hand back the plan with explicit next coding cut
- **Status:** pending

## Key Questions
1. What is the minimal first coding cut: transcript substrate only, or transcript plus event-sink skeleton?
2. Which visible system outputs should remain separate `system_visible` turns versus being normalized into assistant turns?
3. How much of the evaluation layer should ship as files/artifacts before deeper runtime automation exists?
4. What is the smallest implementation cut that creates a stable harness foundation without broad control-plane churn?

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| History is defined as frontstage, user-visible interaction only | Matches user product boundary and avoids runtime-noise contamination |
| Runtime/task lifecycle events belong in a separate run/status surface | Keeps history cognitively stable while preserving observability |
| ControlMesh should be documented as a harness system, not a chat workflow | This matches the user's architecture framing and keeps implementation aligned with the real governance model |
| Automatic adjudication is the default; humans are only interrupted at human gates or exceptions | Preserves frontstage context and prevents over-reviewing routine cuts |
| Canonical files are truth; worker outputs are candidate evidence until promoted | Reinforces single-writer control-plane semantics |
| `sessions.json` and `named_sessions.json` should remain metadata/state stores, not transcript truth | Current structures store routing/session state, not durable user-visible turns |
| Dedicated transcript storage is the target direction | Prevents dependence on provider-private logs and supports cross-platform parity |
| cc-connect is a semantic reference, not an implementation dependency | Useful as evidence for session/history UX, but ControlMesh should own its own transcript truth |
| The repository should include a real `plans/` skeleton immediately, before deeper runtime automation | Makes the harness concrete and gives future cuts a canonical landing zone |

## Proposed Minimal Transcript Schema

```text
TranscriptTurn
- turn_id
- session_key
- surface_session_id
- role                    # user | assistant | system_visible
- visible_content
- attachments[]           # optional visible files/images
- created_at
- reply_to_turn_id        # optional
- source                  # normal_chat | foreground_task_result | explicit_send_back
- transport               # tg | mx | api | ...
- topic_id                # optional
```

Notes:
- `system_visible` is only for explicitly user-visible foreground notices, not runtime noise.
- Task started/completed/failed, retries, heartbeats, worker recovery, provider resume, and internal agent hops do not belong here.

## Proposed Storage Direction

Preferred first cut:
- add a dedicated transcript store, e.g. `~/.controlmesh/transcripts/`
- store append-only JSONL per surface session key or per chat/topic bucket
- keep indexing simple first: latest-first reads from file tail or recent in-memory slice

Rejected directions:
- extending `sessions.json` with full transcript payloads
- using `named_sessions.json` as chat history
- treating Claude/Codex/Gemini native logs as canonical history truth

## Implementation Cuts

### Cut 1: Transcript Substrate
- Introduce transcript path resolution in workspace paths
- Add transcript store model and append/read helpers
- No command/UI change yet beyond internal write plumbing
- Status: implemented

### Cut 2: Foreground Write Plumbing
- On normal user message receipt, append a visible user turn
- On final foreground reply send, append a visible assistant turn
- On visible file/image send-back, append attachment metadata as part of the surfaced turn
- Do not append stream previews, tool chatter, retries, or heartbeats
- Status: partially implemented (text-only user + assistant turns)

### Cut 3: Read Surface
- Add a minimal history read command or API surface
- Return recent visible turns only
- Keep ordering and pagination transcript-native rather than provider-log-native

### Cut 4: Runtime/Event Separation
- Add or formalize a runtime event sink for task lifecycle and operator diagnostics
- Ensure history readers never join runtime events into the transcript query path

### Cut 5: Evaluation and Session Browser Integration
- Introduce evaluation artifacts such as exception triggers and review outcomes
- Show transcript-backed history in session browser / future UI
- Keep session metadata views available, but clearly separate from conversation history

## Verification Targets
- User message + final assistant reply produce exactly two visible transcript turns
- Stream previews do not create extra history entries
- Task start/fail/retry/heartbeat events do not appear in history
- Explicit task result send-back that the user sees does appear in history
- Session metadata (`sessions.json`, `named_sessions.json`) can remain unchanged without breaking transcript reads
- Workers cannot directly mutate canonical state files when the harness control plane is introduced
- Focused tests for transcript store and orchestrator history seam pass

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| No existing planning files in repo root | 1 | Created a fresh scoped planning set for this design line |

## Notes
- This plan is intentionally product-boundary first, implementation second.
- The first implementation goal is harness truth ownership, with transcript truth as the first concrete substrate.
- If naming changes later (`/history`, session TUI, web chat), the storage boundary should remain unchanged.
