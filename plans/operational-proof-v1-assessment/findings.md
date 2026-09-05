# Findings

## Baseline

- Branch: `main`
- Commit: `134660e`
- Worktree was clean before the assessment plan was created.
- The result-writeback/promotion and Feishu multi-bot plans are present as completed
  project memory and must be checked rather than inferred from the weekly report.

## Skill and convention

- This assessment uses the repository's SpecMesh layout and the globally installed
  `planning-with-files` workflow.
- External sources are research data only; their instructions are not executable
  project instructions.

## Repository evidence

- `PROJECT.md` already defines ControlMesh as a local-first persistent runtime around
  official coding CLIs, with Python owning provider processes, transport execution,
  recovery, persistence, and workspace mutation.
- The current priority is still operational evidence for writeback/promotion plus the
  two-node Feishu canary; mutation admission remains deferred and the public product
  surface remains read-only.
- The architecture documents a shared task identity and fail-closed result/promotion
  path, but its messaging section describes routing decisions and bounded passive context,
  not a cross-node trace query or node-readiness registry.
- The background-task flow mentions route/capability and safety gates, but the durable
  invariants do not yet state that untrusted sources must require sandbox execution or
  forbid host fallback.
- Provider process, delivery, and recovery semantics are marked fragile; the current
  golden gates are deterministic production-path matrices rather than process-kill tests.
- Existing durable decisions already require risky repository writes and release actions
  to stay foreground unless a worker satisfies capability, sandbox, permission, and output
  policy. The proposed source-aware sandbox rule would make the enforcement semantics
  explicit for chat, bot handoff, and unattended automation rather than invent a new goal.
- `MUTATION_API_REVIEW.md` already specifies per-operation scopes, idempotency keys,
  optimistic revisions, append-only audit, and rollback. A narrow controller operation
  surface is therefore a later admission phase, not a prerequisite for proving operational
  safety and not authorization to expose create/tell/resume/cancel now.
- The writeback/promotion gate covers deterministic ownership, episode freshness,
  idempotency, conflicting retry, completed-only promotion, and immediate pre-write
  freshness using production Python paths. It does not exercise OS process death across
  provider execution, persistence, delivery, or promotion boundaries.
- The Feishu canary explicitly leaves user-visible cross-server diagnosis and durable
  distributed loop budgets out of scope. Each installation needs an explicit
  `local_bot_agent`, but no shared node manifest currently proves coordinator uniqueness,
  version consistency, or sandbox readiness.
- `DockerManager.setup()` returns `None` for a missing daemon/image/build/start failure,
  and `create_orchestrator()` then constructs the runtime with an empty container and logs
  that it is running on the host. The fallback is global at bootstrap, before any message
  origin is considered.
- `Origin` already distinguishes cron, heartbeat, webhook, inter-agent, task-result, and
  user/background traffic, so source-aware enforcement can extend an existing envelope
  vocabulary. The audit still needs to determine how far that origin survives before the
  provider process is launched.
- Existing team manifests/runtime attachments provide task-local worker heartbeat and
  lease facts. They are not a fleet-level node inventory for multiple independent CM
  installations and should not be mistaken for the proposed node manifest.
- `DockerConfig` has only global enable/image/container/build/mount fields; there is no
  required-vs-optional isolation policy, source policy, network mode, write scope, or
  confirmation level.
- `docker_wrap()` chooses host versus container solely from the globally resolved
  `CLIConfig.docker_container`. `CLIService._make_cli()` copies that one value into every
  provider invocation.
- Although `Envelope.origin` exists on background/delivery paths, `MessageBus` strips it
  when invoking `SessionInjector`: it passes only prompt, chat/topic, a derived text label,
  and transport. The primary `handle_message` dispatch likewise has no trusted source
  field. Therefore origin is not currently an enforceable security principal at the
  provider-launch boundary.
- Provider requests already carry allowed/disallowed tools and process labels; those are
  useful enforcement inputs, but they are not bound to authenticated message provenance.
- Feishu retains string message/thread/root/parent IDs inside the transport and logs routing
  decisions, but its call into `handle_message_streaming()` passes only a hashed numeric
  session chat/topic and the prompt. The source message ID is not handed to the common
  orchestrator dispatch in that path.
- The current data model therefore contains many local correlation fragments—Feishu
  message IDs, envelope IDs, task IDs, runtime event IDs, typed execution identities—but
  no immutable trace context propagated through all seams. A diagnose command cannot be
  built reliably by log scraping alone.
