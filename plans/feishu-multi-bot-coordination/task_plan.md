# Feishu Multi-Bot Coordination Canary

## Goal

Add an opt-in Feishu group policy for multiple real ControlMesh bot identities in one
group: all instances may retain passive context, while coordinator, exact mention, and
explicit `/all` rules determine which instances answer.

## Constraints

- Preserve legacy Feishu behavior unless a group enables `multi_bot_mode`.
- Keep Python ownership of transport routing and transcript persistence.
- Do not add free autonomous bot-to-bot conversation.
- Bot-authored messages are accepted only from configured peer identities and only when
  they explicitly mention the local bot.
- Keep replies anchored to the triggering message/thread through the existing Feishu
  reply policy.

## Plan

- [x] Normalize sender type, mention-all, and mentioned open IDs from Feishu events.
- [x] Add typed per-group multi-bot policy and a bounded sliding-window loop guard.
- [x] Route human messages as coordinator, exact target, `/all`, or passive observation.
- [x] Persist passive observations in the frontstage transcript and inject recent unseen
   passive group context into the next active local turn.
- [x] Add focused config, normalization, routing, context, bot-message, loop, and thread
  tests.
- [x] Update durable Feishu configuration/architecture documentation and verify regressions.

## Acceptance

- Ordinary human message: coordinator answers; non-coordinators record without answering.
- Exact configured bot mention: only the mentioned bot answers.
- `/all`: every enabled bot answers.
- Bot message without a local explicit mention is ignored.
- Configured peer bot with a local explicit mention may hand off until the loop guard trips.
- Replies retain the existing message/thread target.
- Legacy groups remain unchanged.
