# Runtime convergence progress

## Current

Full TS migration, multi-device coordination and real Agent continuity remain **in
progress**. No production writer cutover, complete release or default TS installation
has been accepted. Last directly checked local `cm --version`: **0.43.0**, Python.
The last pushed baseline is **7a1f16f** (durable text webhook ingress). Current changes add
schema 37 Telegram polling, persisted batch/offset ownership and bounded failure handling;
this remains a scoped transport port, not production cutover.

This file is the current handoff, not a chronological commit log. Historical detail
through this consolidation remains in Git at `3a56eed`; deeper native observations and
corrections remain in [findings.md](findings.md). Earlier claims that Gemini lacks a task
adapter, that host execution cannot survive management loss, or that public Gemini accepts
`--ignore-env` are superseded by the implementation/evidence below.

## Done — scoped implementation

| Area | Current implementation | Evidence and limits |
|---|---|---|
| Kernel and local runtime | Transactional tasks/episodes/effects, fencing, cancellation, deadlines, durable local queue, private service/CLI | Broad runtime regression plus scoped differential/fault tests; production Python ownership remains |
| State compatibility | Snapshot preview/import/export, preserved unknown fields and uncertain imported active tasks; incremental schema migrations | Synthetic/differential tests; full live migration, rollback and cutover remain |
| Host work | Normal workunit routing, explicit step/plan approval, automatic confirmed-step advancement, environment binding, streamed retained logs, bounded renewable lease | Actual supervised commands and failure/reopen tests; additional source/environment/deployment parity remains |
| Detached host owner | Independent worker owns supervision and renewal; management SIGKILL does not stop it; approved subsequent steps can advance offline | Management loss, cancellation after reconnect, owner death and no-repeat launch faults tested; not all deployment/crash windows |
| Native OpenCode/Claude | Native session identity and current authorization, local/device execution and retained reconciliation, registered file/mailbox paths | Scoped prior real x64/ARM64 canaries and current test matrix; not universal provider/profile acceptance |
| Native Codex | Registered local resume, preflight, Viewer adoption, workspace/SpecMesh receipts and topology/mailbox integration | Installed CLI with loopback model fixtures covers selected flows; real accounts, physical devices and remaining branches differ |
| Gemini | Registered local text continuation, native JSONL/stream verification, process supervisor, durable task results/recovery, persistent readiness cache | Configured fixture and installed loader/parser tests pass; actual OAuth account is rejected by server; tools/Viewer/device paths remain |
| Coordination | Device identity/leases/fences, durable mailbox, explicit topology scheduling and native task context | Scoped real-device and local native-fixture evidence; full cross-device/provider/partition/rollout matrix remains |
| Telegram | Selected bot delivery, ordered multipart/ack recovery, text webhook/polling, durable topic conversations and normal queue | Local HTTP/reopen/SIGKILL/configuration tests; media/callback/edit updates, formatting, streaming, outbound rate limits and production acceptance remain |
| Integrations | Headless History ports and independent SpecMesh lifecycle are used by qualified provider paths | SpecMesh check does not imply reviewed closeout; supported providers/receipt profiles differ |

### Gemini actual-account findings

The installed public 0.59 entry parser rejected `--ignore-env`; this was a CM implementation
error caused by assuming an internal loader option was public. `3a56eed` removes it from
probe/resume commands and requires merged `advanced.ignoreLocalEnv=true` in joined native
policy admission. The installed public parser now has a regression test.

A bounded canary used an isolated temporary HOME/workspace and copied OAuth files. After
fixing argv, native OAuth refresh changed the copied credential identity and admission
stopped. One requalification of that refreshed copy received native
`IneligibleTierError`, `reasonCode: UNSUPPORTED_CLIENT`, empty stdout and exit 55. The
server rejected this client for Gemini Code Assist for individuals. This is **not quota
exhaustion**, and no real model continuation was proven. Identical probes stopped.
Temporary login copies were deleted; operator authentication files were not write targets.
Private diagnostic evidence: `/tmp/cm-gemini-account-BNTF1Q` (ephemeral, not release assets).

## Verification

- **Schema 37 full regression:** 1038 pass, 34 optional skips, 0 fail; 12,231 assertions,
  1,072 tests / 122 files, 393.03s, exit 0. Docker and standalone SpecMesh enabled;
  `/tmp/cm-runtime-telegram-polling-full.log`. This precedes final retry-delay hardening.
- **Final polling/ingress/configuration regression:** 57 pass, 0 fail, 461 assertions,
  3.72s; `/tmp/cm-telegram-polling-final.log`. Includes explicit 429 classification and
  safe timestamp handling after excessive retry-after. Typecheck/diff check passed.
- GitHub CI for `7a1f16f146dfef8f5bd4b69f308ac7c1030c8ee0` succeeded (34742516529).
  Remote CI for the current polling change has not yet been verified.

- **Schema 36 full regression:** 1025 pass, 34 optional skips, 0 fail; 12,078 assertions,
  1,059 tests / 121 files, 392.57s, exit 0. Docker and standalone SpecMesh enabled;
  `/tmp/cm-runtime-telegram-inbox-full.log`. This precedes the final input-byte-limit fix.
- **Final webhook/transport/configuration regression after Unicode input fix:** 77 pass,
  0 fail, 549 assertions across four files, 4.67s; `/tmp/cm-telegram-inbox-final.log`.
  Typecheck and diff check passed. No live Telegram or provider account was used.
- GitHub CI for `ed3c37c3cb73aa5294ecea030499ebc68b360de4` succeeded (34741735872).
  Remote CI for the current ingress change has not yet been verified.

- **Multipart targeted regression:** 60 pass, 0 fail, 509 assertions, 3.24s;
  `/tmp/cm-telegram-multipart-tests.log`.
- **Schema 35 full regression:** 1010 pass, 34 optional skips, 0 fail, 12,000 assertions;
  1,044 tests / 120 files, 391.72s, exit 0. Docker and standalone SpecMesh enabled.
  `/tmp/cm-runtime-telegram-multipart-full.log`. Typecheck and diff check passed.
- GitHub CI for `62f35d6ee21c71a1bbfe16568b71203b78d8738c` succeeded (34741123956);
  remote CI for the current multipart change is not yet verified.

