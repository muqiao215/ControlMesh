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
