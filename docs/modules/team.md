# Team Module

The additive `ductor_bot/team/` package is the first state-only slice of the OMX migration.

It deliberately does **not** start workers, dispatch over the live bus, manage tmux, or replace Ductor's existing task/session stack.

## Included in This Cut

- contracts and validated models for:
  - team manifest
  - workers and leader session identity
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
- phase transition machine:
  - `plan`
  - `approve`
  - `execute`
  - `verify`
  - `repair`
  - terminal: `complete`, `failed`, `cancelled`

## Not Included Yet

- live delivery integration
- runtime dispatch through `MessageBus`
- worker process lifecycle
- tmux/team runtime management
- gateway dispatch wiring
- write-capable external API operations

## Files

- implementation: `ductor_bot/team/`
- tests: `tests/team/`