- **Schema 34 / Telegram recovery full regression:** 1002 pass, 34 optional skips, 0 fail;
  11,923 assertions / 1,036 tests / 120 files, 390.56s, exit 0.
  `/tmp/cm-runtime-telegram-recovery-full.log`; Docker and standalone SpecMesh enabled.
  Includes retained-ack recovery, cross-chat message IDs and migration corruption rollback.
  Typecheck and diff check passed. Optional native/account profiles remain unaccepted.
- GitHub CI for pushed baseline `90c43487e13ff0a6ed2c56ab6122f3232db2a73f` succeeded
  (run 34740647662). This does not establish remote CI for the current change.

- **Telegram and existing delivery regression:** 48 pass, 0 fail, 396 assertions, 2.49s;
  `/tmp/cm-telegram-delivery-tests.log`. Includes normal configuration, private credential
  rotation, wrong replies, API rejection, lost response and failed acceptance/reopen.
  Typecheck and diff check passed. No real Telegram message was sent.

- **Latest focused regression at 3a56eed:** 43 pass, 0 fail, 268 assertions, 13.02s;
  `/tmp/cm-gemini-native-fix-regression.log`. Installed Gemini public parser,
  settings/recording modules and shared readiness cache/service tests enabled. Typecheck
  and diff check passed.
- **Configured Gemini wiring:** 57 pass, 0 fail, 400 assertions, 16.89s at 67dacd7;
  `/tmp/cm-gemini-config-regression.log`. Normal configuration/queue and reopen recovery
  use a real Node probe with fixture native module/CLI, not a real model account.
- **Previous broad baseline at b1de06f:** 960 pass, 30 optional skips, 0 fail;
  `/tmp/cm-runtime-detached-full.log`. Docker and standalone SpecMesh enabled. This predates
  newer Gemini/host changes and is not evidence for them.
- **Current broad regression at 3a56eed:** 977 pass, 34 optional skips, 0 fail;
  11,751 assertions across 1,011 tests/119 files, 388.82s, exit 0.
  `/tmp/cm-runtime-post-gemini-full.log`. Docker and standalone SpecMesh enabled; optional
  installed-native/account profiles are not enabled by this command and remain unaccepted.
- Last checked GitHub CI before 3a56eed: d21be48 and 9f35243 succeeded. Later CI must be
  checked against its exact SHA rather than inferred from local tests or prior runs.

## Remaining

1. **CM-R0/R1:** finish Python ownership and side-effect parity inventory, including normal
   provider/process/transport and product-terminal behavior. `python-ownership.json` lists
   owners/hashes; it is not proof they have all been ported.
2. **CM-R2:** complete remaining stores, interrupted migration/replay, compatibility export,
   rollback rehearsal, and live writer-transition procedure. Never infer ownership from
   legacy PIDs or dual-write Python JSON and TS state.
3. **CM-R3:** complete all supported provider/tool/source/workspace and transport profiles.
   Gemini still needs native tool receipts, protected configuration/execution graph and
   real-account acceptance; its current configured text profile explicitly refuses
   workspace/SpecMesh/mailbox requirements. Other providers have their own open matrix.
4. **CM-R4/R5:** complete the physical multi-device/native topology matrix, partition,
   clock/lease, stale-worker, mailbox/backpressure and persistent startup/rollout evidence.
   Earlier Rock 5C SSH timeout is a last observation, not a current reachability claim.
5. **CM-R6:** complete History adoption across required providers, real same-session
   continuation/current-file proof, independent SpecMesh hooks and reviewed closeout.
   Historical context is never current project authority or a permission grant.
6. **CM-R7:** clean install/upgrade/package checks, staged default switch, telemetry and
   rollback thresholds, Python writer retirement, release/push and local-version alignment.
   No production cutover or complete release has happened in this sequence.
7. Recheck **CM-A01–A10** against actual final behavior. Preserve cancelled CM tasks
   `77f04609` and `7738c5eb`; no account/browser or WeChat operations are part of this work.

## Issues

- Current Gemini OAuth/client eligibility is externally refused. It is one provider gate,
  not justification to abandon the other migration work or silently narrow the goal.
- Native CLI/package/account, fixture/model-free, real model/account and deployed-device
  claims must remain separate. The public-argv defect demonstrated why module-only
  qualification is insufficient.
- Full terminal UX and production transport delivery are still acceptance requirements.
  Do not spend every continuation on disconnected small provider helpers.

## Next

Telegram text webhook and polling profiles are configured through the normal private entrypoint.
Polling persists raw updates, normalized dispositions and next offset atomically, with a
local-store lease, generation fencing, retry-after and failure latch. Schema 37 broad and
final targeted regressions passed. Schema 38 adds ordinary callback continuation (details below). Next implement Telegram media and management selectors, rich formatting, outbound
rate-limit and streaming parity. Polling inspects the remote webhook instead of deleting it;
separate databases/devices still require the full coordinator/operational acceptance matrix.
The test suite uses local HTTP and unavailable native execution fixtures. No actual Telegram
account, webhook registration or production service was changed. Entire TS migration and
multi-device/provider continuity remain in progress under the original phase/acceptance matrix.
Keep the complete original objective active; mark complete only after every phase and
acceptance item has matching evidence, release and local alignment.

## Current callback checkpoint (schema 38)

- CI fixes b7c62e1 and 859323c separate native failure/exit races and independently
  time the four device publication fault scenarios. Remote CI 34744271753 passed
  at 859323c; this does not cover the later callback changes.
- Telegram ordinary Agent choices now bind opaque IDs to final-part delivery evidence.
  Current bot/chat/topic, receipt, route/grants, complete group and terminal task
  revision are checked before resolving persisted choice text. Foreground/scheduled
  outputs do not issue these chat continuation buttons. Code fences/spans are preserved.
- Schema 38 journals authenticated callbacks separately with original owner/payload,
  pending/applied/blocked status and independent UI acknowledgement state. Webhook and
  polling use this path. Resume, enqueue and applied marking are one transaction;
  duplicate/reopen and forced commit-failure tests preserve original task/native session.
  Text and callback lanes respect arrival order within each conversation. Changed
  permission or cancelled/stale tasks reject old clicks. Generic choice strings never
  dispatch management selectors, even if their text looks like a control command.