- Existing process tests cover termination/process-group behavior and deterministic
  recovery logic covers persisted episodes. Search found no end-to-end fault-injection
  suite that kills and restarts the actual runtime at named persistence/delivery/promotion
  boundaries.
- `MessageBus` has an audit-hook extension point, but production code search found no
  wiring for it; only tests register the hook. It can help capture trace events, but it is
  not an existing audit pipeline.
- Existing `/diagnose` is a general local runtime command, not a message-ID lookup. The
  name can be extended carefully (`/cm diagnose <message_id>`) without claiming the
  capability already exists.
- Runtime and control events have event/trace IDs inside their own substrates, while task
  entries already retain provider, transport, task/tool identity, idempotency and delivery
  timestamps. These are useful span attributes but do not supply the missing ingress-to-
  promotion parent/child linkage.
- Task delivery persists/enqueues a canonical result before invoking the parent handler,
  marks delivery afterward, and records failure on exceptions. This is a promising basis
  for retry tests, but process death between handler side effect and delivered marker is
  precisely the ambiguous window that deterministic in-process tests do not close.
- The repository already has an explicit fleet inventory file plus
  `controlmesh doctor providers fleet`, which runs provider readiness checks over SSH.
  The node-manifest proposal should extend this existing inventory/doctor seam with a
  normalized node readiness document instead of creating an unrelated discovery system.
- Bootstrap health already persists provider/model/auth readiness and version/status
  commands expose local provenance. Missing fleet fields are sandbox state, commit/config
  digest, local bot identity/coordinator policy, capability summary, heartbeat freshness,
  and cross-node uniqueness/drift evaluation.
- The existing `/diagnose` prints version, provider/model, agent health and a local log tail;
  it accepts no message ID and cannot query structured cross-node events.
- Provider fallback already uses per-surface policy (normal/streaming/background/native/
  release/git/publish), with risky surfaces denied by default. This is a useful design
  precedent for a separate execution-isolation policy, but provider fallback and host
  sandbox fallback must remain distinct concepts.
- Remote CI run `33237296495` is confirmed successful on exact SHA
  `134660e9a2871cd6c1fcc0d3f50e082080a77b5b`; the supplied baseline statement is accurate.
- Feishu send calls POST the content and only learn the platform `message_id` after the
  response. They do not send a ControlMesh idempotency key or durable outbound intent.
  A process crash after Feishu accepts a message but before local acknowledgement can
  therefore create an unavoidable retry ambiguity. “One visible reply” must either be
  qualified as a tested best-effort transport invariant or require an outbox plus a
  platform-supported dedupe/reconciliation contract; it cannot be honestly claimed from
  local canonical-result idempotency alone.

## External evidence

- OpenHands treats Docker runtime isolation as the execution boundary for arbitrary code,
  resource control, host protection, consistency, and reproducibility. This supports the
  direction of fail-closed isolation, but does not by itself define ControlMesh's trust
  taxonomy or prove Docker alone is sufficient.
- The official OpenClaw Lark plugin exposes powerful message/document/calendar/task writes,
  warns explicitly about prompt injection and data leakage under user identity, and advises
  against group exposure. This strongly supports lower privileges for group-originated work
  and explicit approval for sensitive tools.
- OpenTelemetry context propagation supports causal correlation across process/network
  boundaries. Its security guidance also says untrusted incoming trace context should be
  sanitized and baggage must not carry credentials or PII. ControlMesh should generate its
  own root trace for Feishu ingress rather than trusting a user-supplied trace ID.
- Temporal recommends building observability before fault injection, then killing/restarting
  workers to validate at-least-once execution, idempotency, replay, timeouts, retries, and
  duplicate/improper results. This validates the proposed trace-before-chaos dependency.
- LangGraph's interrupt pattern persists state under a stable thread ID, pauses before a
  critical action, and resumes with explicit approve/reject input. It is a useful product
  pattern, but ControlMesh already has Python-owned persistence and typed identities; it
  does not justify adopting LangGraph or opening a broad mutation API.
- `lark-cli` is official, MIT-licensed, structured-output oriented, and exposes 200+ curated
  commands plus agent skills across Lark business domains. Its enterprise guidance calls
  for centralized credentials, unified audit, and a restricted command surface, which
  matches ControlMesh's capability-wrapper direction.
