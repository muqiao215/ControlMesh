# Feishu Group Chat Design

Status: executable design draft  
Scope: ControlMesh Feishu transport only  
Primary target: `controlmesh/messenger/feishu/`  
Baseline: `v0.33.x` Feishu runtime and tests

## Goal

Extend the current Feishu transport from a mostly direct-message-oriented bot
into a controlled group-chat transport with explicit policy, trigger, session,
reply, and test contracts.

This document is intentionally implementation-oriented. It is not a product
overview. Every section below is anchored to the current ControlMesh codebase
and is meant to be used as the source of truth for follow-up patches.

## Current Baseline

Current Feishu runtime anchors:

- config surface:
  [`controlmesh/config.py`](/root/.controlmesh/dev/ControlMesh/controlmesh/config.py:180)
- inbound routing and session entry:
  [`controlmesh/messenger/feishu/bot.py`](/root/.controlmesh/dev/ControlMesh/controlmesh/messenger/feishu/bot.py:440)
- inbound message context shaping:
  [`controlmesh/messenger/feishu/message_context.py`](/root/.controlmesh/dev/ControlMesh/controlmesh/messenger/feishu/message_context.py:73)
- restart-safe dedupe and self-echo continuity:
  [`controlmesh/messenger/feishu/runtime_state.py`](/root/.controlmesh/dev/ControlMesh/controlmesh/messenger/feishu/runtime_state.py:1)
- current Feishu behavior tests:
  [`tests/messenger/feishu/test_bot.py`](/root/.controlmesh/dev/ControlMesh/tests/messenger/feishu/test_bot.py:1)

The current runtime already supports:

- inbound Feishu message parsing
- text/post/interactive content extraction
- optional `thread_isolation`
- persisted inbound/content/outbound replay stores
- reply-to-trigger behavior
- minimal group gating fields

What it still lacks is a complete and explicit group policy model.

## Non-Goals

This design does not include:

- tenant-wide admin approval workflows
- auto-provisioning groups from the Feishu Open Platform
- a full in-chat group policy UI
- CardKit-only group interaction mode
- cross-transport shared group-policy abstraction

Those can be added later. This design is limited to making Feishu group chat
predictable, safe, and testable.

## Product Model

Treat Feishu as three distinct ingress modes:

1. direct chat
2. group chat main timeline
3. group thread / reply chain

The runtime must not collapse them into one generic `chat_id` stream.

The design rule is:

- DM policy decides whether a direct sender may talk to the bot
- group policy decides whether a group may host the bot
- trigger policy decides whether one group message is actionable
- session policy decides where that actionable message lands
- reply policy decides how the bot talks back into the group

## Configuration Contract

### Existing fields

Already present in [`FeishuConfig`](/root/.controlmesh/dev/ControlMesh/controlmesh/config.py:180):

- `allow_from`
- `group_allow_from`
- `dm_policy`
- `group_policy`
- `require_mention_in_group`
- `group_reply_all`
- `thread_isolation`
- `reply_to_trigger`

### Recommended stable config shape

Use this as the target shape for the next implementation wave:

```json
{
  "feishu": {
    "mode": "bot_only",
    "runtime_mode": "native",
    "brand": "feishu",
    "app_id": "cli_xxx",
    "app_secret": "sec_xxx",
    "domain": "https://open.feishu.cn",

    "allow_from": ["ou_owner"],
    "group_allow_from": ["oc_group_alpha"],

    "dm_policy": "allowlist",
    "group_policy": "allowlist",
    "require_mention_in_group": true,

    "thread_isolation": true,
    "reply_to_trigger": true,
    "group_reply_mode": "reply",

    "groups": {
      "oc_group_alpha": {
        "enabled": true,
        "require_mention": false,
        "thread_isolation": true,
        "reply_mode": "thread",
        "allow_from_users": ["ou_owner", "ou_admin"]
      }
    }
  }
}
```

### Field definitions

#### `allow_from`

Type:

- `list[str]`

Meaning:

- sender allowlist
- applies to DMs
- may also apply inside groups when no group-specific user override exists

#### `group_allow_from`

Type:

- `list[str]`

Meaning:

- group `chat_id` allowlist
- only meaningful when `group_policy="allowlist"`

#### `dm_policy`

Allowed values:

- `allow`
- `allowlist`
- `disabled`

Meaning:

- `allow`: any direct sender may trigger the bot
- `allowlist`: only `allow_from` senders may trigger the bot
- `disabled`: DM ingress is rejected

#### `group_policy`

Allowed values:

- `disabled`
- `allowlist`
- `open`

Meaning:

- `disabled`: all group messages are ignored
- `allowlist`: only `group_allow_from` groups are eligible
- `open`: any Feishu group may host the bot

#### `require_mention_in_group`

Type:

- `bool`

Meaning:

- if `true`, an eligible group message must explicitly mention the bot
- if `false`, any eligible group message may trigger the bot

#### `group_reply_all`

Current meaning:

- compatibility escape hatch
- when `true`, bypass explicit group trigger requirements

Design note:

- keep it for backward compatibility in the near term
- deprecate it after `group_reply_mode` and per-group overrides exist

#### `thread_isolation`

Type:

- `bool`

Meaning:

- if `true`, group threads/reply chains become distinct session topics
- if `false`, the entire group shares one session

#### `reply_to_trigger`

Type:

- `bool`

Meaning:

- if `true`, the bot replies under the trigger message when the channel API
  supports it
- if `false`, replies are posted without reply linkage

### New fields to add in the next patch

#### `group_reply_mode`

Allowed values:

- `reply`
- `thread`
- `inline`

Meaning:

- `reply`: reply to the source message
- `thread`: continue in the thread/root chain if available
- `inline`: send a plain group message without reply binding

#### `groups`

Type:

- `dict[str, FeishuGroupPolicy]`

Meaning:

- per-group override table keyed by Feishu `chat_id`

Recommended child fields:

- `enabled`
- `require_mention`
- `thread_isolation`
- `reply_mode`
- `allow_from_users`

## Trigger Rules

### DM trigger rules

Decision table:

1. if `dm_policy="disabled"` -> reject
2. if `dm_policy="allow"` -> accept
3. if `dm_policy="allowlist"` -> require `sender_id in allow_from`

### Group trigger rules

A group message is actionable only if all of the following pass:

1. the message is explicitly identified as group chat
2. group policy allows the group
3. sender policy allows the sender
4. the message passes trigger gating

### Group trigger gating

Default rule:

1. if `group_reply_all=true` -> accept
2. else if per-group override says `require_mention=false` -> accept
3. else if global `require_mention_in_group=false` -> accept
4. else require one of:
   - bot mention
   - reply-to-bot message
   - explicit future command exception

### Mention detection

The runtime should treat the following as mention triggers:

1. direct mention of the bot `open_id`
2. reply to a previously-sent bot message
3. optional future support for `@all` if product wants that behavior

Current implementation only handles mention list inspection in
[`_message_mentions_bot()`](/root/.controlmesh/dev/ControlMesh/controlmesh/messenger/feishu/bot.py:2058).

The next implementation wave should add:

- reply-to-bot detection from message lineage or quoted metadata
- optional command bypass for `/help`, `/status`, `/settings`, `/cm`

### Explicit rule about reply-to-bot

A reply to the bot should count as an explicit trigger even when the user does
not mention the bot again.

Reason:

- it matches user expectation in high-traffic groups
- it reduces unnecessary `@bot` noise
- it aligns with the existing `reply_to_trigger` mental model

## Session Key Rules

This is the most important runtime rule.

Do not use only `chat_id` as the session key for group chat.

### Current baseline

Current session entry:

- `chat_id = self._id_map.chat_to_int(message.chat_id)`
- `topic_id = self._id_map.thread_to_int(message.thread_id) if thread isolation`

Source:

- [`handle_incoming_text()`](/root/.controlmesh/dev/ControlMesh/controlmesh/messenger/feishu/bot.py:443)

### Required session-routing rule

If `thread_isolation=false`:

- session key = `SessionKey.for_transport("fs", chat_id, None)`

If `thread_isolation=true`:

- session key = `SessionKey.for_transport("fs", chat_id, topic_id)`
- where `topic_id` is derived from the best session anchor

### Session anchor precedence

Use this order:

1. `thread_id`
2. `root_id`
3. `parent_id`
4. `message_id` only if product explicitly chooses per-message isolation

The runtime should never infer thread boundaries from free text.

### Why this precedence

- `thread_id` is the strongest native conversation boundary
- `root_id` preserves reply-chain continuity even when explicit thread fields
  vary
- `parent_id` is a weaker fallback
- `message_id` is too granular for default use

### Dedupe key alignment

The dedupe and replay keys must use the same conversational boundary as the
session router.

Current content dedupe key:

- [`_content_dedup_key()`](/root/.controlmesh/dev/ControlMesh/controlmesh/messenger/feishu/bot.py:1234)

Rule:

- content dedupe key must include the same anchor used by session routing
- two identical messages in different group threads must not suppress each other

## Reply Strategy

### Goal

Reply behavior must be predictable in group space and must not flood the main
timeline unnecessarily.

### Recommended modes

#### `reply`

Behavior:

- reply to the trigger message

Use when:

- default group mode
- medium traffic groups
- users expect local conversational attachment

#### `thread`

Behavior:

- continue inside the thread/root chain when Feishu exposes it

Use when:

- the group uses threaded discussions
- multiple simultaneous conversations are expected

#### `inline`

Behavior:

- post a plain message to the group without reply binding

Use when:

- the target group is low traffic
- the product explicitly prefers broad visibility

### Default recommendation

Default group reply mode should be:

- `reply`

Reason:

- safer than `inline`
- simpler than fully forcing thread mode
- matches current `reply_to_trigger` behavior

### Current implementation boundary

Today, Feishu replies are mostly controlled by:

- `reply_to_trigger`
- outbound `reply_to_message_id`

This is enough for `reply` mode.

What still needs implementation later:

- explicit `group_reply_mode`
- thread-first reply routing when root/thread metadata exists

## Runtime State and Stability Rules

### Persisted stores that must stay group-aware

Current persisted state:

- `recent_inbound`
- `recent_content`
- `recent_outbound`

Source:

- [`runtime_state.py`](/root/.controlmesh/dev/ControlMesh/controlmesh/messenger/feishu/runtime_state.py:1)

### Required invariants

1. self-echo suppression must survive restart
2. duplicate delivery in one group thread must not reopen the same work
3. same text in different threads must not be treated as the same turn
4. stale persisted state must be discarded when app identity changes

### Persisted key guidance

Inbound:

- key = `chat_id:message_id`

Content:

- key = `chat_id:sender_id:session_anchor:normalized_text`

Outbound:

- key = `chat_id:message_id`

This is already directionally true in the current code and should remain the
contract.

## Implementation Plan

This section is intentionally phaseable.

### Phase 1: baseline group policy

Files:

- `controlmesh/config.py`
- `controlmesh/messenger/feishu/bot.py`
- `tests/messenger/feishu/test_bot.py`
- `tests/test_config.py`

Deliver:

- `group_allow_from`
- `dm_policy`
- `group_policy`
- `require_mention_in_group`
- explicit group-only trigger gating
- thread-isolated session routing verification

Acceptance:

- group not in allowlist is rejected
- group without mention is rejected by default
- mentioned group message is accepted
- different threads route to different topics when isolation is on

### Phase 2: reply-to-bot trigger parity

Files:

- `controlmesh/messenger/feishu/bot.py`
- `controlmesh/messenger/feishu/message_context.py`
- Feishu tests under `tests/messenger/feishu/`

Deliver:

- reply-to-bot counts as actionable group trigger
- quoted/replied lineage is parsed into the trigger decision

Acceptance:

- group reply to bot triggers without explicit re-mention
- unrelated quoted content does not accidentally trigger

### Phase 3: reply mode contract

Files:

- `controlmesh/config.py`
- `controlmesh/messenger/feishu/bot.py`
- `controlmesh/messenger/feishu/sender.py`
- tests

Deliver:

- `group_reply_mode`
- runtime support for `reply | thread | inline`

Acceptance:

- each mode routes reply linkage as specified
- group defaults remain backward compatible

### Phase 4: per-group override table

Files:

- `controlmesh/config.py`
- `controlmesh/messenger/feishu/bot.py`
- settings/UI follow-up only if needed

Deliver:

- `groups.{chat_id}` override contract

Acceptance:

- one group can require mention while another does not
- one group can isolate threads while another shares one session
- one group can narrow sender allowlist independently

## Test Matrix

The following tests should exist before calling the feature complete.

### Config tests

- accepts `group_allow_from`
- accepts `dm_policy`
- accepts `group_policy`
- accepts `require_mention_in_group`
- rejects invalid enum values

### Inbound parsing tests

- normalizes `chat_type`
- detects mention of bot open_id
- preserves `thread_id`, `root_id`, `parent_id`
- preserves quote summary for trigger-adjacent flows

### Group policy tests

- group rejected when `group_policy=disabled`
- group rejected when allowlist misses
- group accepted when allowlist hits
- direct chat rejected when `dm_policy=disabled`
- direct chat gated by `allow_from` when `dm_policy=allowlist`

### Trigger tests

- group mention triggers
- group message without mention is rejected by default
- `require_mention_in_group=false` allows plain group messages
- `group_reply_all=true` bypasses mention gating
- future: reply-to-bot triggers without explicit mention

### Session-routing tests

- `thread_isolation=false` keeps same `topic_id=None`
- `thread_isolation=true` creates distinct `topic_id` values per thread
- same group, different thread does not share topic
- same thread, repeated messages reuse the same topic

### Dedupe and stability tests

- same content in same thread dedupes
- same content in different threads does not dedupe
- persisted self-echo suppression survives restart
- stale identity fingerprint clears replay state

### Reply behavior tests

- `reply_to_trigger=true` replies under the source message
- `reply_to_trigger=false` sends without reply binding
- future `group_reply_mode=thread` continues in thread path
- future `group_reply_mode=inline` posts without reply linkage

## Open Questions

These are the only unresolved design choices that should be decided before
Phase 3 or Phase 4, not before Phase 1:

1. Should `@all` count as an actionable bot trigger?
2. Should slash commands bypass mention requirements in groups?
3. Should per-group sender allowlists inherit from `allow_from` or replace it?
4. Should the settings card expose group policy, or should it stay config-only?

## Recommended Next Step

Use this document as the implementation source of truth and execute in this
order:

1. Phase 1
2. Phase 2
3. Phase 3
4. Phase 4

Do not start with per-group UI or CardKit flows. The runtime contract is the
hard part and should be frozen first.