- UI acknowledgement uses the selected bot's answerCallbackQuery with a 5s bound,
  four concurrent requests, bounded response and pending/sent/unknown journal. Unknown
  acknowledgement outcomes never replay the acknowledgement or native task. This only
  clears the click notification; management selectors and message keyboard editing are
  separate remaining parity owners.
- Full schema 38 regression: 1067 pass, 34 optional skips, 0 fail, 12365 assertions,
  1101 tests/123 files, 393.83s, exit 0 (`/tmp/cm-runtime-callback-full.log`). Docker and
  standalone SpecMesh enabled. Session 62195 is terminal; do not poll or restart it.
- After the full run, code-fence parsing was corrected and cancellation/policy-revocation
  coverage added. Final focused regression: 75 pass, 0 fail, 442 assertions, 2.53s
  (`/tmp/cm-callback-final-focused.log`). Typecheck and diff check pass. The ownership
  manifest changed only the generated Python protocol model hash.
- All Telegram transport/Agent tests use local HTTP and execution fixtures; no actual
  Telegram account was used. Full TS retirement, supported provider/device matrix,
  reviewed SpecMesh closeout, product terminal, installation and release remain open.
- Next: check CI for the callback commit, then port remaining transport media/rich output,
  management selectors, rate limits and streaming behavior within CM-R3. Retain the
  separate operational acceptance and CM-R7 cutover gates.

## Outbound rate-limit checkpoint (schema 39)

- Callback commit 607f69e remote CI 34744841392 passed runtime tests, but failed
  bundled dashboard synchronization: its embedded generated schema lacked `choices`.
  The canonical Web build regenerated only the matching 29-line schema addition,
  committed/pushed as f4ed2ad; replacement remote CI 34745080876 succeeded.
- Explicit HTTP 429 + validated Telegram negative response + bounded positive integer
  retry_after now issues a typed refusal. Other malformed/API/network outcomes remain
  unknown and cannot authorize a retry. Schema 39 retains refusal count, adapter,
  envelope digest, last attempt and not-before time. Shared bot cooldown is checked
  before preparation and again at dispatch admission; three refusals latch blocked.
- Owned wakeup resumes pending delivery after the persisted deadline, without an
  incoming message; stop clears the timer. Reopen reuses the original deadline. No
  Agent is rerun by delivery retry. Automated retries stop after three explicit refusals;
  an operator retry still observes the shared cooldown.
- Focused outbox/Telegram baseline: 72 pass, 0 fail, 615 assertions, 3.69s
  (`/tmp/cm-telegram-rate.log`). Additional shared-bot and actual timer checks:
  47 pass, 0 fail, 382 assertions, 3.10s (`/tmp/cm-rate-wakeup.log`). Typecheck passes.
- Schema 39 full regression: 1078 pass, 34 optional skips, 0 fail, 12462 assertions,
  1112 tests/123 files, 396.06s, exit 0 (`/tmp/cm-runtime-rate-full.log`), Docker and
  standalone SpecMesh enabled. Exec session 82869 is terminal.
- Final stop/revocation/concurrent-reopen checks plus shared delivery regression:
  77 pass, 0 fail, 664 assertions, 7.17s (`/tmp/cm-rate-final-boundaries.log`).
  Typecheck/diff check pass. No actual account/production service changed.
- Next check this commit's CI and port transport media/rich output. Python
  `controlmesh/messenger/telegram/sender.py` dispatches `<file:...>` tags through
  allowed roots and type-aware upload; TS currently projects only text. Media migration
  must bind permitted bytes/identity and remote receipts rather than directly trusting
  an Agent-supplied filesystem path. Full supported transport and operational matrix,
  TS default switch and release/local-version alignment remain incomplete.

## Schema 40: configured local media delivery

- Rate-limit commit `82ecb40` is pushed; CI `34745426070` succeeded.
- Normal Telegram configuration now accepts explicit `delivery.media_roots`. Canonical
  root identity is pinned; file tags select only within those roots. Capture rejects
  links, traversal and non-files, rechecks authorization while reading, and retains
  immutable bytes with size/hash identity. The separate native context limit stays 4 MiB;
  media is bounded to 50 MiB per file and 128 files/256 MiB in the private store.
- Schema 40 stores media against the principal, complete envelope, terminal event and
  task revision. Public metadata has no source path. Complete text/media groups stage
  atomically; capacity refusal precedes file reads. Later-file failure rolls back earlier
  captures and creates a blocked delivery, with explicit same-revision retry.
- Multipart uploads use retained bytes for photo/video/audio/document. One complete
  HTTP 400 rejection allows document fallback; ambiguous outcomes never trigger another
  upload. Receipts bind bot/chat/topic/caption and media metadata. A transformed photo
  acknowledgement is not proof of byte-identical remote storage.
- Confirmed acceptance and original-ack reconciliation reclaim stored bytes. Unknown
  uploads retain them across reopen and never automatically resend. Last-part buttons
  preserve original-task continuation binding.
- Full runtime regression, including Docker and independent SpecMesh: **1117 pass,
  34 skip, 0 fail**, 12628 assertions, 1151 tests across 126 files, 397.63s
  (`/tmp/cm-runtime-media-full.log`). The run has finished; do not resume its old handle.
- Final media/capture/Telegram checks: **83 pass, 0 fail**, 541 assertions, 5.91s
  (`/tmp/cm-media-final.log`); runtime typecheck and diff check pass.
  Generated Python/TS protocol, bundled Web schemas and ownership fingerprint are included.
- Acceptance scope is configured local roots with fixture HTTP endpoints. No actual
  Telegram account upload, remote-device artifact sourcing, production cutover or full
  TS migration is claimed. Cross-device artifacts, management selectors, formatting and
  streaming remain required transport work before the broader migration/release gates.

## Device artifact to media integration

- Local media commit `d86373c` is pushed; CI `34746981469` succeeded.
- `DeliveryDeviceFiles` captures only a file declared by the accepted device execution
  identified by the original terminal event. It uses `DeviceArtifactInbox.read`, preserving
  current revision, principal, completion proof and digest checks through every chunk and
  revalidation. It never resolves a worker path on the coordinator filesystem.
