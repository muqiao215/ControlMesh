# Runtime convergence progress

## Current

Full TS migration, multi-device coordination and real Agent continuity remain **in
progress**. No production writer cutover, complete release or default TS installation
has been accepted. Last directly checked local `cm --version`: **0.43.0**, Python.
The last pushed baseline is **62f35d6** (chat-scoped receipts and local acknowledgement recovery).
Current changes add schema 35 multipart projection, ordered per-part sends and group status;
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
| Telegram delivery | Selected private bot profile, strict receipts, ordered persisted multipart text, retained-ack recovery and group status | Local HTTP/reopen/SIGKILL and upgrade tests; inbound, files, formatting, streaming, rate-limit handling and production delivery remain |
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

Telegram text delivery is wired through normal configuration and DeliveryOutbox. Multipart
text is projected atomically into per-part records, with sequential barriers and group
completion available through private `delivery_groups`. Schema 35 broad validation passed.
Next implement Telegram ingress and its message/thread routing, followed by files, rich
formatting, bounded rate-limit handling and streaming. No real account sends are authorized.
Original retained acknowledgements recover locally without credentials or another send;
missing acknowledgements remain unknown and stop the unsent suffix. This proves original
send acknowledgement, not current remote content or recipient consumption.
Keep the complete original objective active; mark complete only after every phase and
acceptance item has matching evidence, release and local alignment.
