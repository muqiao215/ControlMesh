# Persistent local TypeScript control

Status: implemented candidate; full verification/release status is in [progress](progress.md).
This is the existing TS runtime's local process entry, not a Python bridge or a new task store.
Interactive terminal product acceptance and the production default switch remain separate.

## Start and reconnect

Use an already qualified private `controlmesh.local_runtime.v1` profile. The existing
Python `~/.controlmesh/config.json` is not this format. The selected profile fixes provider,
workspace, source, grants, native history and optional SpecMesh/delivery bindings; a caller
cannot override them in a socket packet. Configuration replacement revokes admission.

Run from the ControlMesh checkout with the pinned Bun/pnpm toolchain:

```bash
install -d -m 700 "/run/user/$(id -u)/controlmesh"
CM_SOCKET="/run/user/$(id -u)/controlmesh/runtime.sock"
pnpm runtime --socket "$CM_SOCKET" serve --config /absolute/private/profile.json
```

`serve` stays in the foreground as a service process and prints one readiness record. Its
stdin can be closed; closing a client terminal does not stop the service. An existing process
supervisor can own this foreground command, but this checkpoint installs no systemd unit,
cron or startup hook and does not replace the installed Python `cm`.

In another terminal, use the same socket:

```bash
pnpm runtime --socket "$CM_SOCKET" status
pnpm runtime --socket "$CM_SOCKET" tasks
pnpm runtime --socket "$CM_SOCKET" new task-1 --prompt-file /absolute/request.md
pnpm runtime --socket "$CM_SOCKET" enqueue task-1 --revision 1
pnpm runtime --socket "$CM_SOCKET" inspect task-1
pnpm runtime --socket "$CM_SOCKET" events task-1
```

`status` exposes a copy of the registered project, Provider/model names, registered write
roots and integration presence. It omits credentials, environment values and native storage
paths. Registration is not a readiness/quota report; execution still performs preflight.
`new` reads this current registration, uses its project/model, and requires `--provider NAME`
when more than one Provider is registered. Explicit `--model` or `--project` must match the
selected registration. Unknown overrides fail before task creation. Configuration changes
still revoke the service's authority; this read does not issue a grant or permit.

Creation does not enqueue implicitly. Once explicitly queued, work runs in the service and
the submitting client may exit. Inspect the current revision before `resume` or `cancel`;
both require `--revision N`. Resume preserves the original task/native binding and returns
a new waiting revision; enqueue that revision explicitly. `tell` delivers a follow-up via
the existing mailbox. None of these commands reinterpret an unknown outcome as a retry.

Task lists show status, configured provider/model and the latest queue outcome or task title.
`--after ID --limit N` provides bounded local-principal pages. Explicit task/event reads use
the kernel's existing read/admin authorization. `events TASK --after N` preserves event
sequence and origin: creation, authorization, schedule and recovery remain distinct events.
Human output neutralizes terminal controls; `--json` preserves data through escaped JSON.
For machine parsing through pnpm, use `pnpm --silent runtime --socket "$CM_SOCKET" --json ...`
so pnpm's own script banner does not precede the JSON response. Direct Bun/`cm-runtime`
invocation produces only the command response.

## Agent and advanced commands

`request --file /absolute/request.json` forwards an existing private control operation.
The file can retain its explicit `id`; conflicting `--request-id` is rejected. Existing
history search/adoption, SpecMesh handoff/verification, reconciliation and topology controls
continue through LocalRuntimeControl. There is no generic shell or arbitrary filesystem API.

Each connection is independent and requests may overlap. A long `drain` cannot block another
connection's `cancel`. Frames are bounded to 64 KiB; responses to 8 MiB; pending commands to
128, connections to 32 and in-flight requests per connection to eight. Malformed UTF-8/JSON
and excess input do not become a prompt. The command-line client sends once, with no retry.

A timeout after sending reports `local_control_response_unknown` and the request ID. The
operation may still be running or have committed. Inspect the original task/run or retry
the identical idempotent operation with its original ID and unchanged body; do not create
a fresh task to guess the outcome. Native uncertainty still uses explicit retained-result
reconciliation. A client disconnect cancels only that connection's reply.

## Ownership and restart

The Linux Unix socket lives in a real, owner-only directory; the socket is mode 0600. This
is a trusted local-user control surface with the profile's authority, not a public Web API.
Do not expose/forward the socket or its containing directory to untrusted Agent sandboxes.
Socket path length must be below 104 bytes. Other platforms are unqualified.