- Normal Telegram config accepts boolean `media_device_artifacts`; explicit true enables
  `<artifact:relative/path>` without granting local roots. Local and device capture share
  the durable media store and outbox; existing per-device transfer limits remain enforced.
- End-to-end fixture coverage runs the device worker/HTTP transfer/completion, projects
  the original text plus attachment, removes the worker directory, and verifies multipart
  upload of the transferred bytes. Single/chunked files, rejected foreign/event/path
  references, disabled source, revoked authority and post-resume capture are covered.
- Related native-device, media, outbox and normal-config regression: **105 pass, 0 fail**,
  961 assertions, 10.62s (`/tmp/cm-device-media-regression.log`); runtime typecheck and
  diff check passed. The test sender uses fixture credentials and intercepted HTTP.
- Final single/chunked checks also reject authority loss during capture and modified
  captured buffers: 2 pass, 0 fail, 42 assertions (`/tmp/cm-device-media-final.log`).
- This closes the retained device-artifact-to-Telegram path for existing accepted device
  artifacts, not physical fleet deployment, all provider artifact profiles or real accounts.
  Next verify this commit's CI, then continue transport parity and the remaining CM-R0–R7
  gates. Production remains Python; release/local alignment is still pending.

## Telegram runtime stop control

- Device-artifact delivery `232b7ad` is pushed; CI `34747306589` succeeded.
- Audit of Python `messenger/telegram/app.py` and `orchestrator/selectors/` confirmed
  `/stop` has a direct runtime route, while model/cron/session/task menus use separate
  management handlers. TS previously queued `/stop` as ordinary model input.
- TS now consumes authenticated `/stop` (including the selected bot suffix) without
  model preflight. It cancels only the mapped conversation task and blocks older queued
  inputs/callbacks. Duplicate updates retain their original receipt. One reserved control
  slot admits stop at ordinary inbox capacity; there is no unbounded queue exemption.
- The ingress pump previously awaited `runtime.drain()` before processing newly received
  input. Its optional synchronous control hook now runs on ingress kicks even during
  active execution. Shared Feishu behavior retains its existing path.
- Webhook test starts a held execution, posts stop through real loopback HTTP and proves
  the active controller exits as cancelled with no successful-result delivery. Related
  Telegram inbox/polling and Feishu inbox checks: **52 pass, 0 fail**, 417 assertions,
  2.31s (`/tmp/cm-telegram-stop-active.log`); typecheck passed. Final callback-order check:
  1 pass, 5 assertions (`/tmp/cm-telegram-stop-order.log`). No external chat account used.
- Stops without a mapped task consume the command without creating a model task. A
  dedicated management response/menu surface remains open, as do model/cron/named-session
  selectors, task cancel-all/cleanup, formatting/streaming and full migration/release gates.

## Schema 41: independent management replies

- Stop control `b99d78e` is pushed; CI `34747662184` succeeded. Another CI invocation
  exists for the same SHA (`34747661811`), not a separate implementation.
- `telegram_control_replies` binds private runtime responses to authenticated inbox
  requests, without synthetic tasks. No-op stop responses use it; actual cancellation
  keeps its existing terminal result response. Task selector menus remain open.
- `telegram-control-reply.ts` verifies bot/chat/thread/text/attempt identity. Dispatch
  becomes unknown before HTTP; original acknowledgements are retained separately from
  acceptance. Explicit inbox retry can accept that original acknowledgement, without
  another send. Unobserved sends cannot be retried; preparation failures remain blocked.
- Response capacity does not undo a stop: with 128 unresolved send records, a completed
  stop retains a deferred reply marker. Capacity recovery stages only the response.
  Deferred work contributes to admission and status; source policy is rechecked after
  reopen. Unresolved reply IDs/reasons appear in the existing inspection/retry surface.
- Focused transport/inbox/polling/Feishu checks: **69 pass, 0 fail**, 650 assertions, 3.43s
  (`/tmp/cm-control-replies-capacity.log`). Full frozen-source regression with Docker and
  independent SpecMesh: **1148 pass, 34 skip, 0 fail**, 12946 assertions, 1182 tests across
  127 files, 410.38s (`/tmp/cm-runtime-control-replies-frozen.log`, session 38768 exited 0).
  Current runtime typecheck passed. No live test process remains for this run.
- Superseded run 39661 mixed cached old modules with a new capacity test and had one
  known failure. It is not acceptance evidence; the frozen-source run above replaces it.
- No actual Telegram account send occurred. Definitive rate-refusal retry for management
  replies, full selector menus, formatting/streaming and the wider CM-R0–R7 matrix remain.

## Schema 42: task status commands

- Management replies `c6cefd7` are pushed; CI `34748541257` succeeded.
- `/tasks` now directly reads selected bot/principal/chat/topic routes, rechecks current
  task authority and returns up to ten entries with an observation time. `/tasks after
  <task_id>` continues the bounded page. Names are display-bounded and control characters
  removed; prompts and paths are not included. No task or model invocation is created.
- Persisted `control_kind` separates read-only views from execution input ordering. Older
  pending user input is not superseded by a newer task view, and a pending view at reply
  capacity does not block later execution input. Old pending requests are classified on
  schema upgrade before admission. Invalid `/tasks` arguments receive usage text.
- The independent control reply pump sends status during active execution without waiting
  for `runtime.drain()`. It is bounded, joins shutdown, and retains prior unknown-send
  behavior. Stop continues to abort the original runtime controller.
- Final Telegram control/inbox/polling and shared Feishu regression: **76 pass, 0 fail**,
  696 assertions, 3.52s (`/tmp/cm-task-views-final.log`). Migration/upgrade cases across
  the runtime suite: **33 pass, 0 fail**, 188 assertions (`/tmp/cm-task-views-migrations.log`).
  Current typecheck and diff check passed. No actual chat account used; full CI for the
  new commit must still be checked. Prior schema 41 full regression does not certify 42.
- This implements the read-only task page and cursor, not cancellation/cleanup buttons,
  model/cron/session menus, streaming/formatting or the full migration/release matrix.

## Release checkpoint

