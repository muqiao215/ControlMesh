# Claude native continuity

Part of the full CM-R3/R6 migration; OpenCode acceptance does not close other providers.

The local CLI is Claude Code 2.1.263. Existing oneshot-command.ts deliberately disables
Claude persistence. Keep that one-shot contract; add a distinct verified native execution
profile rather than silently changing ephemeral execution or passing --continue.

First establish a provider-specific native store reader and independent History candidate.
Claude uses a project JSONL transcript, not OpenCode's SQLite tables. Version-2 identity binds
device, canonical source file identity, UUID, canonical workspace and full raw content bytes.
Partial/malformed or concurrently changed source bytes must reject continuity inspection.
Display parsers remain tolerant; executable context selection is deliberately stricter.
Only the local runtime configuration selects the native store/project path. History returns
context, no source authority, model readiness, permissions or claims of task completion.

Then implement a pinned Claude native profile, explicit --session-id/--resume identity,
closed tool/configuration environment, model preflight with the shared durable quota budget,
retained completion evidence and current-files/SpecMesh validation. Reuse the existing kernel,
process owner, task/device journals and mailbox authority; do not build a second task writer.
The native provider's permission/session history must not replace current CM-issued grants.

Acceptance requires independent Python/TS byte-protocol fixtures, real existing-source
readback, malformed/replaced/edited/foreign-session rejection, exact appended-turn lineage,
then actual current-file reads and same-session recall with model-free lost-result recovery.
Use owned controlled projects for real execution, never append to arbitrary user history.
History remains headless and stdlib-only. Native clients outside CM do not honor its locks.

## Readiness implementation

ClaudePreflight qualifies local CLI 2.1.263, creates an owned private temporary HOME/config,
uses safe mode and explicit credential environment, disables built-in tools/MCP/hooks/plugins,
and requests a single nonpersistent native sentinel turn. Native init and assistant/result
records must agree on the selected model/session; tools/MCP/plugins must be empty. Different
models, extra turns, tool content, absent completion or malformed evidence cannot mark ready.
Unknown environment keys and any unqualified host managed-configuration directory reject
instead of loading them. The accepted host has no /etc/claude-code directory.

ProviderPreflightService.ensureClaude binds the selected credential environment digest and
permission profile before shared-cache admission. Native error fields classify quota/auth;
assistant prose does not. Confirmed zoned reset dates allow bounded waiting, including fractional
seconds; a missing zone remains unknown. Three-probe budget, expiry, lost-permit uncertainty and
explicit operator retry semantics are shared with OpenCode. Host readiness does not qualify a
future container/native execution profile; the actual execution owner must bind that profile.

Actual one-model-call probe passed with the existing selected MiniMax-M3 profile. Independent
readback confirmed zero native tools/MCP/plugins, one persisted permit generation, no repeated
probe on the second check and no remaining owned temporary directories/processes. The stricter
final observer rechecked retained native output without another model. Current readiness expiry
is unchanged. Full Claude original-session execution, workspace/grant/container qualification,
mailbox/retained-turn recovery and normal local/device configuration remain required next work.
