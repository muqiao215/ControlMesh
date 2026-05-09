# ControlMesh Background Task Routing Hardening Plan

Date: 2026-05-09
Scope: P0/P1 redesign plan for routing safety and worker eligibility

## Goal

Refactor ControlMesh background task routing so delegation decisions are made from explicit intent, risk, capability, permission, sandbox, and output-policy gates, with unsafe work held in the foreground by default.

## Files

- `controlmesh/routing/workunit.py`: extend WorkUnit/requirements to carry risk, side effects, runtime-provider hints, and output constraints
- `controlmesh/routing/policy.py`: replace coarse text-first routing with explicit intent classification and protected release/publish distinctions
- `controlmesh/routing/router.py`: add foreground-forcing gates before slot scoring
- `controlmesh/routing/activation.py`: make activation policies advisory only after safety checks pass
- `controlmesh/routing/capabilities.py`: extend slot schema with `sandbox`, `approval_policy`, `cwd`, `visible_paths`, `tools`, and `output_policy`
- `controlmesh/orchestrator/core.py`: pass richer intent metadata from foreground orchestration into routing
- `controlmesh/tasks/hub.py`: preserve execution/result separation and enforce summary-only background delivery
- `controlmesh/bus/adapters.py`: close remaining raw-event/result leakage paths
- `controlmesh/_home_defaults/workspace/routing/activation_policies.yaml`: remove coarse default auto-background rules for high-risk work
- `controlmesh/_home_defaults/workspace/routing/capabilities.yaml`: declare trusted worker contracts explicitly
- `docs/modules/agent_routing.md`: document the new routing safety model, worker contract, and release split
- tests under `tests/routing/`, `tests/orchestrator/`, `tests/tasks/`, and `tests/bus/`

## Phased Plan

### Phase 1: P0 Stopgap Protection
- Keep `github_release` and similar high-risk work in the foreground by default.
- Remove or neutralize activation-policy rules that auto-background release/publish language.
- Add tests proving release-like discussion text does not auto-launch a background publish flow.

### Phase 2: Intent and Risk Model
- Introduce explicit routing intent fields:
  - `risk`
  - `side_effects`
  - `required_caps`
  - `requires_user_approval`
  - `output_policy`
- Map existing WorkUnit kinds onto that model.
- Encode the P0 policy:
  - repo write, git write, publish, release creation, and external write force foreground unless a trusted worker is explicitly approved.

### Phase 3: Worker Eligibility Contract
- Extend worker slots to declare:
  - `sandbox`
  - `approval_policy`
  - `cwd`
  - `visible_paths`
  - `tools`
  - `capabilities`
  - `output_policy`
  - `mode`
- Distinguish read-only explorer/reviewer workers from write/publish workers.
- Reject routing to any slot that cannot satisfy the declared contract.

### Phase 4: Runtime-Backed Provider Resolution and Health
- For runtime-backed providers, resolve model in this order:
  1. explicit task submit model
  2. route capability model
  3. live runtime discovery
  4. static fallback
- Add early diagnostic errors such as:
  - `missing_model_for_runtime_provider`
  - `runtime_provider_unhealthy`
  - `worker_repo_visibility_denied`
- Do not let these cases degrade into one-hour timeouts.

### Phase 5: Output Containment
- Enforce `summarized_only` background delivery.
- Keep internal payloads available in artifacts/logs but strip them from user-visible delivery.
- Audit every delivery path so raw event JSON and internal resume artifacts cannot leak into foreground chat.

### Phase 6: Release Workflow Split
- Split release-related work into:
  - `release_plan`
  - `release_prep`
  - `release_publish`
  - `release_verify`
- Allow background prep/review only when worker contracts allow it.
- Keep `release_publish` foreground unless a specifically trusted publish worker is configured and user approval is present.

### Phase 7: Config and Seed Consistency
- Define clear precedence across:
  - dev repo defaults
  - seeded workspace files
  - installed runtime config
  - live mutable overrides
- Ensure restart does not silently restore unsafe routing defaults over deliberate operator overrides.

### Phase 8: Verification and Incremental Release
- Focus tests on:
  - force-foreground gates
  - worker eligibility rejection
  - runtime-backed model resolution
  - summary-only output delivery
  - live config precedence
- Release in small bounded patches instead of one large routing rewrite.

## Locked Design Rules

- Codex subagents are opt-in only; no automatic subagent creation without explicit user request.
- High-risk tasks are not eligible for automatic background delegation.
- Activation policy does not override safety gates.
- Worker selection is capability- and permission-based, not provider-name-based.
- Background delivery must be summary-only.
- Multi-agent shared task-list collaboration is deferred until after P0/P1 safety work is stable.

## Immediate Next Action

Land the smallest safe checkpoint first:
1. formalize `force_foreground(intent)`
2. extend worker-slot eligibility checks
3. keep release/publish paths foreground by default
4. add regression tests for the current failures