GitHub latest releases remain CM `v0.43.0`, Viewer `v1.1.0`, SpecMesh `v1.2.1`; installed
`/home/muqiao/.local/bin/cm` reports `0.43.0`. No TS production switch or new release has
occurred. Viewer HEAD is `9ea53f1`, SpecMesh HEAD `d393c54`; their respective handoff-service
and independent-port plans retain open acceptance phases. Unrelated Viewer untracked work
was preserved. This checkpoint is not final release/local-alignment acceptance.

## Task management cancellation

- Schema 42 task-page commit `4e27457` CI `34748841147` completed successfully.
- Task pages now issue private `cmg:` cancellation actions bound to the current task
  revision and reply-route digest. Consumption requires an accepted management message
  receipt, matching bot/chat/topic, current source policy and task authority. The existing
  callback journal atomically records cancellation and one-time consumption; ordinary
  `cmc:` Agent continuation remains separate.
- Control processing and callback acknowledgement run outside the active native work
  queue. Task pages select authorized reply routes even for non-chat execution origins.
- Focused Telegram inbox/polling/control and shared Feishu checks: **79 pass, 0 fail**,
  719 assertions, 3.47s (`/tmp/cm-management-cancel-final.log`). Added quota, active
  cancellation, duplicate/reopen, wrong-parent and stale-version cases. No real account
  was contacted. Full migration, production switch and release remain incomplete.

## Offline compatibility export rehearsal

- `e33952b` is pushed; CI `34749102599` was verified in progress, not yet accepted.
- Added `scripts/legacy-export.ts` as an executable counterpart to the offline snapshot
  importer. It opens SQLite read-only, reads one transaction, verifies runtime identity,
  retained original digest/count and task identities/statuses, and refuses missing original
  tasks. It does not instantiate the schema-migrating RuntimeDatabase constructor.
- Output uses exclusive creation and mode 0600, is flushed before success, and never
  overwrites an existing backup or final-component symlink. A failed write may leave a
  partial newly created file; no successful receipt is emitted in that case.
- Independent-process export plus kernel regression: **18 pass, 0 fail**, 97 assertions,
  776ms (`/tmp/cm-legacy-export.log`). Python serializer fixture fields and new TS rows
  survived export/re-import; main database bytes stayed unchanged. Missing source and
  lost imported rows refused output. This is compatibility-artifact rehearsal, not Python
  production startup, writer transfer, or complete multi-store rollback acceptance.

- Post-test typecheck found a widened string in the new test task status. The initial
  export commit was pushed before that failure stopped publication; corrected the test
  to the literal status and reran typecheck successfully. Use the follow-up commit CI,
  not the superseded commit, for acceptance.

## Python rollback reader evidence

- Extended the offline export rehearsal with a real `uv run python` process using current
  `TaskEntry.from_dict` and `TaskRegistry`. After parsing actual exported rows, directory
  references are explicitly remapped to temporary folders before registry initialization.
  No real task directories or account runtime are opened.
- Confirmed current Python startup semantics: running/recovering become stale; an entry
  with no folder is removed. JSON-only restore is consequently insufficient. Exported
  unknown fields are retained as artifact bytes, not promised through Python reserialization.
- Export tests: **2 pass, 0 fail**, 18 assertions, 831ms (`/tmp/cm-python-rollback.log`).
  This adds actual Python reader evidence; production directory restoration, execution
  reconciliation, other stores and writer transfer remain open.
- Latest export fix CI `34749203765` was verified queued; prior cancellation CI
  `34749102599` was in progress. No completion claim for either pending run.

## Host source policy parity

- Cancellation commit `e33952b` CI `34749102599` completed successfully. Python export
  rehearsal `75b641f` CI `34749242744` was verified running; not yet accepted.
- Host routing, execution adapter, process launch and retained-result recovery now use
  a dedicated `enforceHostJobSource`, matching Python's host sandbox decision. Previously
  they incorrectly borrowed the local-foreground-only native-provider profile.
- Real temporary-directory shell tests execute approved direct_message/background_task/
  task_result/legacy_compat contexts. Group, bot handoff, API, cron, webhook and heartbeat
  fail before effects because the host launcher has no sandbox. Native provider source
  restrictions are unchanged. Issued context, approval, grant, workspace and lease checks
  remain mandatory; imported task metadata alone cannot authorize execution.
- Host suite/local queue/live Python authorization matrix: **68 pass, 3 skip, 0 fail**,
  1311 assertions, 10.18s (`/tmp/cm-host-source-full.log`). The three optional independent
  SpecMesh cases were subsequently exercised with the configured local repository:
  **12 pass, 0 fail**, 136 assertions, 7.82s (`/tmp/cm-host-source-specmesh.log`). Runtime
  typecheck passed. Full source ingress/deployment matrix and production cutover remain.

## Cheap-worker acceptance and parent supervision

- User now delegates routine implementation/testing to installed CBC/AGY; primary owns
  dispatch, review and acceptance. Global CLI no-prompt defaults are user-authorized.
- Primary inspected CBC raw logs: 19 pass, 0 fail, 111 assertions (2.60s), both host
  process and issued-ingress suites; typecheck exit 0. No production code changed by CBC.
  Host-source-ingress acceptance is ready for commit. AGY cron plan remains review pending.
- Live CM listener verified on 127.0.0.1:8799, process 8610. Existing TaskHub parent
  inbox/consume/result callback chain is present. A generic doctor profile is not proof
  the running service lacks it. CBC is assigned to reuse/verify the actual parent bridge,
  not introduce a second scheduler or assume CM main is this Codex conversation.
- CBC bridge process handle 51930; output /tmp/cm-cbc-taskhub-parent.json, diagnostics
  /tmp/cm-cbc-taskhub-parent.err. Poll handle before restarting. No periodic model job.

## Missed handoff correction and real CM launch

CBC bridge and AGY review 1 had both exited successfully, but the primary ended its turn
before collecting them. Their output files did not wake the desktop controller. This was
a workflow failure; do not describe it as an active callback or as a provider quota issue.

