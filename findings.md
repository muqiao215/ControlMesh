# Findings & Decisions

## Requirements
- History for ControlMesh should reflect only frontstage, user-visible interaction.
- Runtime/task lifecycle events must live in a separate run/status surface.
- Internal agent dialogue, provider round-trips, retries, heartbeats, and recovery noise must not pollute visible history.
- The resulting design should support future multi-platform parity instead of depending on one provider's native logs.
- The plan should be implementation-oriented and scoped into concrete cuts.

## Research Findings
- The strongest user-authored harness pattern does not live in code first; it lives in method docs and runbooks in `my-programming-world`.
- `my-programming-world` describes ControlMesh-style work as a layered system with tools, memory, tasks, cron, knowledge, executor, and output layers.
- `Wiki/自动化开发范式与智能体协作.md` is effectively a canonical harness spec:
  - file-backed state machine
  - controller/worker split
  - single-writer rule
  - task-local evidence vs canonical state
  - proposal promotion rather than direct mutation
- `编程/开发指南/PLC/PLC 完整项目运行清单.md` shows the same governance shape in a domain-specific harness with explicit ordered gates.
- `编程/浏览器自动化大结局：远程登录加持久化 profile 才是正解.md` shows another concrete harness shape: identity layer, production entry layer,补位 layer.
- Current ControlMesh/ControlMesh session persistence is metadata-oriented, not transcript-oriented.
- `controlmesh/session/manager.py` stores `provider_sessions`, `session_id`, `message_count`, `total_cost_usd`, and `total_tokens`; it does not model visible message transcript turns.
- `controlmesh/session/named.py` stores named-session metadata such as `prompt_preview`, `status`, `message_count`, and `last_prompt`; it is a background-session registry, not a visible chat transcript store.
- `docs/modules/session.md` documents only `sessions.json` and `named_sessions.json` for session lifecycle/state persistence.
- `cc-connect` clearly treats history as part of user-facing session management:
  - `docs/usage.md` groups `/new`, `/list`, `/switch`, `/current`, and `/history [n]` under `Session Management`.
  - `config.example.toml` says `data_dir` stores `conversation history and session state as JSON files`.
  - `CHANGELOG.md` mentions `cc-connect sessions` terminal browsing and `/history` continuing to work via agent JSONL reads after `/switch`.
- Therefore the stable product direction is: ControlMesh should own a frontstage transcript model directly, rather than overloading state registries or leaning on provider-private logs as final truth.

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Adopt a dedicated visible transcript store | Needed to make history a first-class product surface |
| Treat the full system as a harness with control plane, execution plane, and evaluation plane | More accurate than treating the work as chat orchestration plus ad hoc tasks |
| Use the `task_plan` / `findings` / `progress` trio as the canonical control-plane vocabulary | This matches the user's documented method and keeps project truth explicit |
| Make controller/worker write boundaries explicit in the design | This is the user's hardest governance rule and must not remain implicit |
| Default to automatic adjudication and exception-triggered pullback | Matches the user's frontstage-context-saving direction |
| Keep transcript truth separate from session metadata truth | Prevents state objects from becoming overloaded and brittle |
| Treat provider-native logs as optional recovery/import sources only | Avoids coupling history semantics to Claude/Codex/Gemini internals |
| Count visible task result send-backs as transcript-worthy when surfaced to the user | Preserves conversation continuity without exposing backend execution noise |
| Exclude lifecycle events such as started/completed/failed from transcript history | Those belong to observability, not conversation recall |

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| Earlier discussion risked overstating that the reference repo had no real history support | Tightened the wording: cc-connect definitely exposes history semantics, but its sources appear mixed between its own data dir and provider-native logs |
| ControlMesh current repo has no existing planning files for this line | Started a dedicated file-based planning set in repo root |

## Resources
- `/root/.controlmesh/analysis/controlmesh-src/docs/modules/session.md`
- `/root/.controlmesh/analysis/controlmesh-src/controlmesh/session/manager.py`
- `/root/.controlmesh/analysis/controlmesh-src/controlmesh/session/named.py`
- `/root/.controlmesh/workspace/repos/cc-connect/docs/usage.md`
- `/root/.controlmesh/workspace/repos/cc-connect/config.example.toml`
- `/root/.controlmesh/workspace/repos/cc-connect/CHANGELOG.md`
- `/root/.controlmesh/workspace/repos/cc-connect/core/engine.go`
- `/root/.controlmesh/workspace/repos/cc-connect/cmd/cc-connect/sessions.go`
- `/root/.controlmesh/workspace/repos/my-programming-world/Wiki/自动化开发范式与智能体协作.md`
- `/root/.controlmesh/workspace/repos/my-programming-world/学语与公众号/公众号/草稿/Superpowers与Plan-with-Files_把AI从聊天搭子变成长期项目搭子.md`
- `/root/.controlmesh/workspace/repos/my-programming-world/编程/浏览器自动化大结局：远程登录加持久化 profile 才是正解.md`
- `/root/.controlmesh/workspace/repos/my-programming-world/编程/开发指南/PLC/PLC 完整项目运行清单.md`

## Visual/Browser Findings
- No browser inspection was needed for this planning pass.
- Repo evidence was sufficient from local source and docs.

## Candidate Write Points in ControlMesh
- Normal foreground message handling in `controlmesh/orchestrator/flows.py`
- Final reply send paths after provider completion
- Explicit visible send-back helpers for files/images or task results
- Possibly API transport send surfaces if they map to user-visible chat output

## Candidate Non-Transcript Event Sources
- heartbeat observers
- background/named session lifecycle updates
- task scheduler state changes
- recovery planner actions
- provider CLI streaming/tool events
- internal multi-agent dispatch and follow-up plumbing

## Open Design Questions
1. Should `system_visible` transcript entries be allowed at all, or should all visible non-user/non-assistant outputs be normalized into assistant turns with metadata?
2. Should transcript files be partitioned by `SessionKey` only, or by a separate stable frontstage session identifier that survives provider switching?
3. How much attachment metadata is required for history replay: just file path/name, or a fully normalized outbound artifact record?
4. Which evaluation artifacts should become first-class files in the initial harness cut: scorecard only, or scorecard plus exception triggers and review outcomes?

---
This file captures current evidence and the design boundary. It should stay aligned with `task_plan.md` as the implementation plan evolves.
