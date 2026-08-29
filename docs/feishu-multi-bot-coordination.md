# Feishu Multi-Bot Coordination

Status: opt-in canary

Scope: multiple real ControlMesh Feishu bot identities in one allowlisted group

This mode lets every ControlMesh instance receive an eligible human group message while
keeping visible replies deterministic. It is disabled by default and does not change
legacy `require_mention` behavior in other groups.

## Routing Contract

| Inbound message | Local coordinator | Explicitly targeted bot | Other configured bots |
|---|---|---|---|
| Human, no configured bot @ | reply | n/a | save passive context, stay silent |
| Human, @ one configured bot | stay silent unless targeted | reply | save passive context, stay silent |
| Human, `/all ...` | reply | reply | reply |
| Configured bot, no local @ | ignore | ignore | ignore |
| Configured bot, explicit local @ | reply within loop budget | reply within loop budget | ignore |
| Unknown bot sender | ignore | ignore | ignore |

An ordinary Feishu `@all` mention is not the ControlMesh broadcast trigger. Use the exact
configured slash command (default `/all`) when independent answers are wanted.

Replies continue to use the existing `reply_mode`. For a group canary, use
`thread_isolation=true`, `reply_mode="thread"`, and `reply_to_trigger=true` so execution
state and responses stay anchored to the source thread/message.

## Canary Configuration

Install the same identity keys and coordinator policy on every CM that belongs to the
group. Set `local_bot_agent` separately on each server to the key representing that bot.
This explicit local selector is required because independent CM installations normally all
run their foreground runtime as `main`. Identity values are the bot sender/mention
`open_id` values from Feishu events, not `app_id` values. Resolve the values as observed by
each receiving app; if Feishu scopes an ID to an app, the values may legitimately differ
between server configs even though their keys stay the same.

Replace the placeholder bot and human open IDs before enabling this configuration:

```json
{
  "feishu": {
    "group_policy": "allowlist",
    "group_allow_from": ["oc_cdf6d69446db7e9e480067de4f309192"],
    "reply_to_trigger": true,
    "groups": {
      "oc_cdf6d69446db7e9e480067de4f309192": {
        "enabled": true,
        "group_policy": "allowlist",
        "group_allow_from": ["oc_cdf6d69446db7e9e480067de4f309192"],
        "allow_from_users": ["ou_REPLACE_WITH_OWNER_OPEN_ID"],
        "multi_bot_mode": true,
        "coordinator_agent": "raspberry_pi",
        "local_bot_agent": "raspberry_pi",
        "bot_identities": {
          "raspberry_pi": "ou_REPLACE_WITH_RASPBERRY_PI_BOT_OPEN_ID",
          "reviewer": "ou_REPLACE_WITH_REVIEWER_BOT_OPEN_ID"
        },
        "broadcast_command": "/all",
        "capture_passive_context": true,
        "thread_isolation": true,
        "reply_mode": "thread",
        "bot_loop_guard": {
          "enabled": true,
          "window_seconds": 60,
          "max_bot_mentions": 5,
          "scope": "chat"
        }
      }
    }
  }
}
```

On the reviewer server, keep the same `coordinator_agent`, set `local_bot_agent` to
`"reviewer"`, and substitute the bot open IDs as that app observes them. Never deploy the
same local selector to two different bot apps; both processes would believe they own the
same reply route.

`require_mention=false` and global `group_reply_all=true` are not needed. The multi-bot
router owns activation for this group. The older `agent_roster/default_agent` mechanism
routes named logical agents behind one visible Feishu bot and is deliberately bypassed
when `multi_bot_mode` is enabled.

## Passive Context

Silent configured CMs append eligible human messages to the Python-owned frontstage
transcript with source `feishu_passive_group`. Before that CM next answers an exact @ or
`/all`, up to 12 recent passive observations (bounded to 6000 characters) are prepended as
group context.

Passive capture runs only after sender and group authorization. Keep
`allow_from_users` narrow: group text becomes model context and must be treated as
untrusted input. Do not grant high-risk tools merely because a message came from an
allowlisted group; writes, outbound messages, calendar changes, and document mutations
should retain their normal confirmation boundary.

## Bot Handoff and Loop Protection

Bot-authored messages are dropped unless both conditions hold:

1. the sender open ID is present in `bot_identities`; and
2. the message explicitly mentions or replies to the local bot identity.

Allowed handoffs enter a bounded sliding window. The default permits five addressed bot
messages per chat in 60 seconds. A human message clears the chat's chain. Duplicate
message IDs do not get a second chance, and state is bounded to 5000 active keys.

The guard is deliberately in-memory: a restart clears the loop budget but normal Feishu
message deduplication and persisted outbound self-echo protection still apply. Do not use
bot-to-bot @ as an autonomous planning protocol; it is a narrow, explicit handoff seam.

## Canary Checklist

1. Start only the Raspberry Pi `main` CM with the new policy; verify a normal message gets
   one reply and appears under the original thread/message.
2. Start one non-coordinator CM; verify a normal message still gets one reply and the
   second CM logs `action=observe`.
3. @ each bot separately and verify only the selected identity replies.
4. Send `/all state your agent name` and verify one reply per configured bot.
5. Send a bot-authored message without @ and verify every CM logs a drop.
6. Exercise an explicit bot handoff past the configured threshold and verify
   `reason=bot_loop_guard`.
7. Roll back by setting `multi_bot_mode=false`; legacy mention behavior resumes without a
   transcript migration.

## Diagnostics

Every routed message emits one structured log line containing `chat_id`, `message_id`,
`local_agent`, `action`, and `reason`. Use the Feishu message ID to correlate delivery
across servers. This canary does not yet expose a user-facing cross-server diagnostic
report or durable distributed loop counter.