Primary bridge review found missing concurrent cold-start/consume protection and missing
parent/definition binding. CBC native session `01a09a29-a069-7afe-9ab4-909d055fa089` is
now resumed through source CM hostjob `cbc-parent-bridge-r2`, explicit logical parent
`codex-runtime-convergence`, isolated CM home under outputs/runtime-convergence/parent-supervision.
Launch detached after 1s; authoritative CM status is running. A separate non-model CM
wait process (unified exec 45057, no wait timeout) is active in the primary tool channel.
`cbc ps --json` confirmed matching native session heartbeat and its JSONL events advance.
This proves actual launch/continuation, not yet terminal result acceptance or installed
0.43.0 alignment. See delegation/README.md for paths and handles.

AGY revised plan's native conversation ID from CLI JSON:
`def64a8d-18c9-49eb-abd4-82488284d15f`. Six review concerns were addressed in its design;
primary further corrected fold wording to first/second ordering rather than universal
DST classification. Cron SQL and provider integration remain proposed, not implemented.

## Parent result received; cron persistence and CI parallel work

- CM's active wait returned CBC r2 completed/exit 0 at 2026-09-13T11:49:50Z. This is
  actual receipt by the primary tool turn, not an idle desktop callback.
- Primary's small scratch-state acceptance reproduced a binding bypass: corrupt intent
  followed by another parent and command returned the old completed event and allowed
  a second consume. Returned to the same CBC native session as CM job
  cbc-parent-bridge-r3 (handle 92783). Wrapper disappearance uncertainty also remains a
  review concern. Bridge is not accepted or published yet.
- AGY same-native-session batch 1 implements TS cron persistence/offline migration;
  CM job agy-cron-batch1, handle 61893. Code is in progress, not accepted. No runtime
  switch, production cron writes, model-polling loop or release.
- User authorized CI settings review. Of the latest 12 main runs, 11 now succeed;
  earlier d5734e1 failed a genuine TS literal type check, fixed at 8651820. Latest
  93fb734 failed one Docker info preflight; its failed-job rerun succeeded unchanged.
  CBC job cbc-ci-stability (handle 64503) is implementing bounded read-only readiness
  and superseded-run cancellation while retaining required checks. Raw initial failed
  log: /tmp/cm-ci-34750299686-failed.log. Acceptance pending.

## Accepted CI stability change and controller version boundary

CI-only commit `5cab0c9` is pushed to main. Remote run 34756010064 succeeded, including
both Python versions, Ruff, mypy, packaged Alpha smoke, product layer, real containers
and the explicit aggregate. Required checks remain. Manual dispatch has a unique run-ID
concurrency group; push/PR superseded checks can cancel. Docker readiness retries only
bounded read-only probes; runtime execution and assertion failures are not retried.

AGY batch 1 worker itself completed with exit 0 and native SUCCESS, but its supervising
CM command (61893) exited 1 with `_clear_review_locked` NameError: it imported an
intermediate Python module while CBC was editing that module. Do not rerun AGY batch 1
or equate controller failure to worker failure. Both native result and exit artifact
were read. Primary review found unsafe future fencing, uncertain-attempt replay and
lossy/non-exclusive export despite passing happy-path tests; revision 2 is required.

New controller launches use a frozen copy under outputs/runtime-convergence/parent-supervision/
controller-r3-snapshot (477 Python files, manifest.json with SHA-256 digests), not the
editable checkout. The snapshot passed an actual run/wait completed/exit-0 smoke.
AGY revision 2 uses CM job agy-cron-batch1-r2, active handle 93495, same native conversation.
Its task is delegation/agy-cron-batch-1-review-2.md. This operational snapshot is not an
installed release or accepted final runtime version. Preserve it while that job runs.

## Local parent bridge acceptance

CBC r3 completed/exit 0 and was collected through CM at 2026-09-13T12:11:27Z.
Primary verified corruption refusal, explicit provenance binding, concurrent start and
consume, review-required unknown worker state and child-alive wrapper loss coverage.
Primary corrected running status snapshots inheriting terminal=true and orphan execution
artifacts allowing recreation. Final targeted bridge suite: 23 passed in 17.25s
(`/tmp/cm-parent-bridge-primary-tests.log`); changed-file Ruff and diff whitespace passed.
CBC also reported 231 runtime/task and 992 multiagent/CLI regressions passed; primary did
not rerun these broad suites. New files have no mypy errors; 12 pre-existing host_jobs.py
errors remain. Ownership generator refreshed: 514 Python modules / 57 persisted TaskEntry
fields, golden fixture unchanged. This records an added Python owner still requiring TS
port; neither full migration nor installed 0.43.0 alignment is complete.

Local bridge committed/pushed at `8f4de54`; remote CI 34756650873 completed successfully.
AGY revision 2 completed exit 0 through the frozen CM controller at 12:14:14Z, was
received, and its exact bound terminal event was consumed once; second consume returned
null/exit 3. This is real native-worker result-channel acceptance, not only a fake CLI.
Primary still rejected its cron code: an actual Bun import/export changed null description
and timezone to empty strings, dropped user raw/version/spec_digest, and a getter created
coordinator authority. Failover completion reconciliation and snapshot publication also
need repair. AGY revision 3 runs as `agy-cron-batch1-r3`, handle 68371, from frozen
`controller-8f4de54` extracted from committed code. See delegation/agy-cron-batch-1-review-3.md.
No other cheap workers remain active. Do not replay the consumed revision-2 attempt.

Next independent owner dispatched: CBC recurrence (`cbc-cron-recurrence`, handle 55848,
native 01a09aba-fdd5-7569-b07c-a3dc7b707188), also through frozen controller-8f4de54.
Owns pure TS expression/timezone/DST calculation and Python differential fixtures, with
no database edits, timer, provider call or delivery. AGY remains persistence owner.
Prior goal turn was concrete progress: CI and bridge commits both passed remote CI,
real native terminal consumption was verified, and rejected cron defects were reproduced.

AGY r3 completed at 12:28:03Z, exit 0; its bound event was consumed. Earlier raw/null
and authority-getter counterexamples now pass independent Bun review. New concrete
regressions: replace:true still retained omitted per-job fields, and removeJob deleted
an active attempt through FK cascade. R4 now owns exact replacement plus archived
definitions retaining execution lineage (CM job agy-cron-batch1-r4, handle 99572).
Do not accept or push the TS cron candidate until these regressions are resolved.

