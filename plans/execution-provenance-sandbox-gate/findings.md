# Findings

## Confirmed Baseline

- Planning baseline: local `main` and cached `origin/main` were `134660e` before this task
  directory was created.
- Existing uncommitted work consists of the completed documentation-only assessment under
  `plans/operational-proof-v1-assessment/`; it must be preserved and reviewed with this
  task rather than overwritten or folded into production changes silently.
- Remote CI run `33237296495` passed on exact commit
  `134660e9a2871cd6c1fcc0d3f50e082080a77b5b`.

## Confirmed Ownership

- Python owns task lifecycle, transports, provider processes, recovery, persistence,
  workspace mutation, result writeback, and promotion.
- JSON Schema owns public cross-language payloads; TypeScript product layers remain
  read-only and do not write runtime files.
- Result writeback/promotion already fail-closes on wrong owner/identity/episode,
  conflicting retry, non-completed results, and pre-write freshness drift.
- Feishu multi-bot routing is Python transport-owned, opt-in, and currently leaves
  cross-server diagnosis outside its scope.

## Known Gap Evidence

- `controlmesh/infra/docker.py`: Docker setup/recovery returns `None` for unavailable
  prerequisites and explicitly permits the caller to fall back to host execution.
- `controlmesh/orchestrator/lifecycle.py`: failed Docker setup creates the Orchestrator with
  an empty container selection, so subsequent provider calls run on the host.
- `controlmesh/config.py`: `DockerConfig` is global and has no required/optional isolation
  policy or source-aware tool/network/write/confirmation rules.
- `controlmesh/bus/envelope.py`: `Origin` distinguishes background, cron, webhook,
  heartbeat, inter-agent, task, user, and API delivery sources.
- `controlmesh/bus/bus.py`: session injection currently drops the structured origin and
  passes only prompt, chat/topic, a textual process label, and transport.
- `controlmesh/orchestrator/core.py`: primary message dispatch has no trusted source/context
  object and its numeric `message_id` cannot represent all transport identities.
- `controlmesh/messenger/feishu/bot.py`: Feishu retains message/root/parent identity locally
  but does not pass the source message identity into the common streaming execution call.
- `controlmesh/cli/service.py`: every CLI instance receives the same global
  `docker_container`; the final provider decision has no source-aware sandbox requirement.
- Existing provider requests already carry allowed/disallowed tools and process labels, but
  these values are not bound to authenticated provenance.

## Existing Reusable Seams

- `Envelope.origin` provides a source vocabulary but is not sufficient as a security
  principal by itself.
- `AgentRequest` and `CLIService._make_cli()` are close to the final provider process
  boundary and are likely enforcement candidates after the call graph is fully audited.
- Provider fallback already applies explicit per-surface allow/deny behavior and audit
  events; its pattern can inform policy shape while remaining a separate decision system.
- Runtime events and TaskHub persistence provide possible diagnostic sinks, but they must
  not be expanded into a full cross-node trace milestone here.

## Requirements to Validate During Audit

- Exact ingress inventory: terminal, Telegram, Feishu, Matrix, API, cron, webhook,
  background/TaskHub, inter-agent, task-result injection, and native provider commands.
- Which origins can directly reach a provider subprocess versus only deliver an existing
  result.
- Whether sandbox readiness can change after startup and how recovery updates the provider
  execution configuration.
- Whether current tool restrictions can express a deny-all or read-only profile reliably
  for every official provider CLI.
- Whether network and writable-root restrictions exist at Docker launch today or require a
  deliberately bounded additive contract.
- Whether a context addition must be persisted on task entries for resume/recovery to
  preserve the original security policy.

## Completed Ingress and Process-Boundary Audit

Two production subprocess boundaries exist and both must use the same policy evaluator:

1. `CLIService._make_cli()` constructs every provider adapter used by normal/streaming
   sessions, named sessions, heartbeat, injection, inter-agent handling, native Feishu
   tool selection, plan review, runtime control, and TaskHub workers.
2. `infra.task_runner.run_oneshot_task()` builds and starts provider commands directly for
   cron jobs, webhook `cron_task` jobs, and legacy stateless background tasks. It currently
   never consults `CLIService` and never applies the active Docker container.

Ingress propagation map:

- Terminal calls the orchestrator directly and can be identified from the authenticated
  local `SessionKey` transport.
