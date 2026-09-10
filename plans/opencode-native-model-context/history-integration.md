# History Viewer → TaskHub continuity proposal

Status: inspected design; external-session adoption is not implemented.

## Ownership and flow
1. Viewer reads native session stores and emits the existing evidence/handoff bundle plus a candidate reference. It never edits CM private task files or starts a provider from a browser command string.
2. Trusted local Python admission resolves a candidate against the local provider store, verifies provider, host/profile, source revision and repository identity, and creates a new TaskHub task with source provenance. A Viewer path or session ID alone is not authority.
3. For the same provider, use an explicit native fork when supported. Save the returned child session ID on the new task; preserve the original. Never use “continue latest” for automatic selection.
4. If fork is unsupported or the provider changes, start a fresh task with a bounded, labeled handoff. This transfers selected information, not hidden native state.
5. On completion, CM owns task lifecycle and validation. Verified durable facts go through normal SpecMesh project/architecture/plan updates. History remains supporting evidence.

## Candidate selection
First filter local provider/profile and resolvable session; then compare actual repository paths in evidence, remote identity and task/topic. Cwd and title are insufficient, especially sessions started in the home directory. Prefer relevant user intent and recent verified artifacts over a recent timestamp alone. Show source, reason for selection, model, last update and conflicts. Never inherit old permissions from the transcript.

## Proposed fields (not a current API)
An external_session reference needs provider, opaque source ID, local profile/host identity, source revision and continuation mode. Repository binding, requested model, explicit follow-up and expected source revision are checked by Python. Use additive persisted provenance fields with legacy-null loading and idempotency keyed to source revision + request. Store selected evidence IDs and a bounded handoff digest rather than complete transcripts.

## Gates before implementation
| Gate | Acceptance |
| --- | --- |
| Admission | Untrusted browser references cannot become shell arguments or grants; existing source, owner and tool-grant checks run before spawn. |
| Repository | Deleted, moved, stale or ambiguous repositories require resolution; no automatic change of worktree based solely on history. |
| Fork | Original session unchanged; child ID returned, bound and recovered by TaskHub. |
| Model | Explicit selection or native resolution recorded separately from a successful live response. |
| Grants | OpenCode restrictive mapping remains rejected until native enforcement is verified; no grant deletion to enable continuation. |
| Concurrency | Duplicate requests are idempotent; active-source/fork races have deterministic behavior. |
| Recovery | Process interruption and restart recover child provenance, ownership and delivery identity. |
| Privacy | No raw transcript uploads or private runtime paths in public API/artifacts by default. |
| Product | User can choose, inspect, start and trace the resulting task; a copied command alone is not TaskHub integration. |

## Delivery phases
P0: read-only discovery, candidate evidence and bounded native fork proof (this investigation).
P1: local Python external-session admission with fixtures and lifecycle/golden coverage; no public mutation API.
P2: Viewer candidate UI and reviewed local handoff contract, shell quoting tested on supported platforms.
P3: real interruption/recovery/cancel/delivery and stale-source acceptance. Roll back via feature disable; preserve existing tasks and native source stores.

## Limits
Native context may be compacted, incomplete or wrong. Preserve evidence and reread canonical SpecMesh facts before edits; this workflow improves continuity but cannot guarantee perfect agent memory.