Cross-project read-only refresh: Viewer worktree retains its three untracked user
paths; SpecMesh worktree is clean. Their local AGENTS/PROJECT and active plans still
leave Viewer HV-H0/H1/H4/H5 and the broader native handoff matrix open, plus SpecMesh
external closeout/reviewer evidence and provider/device takeover acceptance. CM's new
CLI result bridge does not close these gates. No source/service changes in either
repository were made during this refresh.

Primary follow-up: both existing run/wait handles remained live; no worker restarted.
A fresh in-memory Bun import/export reproduced loss of five user fields named like
internal metadata (storage_raw/storage_version/storage_spec_digest/storage_archived/
raw_metadata). See delegation/cron-raw-collision-review.md. This observation is against
the still-edited candidate; recheck after AGY R4 finishes before dispatching another review.

Correction at 2026-09-13 20:56 +08: old run/wait handles reflected live controllers, not
live workers. Actual recorded worker PIDs 1831863/1826029 were absent; stdout/stderr and
exit_code.txt were empty. Bridge existence-only completion checks prevented vanished
worker detection. Primary aligned evidence parsing with HostJobRunner's integer parser;
27 focused tests pass (20.34s), including absent/empty/whitespace/corrupt/non-UTF8 exit
artifacts, with Ruff/diff checks passing. Log: /tmp/cm-parent-empty-exit-tests.log.
Stopped only the three identified stale run/wait controllers; corrected wait collected
both jobs as failed, exit_code=null, review_required=true, quiescence=unknown. CBC native
ps reports no active sessions; AGY native quiescence still needs checking. Neither task
was restarted, accepted, or marked successful. Existing code is unfinished and preserved.

After CBC ps confirmed no active native session, primary explicitly continued the same
native conversation through new job cbc-cron-recurrence-recovery on frozen controller
1c8170b. Handle 42834 ended, process exit 0, but stdout reports quota 429 with reset
2026-09-14 17:26:09 UTC+8. This is application failure, not accepted work. No retries
before evidenced reset. Generic process completion and provider semantic completion
remain distinct; do not rewrite real exit codes. Fix 1c8170b pushed successfully.

Primary recurrence recovery review: CBC's test file was empty (Bun exit 0 but zero tests),
so primary added 172 zoneinfo-matrix cases, 41 grammar cases and timezone/fall-back checks.
Initial result 173 pass/42 fail exposed ignored range/wildcard steps (*/15 ran every minute).
Compared actual installed CronSim Field.parse and corrected step selection in TS. Result:
215 pass, 0 fail, 906 assertions; /tmp/cm-primary-cron-recurrence-review.log. Golden --check
reproduces the checked-in matrix. TS errors in recurrence/tests corrected; package typecheck
still fails only on unfinished cron-store archived DTO fields. Six-field grammar rejection,
remaining DST/bounds coverage and original parser attribution remain review items; this is
not full cron acceptance. No CBC model retry, source cutover or cron provider execution.

Independent restart counterexample: daily 01:30 America/New_York, reference
2026-11-01T06:05Z (second 01:05) incorrectly returned the already-used civil slot at
06:30Z. Recurrence now binds repeated civil slots to fold 0 only; no fold-1 catch-up.
This is an explicit no-replay policy, not unchanged Python runtime parity. Oracle retains
py_announced_ms/py_fire_ms separately; expected_ms records the TS policy. Bounded retry
allows 2881 civil minute slots for historical date-line repeats. Updated result 216 pass,
0 fail, 907 assertions in 216ms, Ruff and diff checks pass. Full persistence acceptance,
cron ingress/provider integration, and runtime rollout remain open. AGY recovery wrapper
1864653 and handle 57638 reverified live; no duplicate continuation dispatched.

CI follow-up: 1c8170b run 34758490373 failed the generated runtime ownership check,
not the new supervision tests. Primary omitted regeneration after changing bridge source.
Regeneration changes only the host_job_bridge.py SHA in python-ownership.json; inventory
remains 514 modules/57 fields. No gate relaxed. b6d9ddb was pushed with 217 recurrence
tests passing; its run 34759251799 was still active when inspected. AGY recovery remains
live and has begun updating archive/restore code; its final evidence is not available yet.

Remote verification: CI run 34759345008 for exact SHA
58a143eb22e4c7d1031c64dac8ccb9c32d36e5af completed SUCCESS; all required jobs passed.
This verifies the committed bridge fix, refreshed ownership digest and recurrence module.
The uncommitted AGY persistence candidate was excluded and remains unaccepted.

AGY handle 57638 returned terminal process exit 0 at 13:23:34Z, but stderr states print
timeout after 20m with turn in progress. Native JSON SUCCESS response only says tests
were launched and awaited. No Bun/pytest/tsc process or new AGY log was found; no restart.
Primary then ran focused persistence tests (12 pass/114 assertions) and package typecheck
(exit 0); logs /tmp/cm-primary-persistence-recovery-{test,typecheck}.log. Fresh in-memory
counterexamples now pass: seven colliding user keys retained, replacement removes obsolete
field, archive hides definition/export while retaining attempt, restoration preserves
attempt and increments revision. These fixes still need committed regressions plus actual
snapshot contention/publication-failure and rollback coverage requested in review 4.

Primary added cron-registry-recovery.test.ts: colliding raw keys across replacement and
50 status updates, archive/restore with retained active attempt and replay rejection,
rollback of earlier writes/archives/snapshot metadata when a later job is invalid, actual
overlapping WAL reader/writer transactions, and injected publication collision exercising
real filesystem EEXIST after temp fsync with preserved winner and no temp leak. Five new
tests pass (38 assertions). Combined cron suite: 234 pass/1069 assertions, 696ms; package
typecheck exit 0. Logs /tmp/cm-primary-cron-combined.log and
/tmp/cm-primary-persistence-recovery-typecheck.log. Runtime package suite launched once
because migration 43 affects all database consumers; completion evidence still pending.

Full package handle 3531 completed: 1368 pass/70 skip/2 fail in 191.55s. Both failures
were legacy-export rejecting schema 43 due to its old upper bound 42. Primary updated
the read-only export bound and added version-44 refusal without output/database mutation.
Legacy export plus persistence/recovery follow-up: 20 pass/174 assertions. See
delegation/primary-cron-persistence-result.md for scoped source acceptance and remaining
runtime integration. This records a failed full run and successful targeted correction,
not a fabricated all-green full rerun.

