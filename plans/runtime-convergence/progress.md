# Progress

## Current

Full goal active. A private transactional TS kernel, durable mailbox, Linux process supervision and persisted native OpenCode preflight service are implemented in the primary local workspace. CM-R0/R1/R2/R3/R5 remain in progress because runtime integration and their full exit gates are not complete.

## Done

Checkpoint `f65cc27e3ba2c9b2b57a73f0380967722229c7f4` is pushed to main. CI 34550244752 passed, including both complete Python suites (3.11/3.12), type/protocol/golden/SDK/Web checks, build and installed-wheel smoke. No production runtime cutover or new release tag was made for this private kernel checkpoint.

The supervision checkpoint `011510e8b349a628173150e7cbd4f021919e5b20` is pushed to main; CI 34572737074 passed for that SHA. Python remains the released runtime.

Implemented `packages/controlmesh-runtime-core` with versioned SQLite transactions, request receipts, task revisions, per-episode device leases/fencing, cancellation, uncertain-result recovery, external-effect dispatch/confirmation and bounded durable mailboxes. Versioned lease/message schemas generate Python and TS definitions through existing tooling. Added an explicit snapshot preview/import CLI and source/serializer drift gate; CI runs `pnpm test:runtime-core`.

Checks: 23 kernel/mailbox/process tests passed, including final atomic-event/reopen regressions (96 assertions). Strict TS typecheck and repository Ruff passed. Existing lifecycle/writeback/grant/provenance goldens passed, including 14/14 facade observations and 22 Python protocol/golden tests; 12 SDK smokes passed; Web bundle rebuilt for the additive generated schemas. Protocol/release-contract tests separately passed 11/11. Source baseline: 512 Python modules and 57 serialized TaskEntry fields. Read-only preview of actual local tasks: one done, two cancelled, no active tasks; no writer switch or task-folder changes.

## Remaining

CM-R0 through CM-R7; coupled History/SpecMesh gates and actual multi-device/native provider acceptance. No full-migration completion is claimed.

## Issues

No blocking condition. Legacy TaskRegistry performs destructive orphan cleanup at construction; import/migration must never construct it against live source data. The old JSON helper treats corrupt inputs as absent, so migration must use strict decoding and preserve all unknown fields.

## Next

Linux process supervision is now implemented and tested: a detached, verified anchor survives provider exit and terminates the owned group on controller loss, lease cancellation, deadline, output limit or native error. PID/start-time/group/session guards prevent unsafe group signals, and asynchronous admission callbacks fail before spawn. The full new core suite passed 32/32 with 122 assertions on the actual Bun 1.3.11 executable used for CI, plus strict TS typecheck. The initial `pnpm dlx` shim was empty and its zero exit was not accepted as test evidence; the real versioned binary was located and executed directly. These are synthetic real-process tests, not model-account or native-session acceptance.

OpenCode preflight is now connected to a versioned SQLite cache: native permission attestation, exact model/config/credential/device binding, one durable probe permit, expiry, bounded transient retries, and explicit recovery from unknown results. Schema v1 upgrades atomically to v2 while preserving tasks. Core tests passed 51/51 (203 assertions) on Bun 1.3.11, with strict TS typecheck. Actual OpenCode 1.18.29 accepted the recently used M3 model; repeat/reopen requests reused one cache generation. A loopback-only synthetic quota provider received exactly one request before native-error abort (3.95 seconds). See findings for permission and history-selection details. These native model probes did not resume existing conversations.

Wire the concrete provider/source/grant admission and execution runner, including native continuation identity and explicit reconciliation. Other persisted stores, device transport and SpecMesh hooks remain. Full production cutover is pending; do not relabel this checkpoint as full TS migration.