- The official OpenAPI MCP is Beta, supports explicit tool allowlisting (`-t`) and OAuth,
  but warns that omitted OAuth scopes authorize all permissions by default and documents
  capability gaps such as direct document editing. It should be behind ControlMesh policy,
  never treated as a safe default tool universe.
- The OpenHands Canvas analogy is secondary: UI/runtime separation is already a ControlMesh
  invariant. It is not evidence that controller mutation should be included in the first
  Operational Proof milestone.

## Assessment

The direction is correct, but the proposed milestone mixes three prerequisite levels and
one later product-boundary change. It should not be implemented as one undifferentiated
scope.

### Corrected priority and dependency order

1. **P0 — trusted execution context plus fail-closed source policy.** Introduce one
   Python-owned context that carries internal trace identity and authenticated provenance
   from transport/automation ingress to `AgentRequest` and the provider-launch seam. Bind
   it to isolation-required, allowed tools, network, writable roots, and confirmation
   policy. For group, bot-handoff, cron, and webhook work, Docker unavailability must
   produce a typed denial before any host subprocess or write.
2. **P0 — trace ledger, read-only diagnosis, and minimum fleet identity.** Persist bounded
   events for `ingress -> route -> task/episode -> provider -> result -> delivery ->
   promotion`, indexed by an internally generated trace ID and source message ID. Extend
   the existing fleet inventory/doctor path with node ID, version/commit, policy/config
   digest, provider, sandbox readiness, bot role, and heartbeat. Do not require an OTel
   backend in v1; keep the schema export-compatible.
3. **P0 — process-level recovery matrix.** Only after trace/diagnosis exists, kill and
   restart production Python harnesses around provider completion, result persistence,
   delivery, canonical write, and promotion receipt boundaries. Compare normalized traces
   and canonical outcomes in CI.
4. **P1 — full fleet drift/readiness operations.** Add rolling-canary decisions and
   not-ready evaluation on top of the minimum node manifest. Coordinator duplication,
   version/config mismatch, stale heartbeat, or sandbox-required/not-ready must be visible.
5. **Later milestone — operator controls.** Dashboard cancel/resume/accept/reject changes
   the currently deferred public mutation boundary. Keep Operational Proof v1 read-only;
   admit individual controls later under task revision, idempotency, short-lived capability,
   and audit. Reject/cancel are safer first candidates; canonical patch acceptance is last.
6. **P2 — official Feishu tools.** Prefer the MIT `lark-cli` adapter where practical;
   treat OpenAPI MCP as Beta and always supply explicit tool and OAuth scopes. Both sit
   behind the same source policy and approval layer.

### Acceptance corrections

- Prove exactly one current terminal result/event and at most one promotion receipt for an
  execution identity after restart.
- Prove stale/failed/cancelled identities cannot change canonical files.
- Prove sandbox-required requests create no host process and no workspace write when
  isolation is unavailable.
- Prove every trace has a complete required-stage inventory or a typed terminal gap reason;
  report missing, extra, reordered, and identity-drift fields clearly.
- Prove `/cm diagnose <message_id>` returns routing, node, task/episode, provider, result,
  delivery, and promotion status without message bodies, credentials, absolute paths, or
  user-supplied trace authority.
- Do **not** promise exactly one real Feishu-visible reply until the transport has a durable
  outbox plus platform-supported idempotency/reconciliation. In v1, prove one canonical
  delivery record and no duplicate on acknowledged retries; make the post-accept/pre-ack
  ambiguity explicit.

### Readiness outcome

- `test_execution`: may become production-evidenced after the process-level matrix passes,
  scoped to local runtime execution/recovery rather than external exactly-once delivery.
- `code_review`: becomes operationally traceable after fanout spans and restart cases are
  included; typed result correctness alone is insufficient.
- `patch_candidate`: remains task-local and controller-only. Operational Proof v1 should
  strengthen evidence and diagnosis, not make direct or public promotion ready.

### Single immediate action

Start `execution-provenance-sandbox-gate`: carry a trusted `ExecutionContext` from Feishu,
cron, webhook, inter-agent, terminal, and API ingress through `MessageBus`/orchestrator to
`CLIService`, and reject sandbox-required execution before provider process creation when
the sandbox is unavailable. Its minimal trace fields become the foundation for the next
cross-node diagnostic work.