Scheduler integration review reproduced a stale-admission gap: createAttempt accepted
an old queued occurrence after its definition was archived. Added transactional current
normalized definition validation (active/enabled and exact revision/digest) before new
attempt insertion. Regression covers archive, disable and changed instruction, requiring
zero attempts after rejection. Existing-attempt reconciliation is unchanged. Persistence
suites: 18 pass/158 assertions; /tmp/cm-cron-admission-definition-review.log. This is an
execution-entry guard required before timer/queue integration, not a completed scheduler.

Implemented CronTaskAdmission using existing TaskIngress and the same RuntimeDatabase
transaction: fixed schedule/cron provenance and controller-required grant, one task/attempt
binding, repeated-submit observation, coordinator generation fencing, rollback on either
task or attempt refusal, TaskHub policy checks and monitor disable after successful submit.
The first implementation exposed FK ordering; corrected task-before-attempt in the same
transaction. Initiated occurrences are now enqueued; explicit worker state advances running.
Provider execution is not started. Timer due/quiet/dependency eligibility remains the
scheduler's unimplemented owner; this trusted seam is not exposed as a remote endpoint.
Validation: 29 tests pass/224 assertions; /tmp/cm-cron-task-admission-tests.log. Final
typecheck passes after state correction; /tmp/cm-cron-task-admission-typecheck.log.
Public index exports this admission seam for subsequent integration.

0b4886e push initially timed out; verified remote still at 0a85b05, then explicit bounded
push succeeded. Admission now verifies due time and explicit quiet windows before task
creation, matching Python's configured-user-timezone semantics (no heartbeat fallback,
no substitution of job recurrence timezone). Seven admission tests pass/28 assertions,
including fixed-clock due boundary and cross-midnight zone behavior; typecheck passes.
Logs /tmp/cm-cron-quiet-admission-{tests,typecheck}.log. Dependency eligibility, durable
timer/cursor loop and actual execution/delivery are still pending; production unchanged.

Dependency integration: Python DependencyQueue uses same-key FIFO mutual exclusion,
not prerequisite job IDs. Task admission now acquires the existing persisted dependency
lock inside the task/attempt transaction; busy admission rolls back task and attempt.
Lock acquisition/renewal additionally checks the attempt's current coordinator generation.
Test verifies a competitor remains blocked after deadline without replay and stale
coordinator renewal is rejected. Twenty tests pass/148 assertions and typecheck passes;
/tmp/cm-cron-dependency-admission-{tests,typecheck}.log. FIFO admission ordering and
verified terminal release still need scheduler/execution integration; no claim they are done.

Added bounded FIFO admission metadata (version 1, at most 256 unique occurrence IDs per
dependency) in the existing transactional meta store. Busy requests commit only queue
position; task/attempt creation waits for both queue head and free lock. Invalidated
waiting definitions are pruned, while active/uncertain execution stays protected by its
separate lock. Successful admission removes its waiting entry in the same transaction.
New connection test confirms request order survives connection replacement and cannot
be bypassed by older planned timestamps. Typecheck and nine admission tests pass; logs
/tmp/cm-cron-fifo-admission-{tests,typecheck}.log. Actual process completion/release,
timer/cursor owner and broader provider/device acceptance remain pending.

Per-job overlap correction: Python CronObserver._executing suppresses overlapping runs
across schedule slots, but TS createAttempt previously checked only the same occurrence.
The transactional query now covers every initiated/running/cancelling/uncertain attempt
of the same job. Updated regression explicitly rejects a later slot while the first is
unknown, then simulates trusted reconciliation before admitting the next slot. Twenty-seven
tests pass/199 assertions and typecheck passes; /tmp/cm-cron-job-overlap-{tests,typecheck}.log.
This closes a persistence admission gap required for the upcoming recurring timer owner.

Implemented exported CronScheduler tick/run: bounded enabled-job scan, versioned cursor
binding to definition/timezone, forward initial planning, one-slot recovery without full
backfill, stable pending occurrence while dependency-busy, unchanged-state detection,
explicit quiet/duplicate skip records and abortable model-free delay loop. Uses existing
CronTaskAdmission; does not invoke providers. Four scheduler tests cover disk reopen,
overlap/no-backfill, quiet skip, dependency wait reuse/release, abort and stale coordinator.
Combined cron suite 248 pass/1136 assertions (1070ms) and typecheck pass;
/tmp/cm-cron-scheduler-{suite,typecheck}.log. Runtime service startup, worker execution,
quota circuits, real terminal reconciliation and delivery remain open. No production
service, OS cron, external account or model invocation was started for these tests.

CronScheduler/CronTaskAdmission now accept an optional existing LocalTaskRuntime bound
to the exact same kernel. New admissions enqueue within the task/attempt transaction;
queue-full rolls back task, attempt and queue insertion while retaining the scheduler's
pending occurrence for retry. Existing submissions remain observations, without replay.
Fourteen scheduler/admission tests pass (70 assertions), plus typecheck and diff check;
logs /tmp/cm-cron-queue-{tests,typecheck}.log. Test uses the actual SQLite local queue
with a nonexecuting resolver, not a real provider. Runtime startup wiring and terminal
reconciliation remain pending. A suspected equal-generation cross-coordinator issue
was disproven by singleton registration and generation-incrementing takeover; that
experimental patch and test were removed rather than claiming a reproduced defect.

Candidate local service now wires optional cron_scheduler configuration to the existing
queue/provider resolver and ticks it before checking whether execution drain is pending.
Requires explicit existing coordinator identity/generation; no startup bootstrap/rotation.
Detached host worker mode suppresses cron. Actual service/socket test proves cursor
creation and preservation after close/reopen, no model probes/tasks for a future slot,
rejection of missing/stale authority, and no child scheduler. One test/seven assertions
passes, plus typecheck; /tmp/cm-cron-service-{tests,typecheck}.log. No production profile
was changed. Real native execution/terminal synchronization, quota circuits and delivery
acceptance remain pending; full TS migration and multi-device gates remain open.
