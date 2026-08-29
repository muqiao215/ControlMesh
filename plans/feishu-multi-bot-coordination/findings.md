# Findings

## Baseline

- Merge baseline is current `main` at `ee8e2bf`; the downloaded patch was authored from
  `6d52099` but applies cleanly after the result-writeback/promotion work.

- Feishu already has group allowlists, mention gating, thread isolation/reply modes, and
  one-visible-bot controlled internal agent handoff.
- The existing v1 handoff deliberately excludes multiple real Feishu bot identities.
- Incoming events currently normalize only whether the local bot was mentioned; sender
  type, mention-all, and the complete mention identity set are discarded.
- Messages rejected by mention gating are deduplicated but are not retained as usable
  frontstage context.
- Frontstage transcript storage is append-only and already supports arbitrary stable
  `source` labels, making it a suitable Python-owned persistence seam for passive group
  observations.

## External reference

The official Lark Channel SDK models `senderType`, `senderIsBot`, `mentionAll`,
`mentionedBot`, reply/thread anchoring, and an opt-in sliding-window `botLoopGuard`.
This work adopts those behavioral ideas without introducing a Node runtime dependency.

## Implementation findings

- Independent CM installations normally all start their foreground stack as `main`.
  Therefore `agent_name` cannot safely identify a real bot across servers. The policy
  requires an explicit per-server `local_bot_agent` key and fails config validation if it
  is absent or unmapped.
- The existing `reply_mode="thread"` target resolver already preserves the original
  parent/root/message binding, so no new outbound mutation surface is required.
- The older `agent_roster/default_agent` path is a one-visible-bot logical handoff. It is
  bypassed in real multi-bot mode to avoid two routing owners for one message.
- Passive observations fit the existing append-only transcript model. A distinct
  `feishu_passive_group` source keeps them auditable, and only observations after the most
  recent local assistant turn are injected into the next active prompt.
- Bot open IDs may be app-scoped. Coordination keys must match across servers, while each
  server should configure peer ID values as observed by its own Feishu app.