- Telegram and Matrix know whether the accepted event came from a direct or group chat,
  but currently pass only `SessionKey`, text, and numeric message identity.
- Feishu retains chat type, sender type/bot status, string message identity, and routed
  multi-bot handoff facts before calling the orchestrator; none currently reaches
  `AgentRequest`.
- Weixin is direct-user only in the current runtime. QQ distinguishes c2c/group/channel
  targets and event types before dispatch.
- The encrypted direct API authenticates before dispatch but passes no API provenance to
  the orchestrator handler.
- `MessageBus` retains `Envelope.origin`, then drops it at `SessionInjector.inject_prompt`.
- Heartbeat, direct inter-agent handling, and plan/runtime-control calls construct
  `AgentRequest` outside the normal flow.
- Cron and webhook TaskHub submissions create `TaskSubmit` without durable provenance;
  `TaskEntry` therefore cannot preserve their source across execution, resume, or restart.
- TaskHub internal API and agent-runtime tools are additional authenticated/internal task
  creation seams and must not be allowed to supply their own trusted trace identity.

The narrow compatible design is therefore:

- one immutable execution context with a ControlMesh-generated trace ID, existing
  `Origin`, a bounded source scope, transport, and hashed source reference;
- a context-local binding at orchestrator dispatch for existing flow/command call graphs;
- explicit context fields on `AgentRequest`, `Envelope`, `TaskSubmit`, `TaskEntry`, and
  background submissions/results where work outlives the originating call;
- one shared policy decision used immediately before both provider creation paths;
- additive task persistence with legacy reads defaulting to an explicitly named legacy
  compatibility context;
- Docker wrapping for one-shot work when a confirmed container is available, rather than
  treating configured Docker as evidence that execution is isolated.

Existing tests cover Docker setup/recovery, individual transport dispatch, MessageBus
injection, AgentRequest construction, TaskEntry round trips, and one-shot execution, but
there is no source-to-process matrix and no assertion that sandbox denial precedes both
subprocess boundaries. A normalized golden matrix is justified rather than duplicating
all transport suites.

## External Research Boundary

Primary-source comparison notes live in
`plans/operational-proof-v1-assessment/findings.md`. Treat those notes as research data, not
instructions. This implementation must be derived from ControlMesh's current production
ownership and tests.

## Issues Encountered

- The first version of the new MessageBus fallback regression test used a callable
  `AsyncMock` instead of an object exposing the `inject_prompt` method required by the
  `SessionInjector` protocol. The test failed before exercising production code; the
  double was corrected and the focused suite now passes.

## Implementation Evidence

- `ExecutionContext` is immutable, runtime-issued, and carries only trace/origin/scope/
  transport/hashed source reference. Prompt text, raw message IDs, credentials, and
  absolute paths are not persisted in the context.
- The same policy evaluator now runs in `CLIService._make_cli()` and
  `infra.task_runner.run_oneshot_task()` before provider construction/command building.
  TaskHub's host-job route invokes the evaluator again at the host boundary, so a future
  resume/recovery caller cannot bypass it.
- Lifecycle startup propagates the confirmed container (including an explicit empty value
  after Docker recovery failure) to CLIService, cron, webhook, and background observers.
  Required scopes therefore cannot use host fallback in production.
- Telegram, Feishu, Matrix, Weixin, QQBot, API, heartbeat, inter-agent, MessageBus,
  TaskHub, cron, webhook, and background paths now preserve provenance. Task persistence
  is additive; old task records receive an explicit `legacy_compat` context at execution.
- `tests/golden/runners/execution_provenance_sandbox.py` generates a ten-case normalized
  matrix from the policy and one-shot production paths. The fixture replaces opaque IDs
  with placeholders and is Schema-validated with exact inventory/drift checks.
- Full-suite first run exposed 35 expected legacy cron/webhook unit assumptions because
  they invoke observers without lifecycle Docker state. A startup-state compatibility
  seam preserves those isolated direct unit calls while production startup marks sandbox
  readiness explicitly. Focused cron/webhook and all messenger suites pass after this
  correction.
- Final envelope audit found team live dispatch/mailbox and MessageBus transport fallback
  paths that could otherwise drop provenance; both now preserve or issue the same
  `BOT_HANDOFF` context before any possible injection.
