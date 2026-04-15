# Confirmed Facts
- the runtime already had checkpointing, summaries, and promotion as separate capabilities, but not one bounded autonomous chain that ran them in order
- controller-approved automatic promotion can stay narrow by reusing summary promotion and refusing any non-controller authority
- a minimal in-process scheduler is enough to prove drain-until-idle behavior without widening into daemon/system work

# Risks
- future automation work can still sprawl if this pack is used as a wedge toward transport ingress or daemon/system integration
- automatic promotion must remain constrained to the existing controller-approved summary-promotion path or authority drift will return

# Deferred
- transport/CLI ingress
- daemon/system wiring
- broader trigger plumbing across external inputs
- multi-worker orchestration

# Decision Records
- 2026-04-15: Close `Autonomous Runtime Loop Pack` as one bounded implementation package instead of splitting scheduler, triggers, and automatic promotion into smaller scopes.
