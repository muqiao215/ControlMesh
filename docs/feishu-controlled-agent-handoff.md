# Feishu Controlled Agent Handoff

Status: v1 implementation design  
Baseline: ControlMesh `v0.40.3`  
Scope: Feishu group chat routing only

## Product Boundary

V1 supports:

- explicit user selection of a named agent in a Feishu group
- one-hop controlled handoff through the existing ControlMesh multi-agent bus
- delivery of the selected agent result back to the original Feishu group and reply/thread target

V1 does not support:

- multi-hop autonomous handoff
- free bot-to-bot group chat
- multiple real Feishu bot identities automatically conversing in one group

## Configuration

Per-group policy lives under `feishu.groups.{chat_id}`:

```json
{
  "feishu": {
    "groups": {
      "oc_group": {
        "agent_roster": ["main", "coder", "reviewer"],
        "default_agent": "main",
        "allow_interagent_handoff": true,
        "max_handoff_depth": 1
      }
    }
  }
}
```

The roster is an allowlist. A group message can only route to a target listed in
that group's roster. `max_handoff_depth` is clamped by the runtime to the v1
maximum of one delegated hop.

## Routing Rules

The Feishu bot remains the only visible Feishu identity for v1.

For group messages, `controlmesh/messenger/feishu/bot.py` resolves routing
after the existing sender/group/trigger/dedup gates and before the normal main
agent streaming turn.

Explicit target syntaxes:

- `@coder implement this`
- `agent:coder implement this`
- `agent=coder implement this`
- `@agent:coder implement this`

If the target is not in the group roster, the message falls back to the normal
main-agent path. If the target is the current Feishu bot's own agent name, the
message also stays local.

When `default_agent` is configured and is not the current agent, unqualified
group messages route to that default agent.

## Handoff Envelope

The target agent receives a normal inter-agent message with a Feishu handoff
envelope:

```text
[Feishu controlled group handoff]
source_agent=main
target_agent=coder
chat_id=oc_group
thread_id=omt_thread
reply_target=original_feishu_group_thread
handoff_allowed=true
remaining_handoff_depth=0
...
[/Feishu controlled group handoff]
```

This is intentionally an instruction boundary, not a free-form group chat
protocol. In v1 the Feishu entry agent has already consumed the one allowed
handoff when it delegates to the selected roster agent, so the receiving agent
must answer the request and return the result to the source agent.

## Safety Controls

- Group routing is opt-in through per-group `agent_roster`.
- All normal Feishu group policy, mention/reply trigger, sender allowlist,
  content deduplication, and outbound self-echo controls still run first.
- The source Feishu bot formats returned text as `[agent]` plus the result, so
  the visible group has one Feishu bot identity with labeled agent output.
- The runtime does not open autonomous bot-to-bot conversation loops.

## Test Surface

Focused tests cover:

- config parsing for snake_case and camelCase policy fields
- explicit group `@agent` routing through the multi-agent bus
- default-agent routing with handoff disabled
- unknown agent fallback to the normal main-agent streaming path
