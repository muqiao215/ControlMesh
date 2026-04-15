# Confirmed Facts
- the autonomous runtime loop existed, but it did not yet expose a bounded operational control surface
- `signal/query/update` is enough to make the runtime externally operable without widening into a second runtime or heavier infrastructure
- append-only `ControlEvent` records plus trace/span identity make the new control surface observable without letting observations mutate canonical truth
- `PromotionController.reconcile()` keeps canonical mutation controller-owned above review plus latest summaries
- the CLI control surface remains narrow: `controlmesh runtime run|signal|query|update`
- repo-wide verification is green on top of this pack: `3941 passed, 3 skipped` plus clean `ruff`

# Risks
- future control-surface work can still drift if packet, plan, worker, and trace identity constraints are relaxed
- `already_promoted` idempotency is currently anchored on the latest task/line summary pair; any broader idempotency model should open as a separate hardening scope
- future ingress work can still sprawl if CLI is used as a wedge toward daemonization, broader transport ingress, or dashboard work

# Deferred
- daemon/system wiring
- broader transport/provider ingress
- multi-worker orchestration
- SQLite
- broad query or dashboard work
- further control-surface identity hardening beyond this pack

# Decision Records
- 2026-04-15: Close `Runtime Control Surface Pack` as one bounded implementation package over the existing autonomous runtime loop instead of creating a second runtime.
