# Team Module

The additive `ductor_bot/team/` package is the first state-led slice of the OMX migration.

It now includes a narrow leader-session live bridge, but it still does **not** start workers, manage tmux, or replace Ductor's existing task/session stack.

## Included in This Cut

- contracts and validated models for:
  - team manifest
  - nested leader session identity via `TeamSessionRef`
  - nested leader/worker runtime ownership via `TeamRuntimeContext`
  - task claims
  - dispatch requests
  - mailbox messages
  - events
  - phase state
- file-backed state primitives under a dedicated team state root
- read-only JSON envelope API:
  - `read-manifest`
  - `list-tasks`
  - `get-summary`
  - `read-events`
- limited live delivery bridge:
  - dispatch requests can inject a coordination prompt into the leader session via `MessageBus`
  - mailbox messages can emit leader-visible unicast notifications
- phase transition machine:
  - `plan`
  - `approve`
  - `execute`
  - `verify`
  - `repair`
  - terminal: `complete`, `failed`, `cancelled`

## Not Included Yet

- worker process lifecycle
- tmux/team runtime management
- gateway dispatch wiring
- write-capable external API operations
- true worker-session delivery or per-worker runtime execution
- end-to-end delivery acknowledgements beyond successful bus submission

## Live Bridge

The current live path is intentionally narrow:

- `TeamManifest.leader.session` is the only routable live target
- dispatch requests use `MessageBus` injection into that leader session
- mailbox messages use a leader-visible unicast notification without injection
- worker targets remain team-state semantics, not separate live runtimes

This keeps the cut additive to Ductor's existing bus/session stack and avoids inventing a second delivery mechanism before worker runtime management exists.

## Identity Model

`SessionKey` remains Ductor's chat/session identity. The team layer composes with it instead of redefining it:

- `TeamLeader.session` stores a `TeamSessionRef`
- `TeamLeader.session_key` materializes the existing `SessionKey`
- `TeamLeader.runtime.cwd` owns the leader workspace/runtime cwd
- `TeamWorker.runtime.provider_session_id` stores provider-local runtime session ids

The manifest now persists nested `session` and `runtime` records, but still accepts the earlier flattened fields on input:

- leader `session_transport` / `session_chat_id` / `session_topic_id`
- manifest-level `cwd`
- worker `session_id`

## Files

- implementation: `ductor_bot/team/`
- tests: `tests/team/`
