# Findings: Execution Tool Grants — Enforceability Review (Unit A pre-work)

## 0. Implementation correction (2026-09-06, discovered while coding)

- Claude's `--allowedTools` is an auto-approval rule, not a closed-world gate —
  same semantics class as gemini's deprecated flag. Hard restriction on claude
  comes from `--disallowedTools` deny rules plus permission modes. The matrix
  row "Map allow/deny directly to flags" is therefore narrowed: allow-only
  (closed-world) grants are unenforceable via claude flags and are rejected
  (`allowlist_not_enforceable_flags`); deny-based, network-tool, and read-only
  floors map. `bypassPermissions` + restrictive grant is rejected on claude and
  codex (`bypass_conflicts_grant`) because bypass cannot guarantee deny rules.
- Landed enforcement vocabulary: `restrictive` = any of tool_allow/tool_deny/
  no_network/writable_roots; floor-only grants (evidence-only) keep legacy
  behavior on every provider; `None` grant = legacy path exactly.
- Follow-ups recorded in `progress.md`: opencode per-invocation config overlay,
  gemini policy-engine config, claw/openai_agents hard-gate proof, one-shot
  cron/webhook grant wiring, golden coverage growth as surfaces are proven.

## 1. Current boundary: descriptive, not enforced

- `controlmesh/execution_policy.py:107-112` hardcodes `tool_policy="request_bound"`,
  `network_policy`, `writable_roots_policy`, `confirmation_policy` as descriptive
  strings in the admission evidence; the only real gate is sandbox availability per
  source scope (`_SANDBOX_REQUIRED_SCOPES`). No grant object exists anywhere in the
  runtime (grep: no grant/fingerprint contract in production code).
- Provider tool flags are driven by **static global config**
  (`controlmesh/cli/types.py:62-63` `allowed_tools/disallowed_tools` on the provider
  config dataclass), not by per-task authorization. Any task today inherits the
  provider's full configured surface.

## 2. Per-provider enforceability matrix (installed CLI evidence, 2026-09-06)

| Provider (installed) | Native enforcement granularity | Evidence | Grant mapping |
|---|---|---|---|
| **claude** 2.1.263 | **Tool-name allow/deny** + permission mode | `--allowedTools/--disallowedTools <tools...>`, `--permission-mode <mode>` in `claude --help`; already plumbed in `cli/claude_provider.py:81-84` | Map allow/deny directly to flags; denylist + permission-mode floor. `--dangerously-skip-permissions` is incompatible with a grant → reject that combination for restricted tasks |
| **codex** 0.153.2 | **Sandbox-mode + approval** granularity, NOT per-tool | `-s/--sandbox <MODE>`, `-a/--ask-for-approval <POLICY>`, `-c 'sandbox_permissions=[...]'` / workspace-write network toggles; plumbed in `cli/codex_provider.py:91-100` | Tool restrictions must map onto sandbox mode + approval policy (e.g. read-only tool scope → `--sandbox read-only`); restrictions that cannot be expressed are **rejected**, never prompt-only |
| **gemini** 0.43.0 | **Approval-mode** granularity; `--allowed-tools` is an auto-approval list, not a denial gate (deprecated → Policy Engine) | `--approval-mode` choices `default/auto_edit/yolo/plan` in `gemini --help`; plumbed `cli/gemini_provider.py:103-110` | Hard restriction maps to `--approval-mode plan` (read-only) or a generated policy-engine config; `--allowed-tools` alone must NOT be treated as enforcement |
| **opencode** 1.18.29 | **Config-file permission rules** (`permission: edit/bash/webfetch ask/allow/deny`) and agents; CLI surface has only `--auto` / `--dangerously-skip-permissions` | `opencode --help` flag dump; `cli/opencode_provider.py:52-55` passes only the skip flag | Per-task grants require a generated per-invocation config overlay (if the run surface accepts one) or **reject**; a whitelist in the prompt is not enforcement |
| **claw / openai_agents** | Second wave — `claw_provider.py` already has allowedTools-style plumbing (grep hit); audit at implementation time | repo grep | Same procedure: prove the flag is a hard gate before mapping |

## 3. Sandbox is the floor, grants narrow within it

- Group/bot-handoff/API/cron/webhook/heartbeat scopes already fail closed without a
  confirmed Docker sandbox (`execution_policy.py:15-24`); for those sources the
  container network default and configured mounts are the enforced floor, and a grant
  may only narrow.
- Trusted-host scopes (local foreground, direct message) have no sandbox floor, so
  provider-native flags are the only enforcement — unmappable restrictions must be
  rejected for those sources too, not degraded to descriptive fields.

## 4. Existing persistence + recovery channel (reuse, do not invent)

- `ExecutionContext` is issued only by trusted runtime code (`bus/envelope.py:66-98`),
  carried via contextvar (`bind_execution_context`), persisted on the task record
  (`tasks/models.py:104,166,223-224,288-290` round-trip), and restored on
  resume/recovery and one-shot execution (`tasks/hub.py:633,770,1004,1371`,
  `infra/task_runner.py:52`, `infra/base_task_observer.py:56` — unknown/legacy falls
  back to `ExecutionContext.legacy()`).
- Recovery already restores provenance across episodes; a grant should ride the same
  task-record channel as a **separate additive optional field**, not inside
  `ExecutionContext` (provenance and authorization are different authorities).

## 5. Minimal persistence & recovery contract (design for Unit A implementation)

1. **Grant object**: frozen `ToolGrantSnapshot` — `schema_version`, `tool_allow`,
   `tool_deny` (tuples, provider-token normalized at issue time), `network_policy`,
   `writable_roots` (bounded, no secrets), `confirmation_policy`,
   `provider_surface` ∈ {`claude_tool_flags`, `codex_sandbox`, `gemini_policy`,
   `opencode_config`, `reject`}, plus the reply-target identity copied from the
   envelope (transport/chat/topic/thread) — no new target model.
2. **Issuance**: trusted Python ingress only (same authority as
   `ExecutionContext.issue`), derived from the request plus the policy floor;
   persisted once at submit on the task record as additive optional JSON with strict
   version parsing. Missing grant on old records = fail-closed baseline
   (unrestricted-config behavior preserved), never auto-elevated.
3. **Enforcement point**: each provider adapter maps the snapshot to its native
   surface **at process construction, before launch**; unmappable restriction →
   typed pre-launch rejection (pattern: `ExecutionPolicyDenied`), regardless of
   source scope. Static config and grant intersect (union of denies, intersection
   of allows); a grant never widens static config.
4. **Recovery/rebind**: on resume/recovery the owner verifies the lineage
   (same task, current episode) and rebinds the snapshot verbatim to the new
   episode — no expansion, no reuse of a previous episode's grant object as proof;
   if the current provider/adapter cannot honor it, the episode fails closed.
5. **Rollback**: additive field is ignored by old readers (compat verified); a
   rollback that would make a grant-ignoring executor run restricted tasks must
   quarantine those tasks first (recorded in the task record).
6. **Verification path**: production enforcement first, then a normalized golden
   fixture + drift gate reusing the provenance/writeback runner pattern; seven
   acceptance groups from the weekly-report plan (cross-provider, recovery
   consistency, tamper, cross-task/episode replay, over-privilege request, no
   secret serialization, old-record compat) plus per-provider mapping cases.
