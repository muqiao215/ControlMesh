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