An inherited-descriptor `flock` is acquired before opening a profile that might auto-start
work. A second listener cannot silently remove the first one's socket. SIGKILL releases the
OS lock; a new owner removes a leftover socket only after an authoritative connection refusal
and an unchanged inode check. Bun 1.3.11 reports ENOENT for the verified orphaned-socket case;
both ENOENT and ECONNREFUSED require those checks. A timeout or permission failure does not.
Lock files remain in place; their mere existence is not evidence of a running service.

Clean shutdown stops only this runtime's owned execution, drains outstanding control
operations, closes the listener and removes only its own unchanged socket. SQLite queue,
events, receipts and native recovery records persist. Restart processes queued work through
the existing lease/fence owner; canceled, completed, blocked and uncertain attempts are not
automatically turned into new native inputs. No production data migration occurs here.

## Verification boundary

Tests use actual process startup, independent CLI clients, Unix sockets, OS file locks,
SQLite and SIGKILL/restart. A configured Docker test uses the actual file broker, native
verifier, queue and staged publication, with a synthetic Claude process: two turns preserve
the original session after service restart and read the changed project file. This is
service integration evidence, not new real-model memory or physical multi-device acceptance.

The full goal still includes remaining provider/transport/store owners, terminal editing and
rendering, initial workspace distribution, real complex continuation, physical end-to-end
acceptance, reviewed SpecMesh closeout, packaging, release/install and the staged default switch.

## Interactive client prototype

`pnpm runtime --socket "$CM_SOCKET" ui` opens the Bun/OpenTUI client in a TTY. It does
not start a second service. Plain text in new-task mode submits and then enqueues only
the acknowledged revision. `/open TASK` selects existing work; `/resume TEXT` registers
a new round and `/enqueue` explicitly executes it. `/tell TEXT` uses the task mailbox.
`/events` preserves the event view during polling. `/model PROVIDER` chooses among the
registered providers for new work only; it does not change an existing native session.

On an unacknowledged mutation, the client retains the exact packet in memory and blocks
new mutations. `/retry` explicitly resends that same ID/body through runtime idempotency;
it never creates a fresh task or automatically enqueues a follow-on step. Read commands
remain available. The request ID is displayed; retained packets and drafts are currently
process-local, so client restart does not restore them. `/quit` detaches without stopping
the service. This remains an interactive prototype: full terminal-product gates, native
borrowing, real-model acceptance and installed-entry cutover are pending.

Task pages in the interactive client support `/more`; refresh keeps the current page.
Event view advances the service sequence cursor on each refresh, showing at most 200
records in memory and disclosing dropped display records. `/events` restarts history
reading; `/more` catches up another bounded batch. These are lifecycle events, not
live provider-token output.

### Native history in the terminal

`/history claude QUERY` searches the configured headless History catalog.
`/refresh-history claude` explicitly refreshes that catalog; polling/search does not
schedule refresh or execute a model. `/adopt claude SESSION_ID` prepares a task-bound
context handle and shows it without submitting a task. The next plain-text input becomes
the new task prompt; original historical messages are not resubmitted. `/new` discards
the selection. Model changes are refused while a prepared context is selected.

The local runtime history ports support explicitly registered Claude and OpenCode providers.
OpenCode searches its registered SQLite source directly; `/refresh-history opencode` returns
`native_history_refresh_unsupported` because that source needs no derived-cache refresh.
Other provider names remain unqualified. Provider-native
execution still uses the existing registry/baseline checks and enqueue preflight. Terminal
integration tests do not establish real-model memory recall.

### Agent-facing continuity commands

The noninteractive CLI exposes `history-search --provider NAME [--query TEXT]`,
`history-refresh --provider NAME`, `prepare-adoption TASK --provider NAME --session ID`,
`handoff TASK`, and `verify TASK`. Use `--json` and a stable `--request-id` for scripted
steps. `prepare-adoption` returns context only; pass its `result.native_session` JSON as
`new TASK --provider NAME --adoption JSON --prompt TEXT`. The handle is bound to the
prepared task/provider/model/workspace and is revalidated by the runtime. Raw native
references are not accepted by this flag. Use subprocess argument arrays rather than
constructing shell command strings from returned JSON. Creation does not enqueue.

`handoff` and `verify` exit 1 when `gate_passed` is not true, even if the socket operation
completed successfully. Inspect the JSON gate result for details; a transport success
alone does not authorize continuation or prove reviewed closeout. No command loads the
interactive renderer or depends on the Web UI.
