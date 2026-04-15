# Confirmed Facts
- The colab line is not active in the current repository tranche.
- ControlMesh autonomous rounds still require a canonical file set for parked lines.

# Blockers
- The line has not been opened for implementation in this repo.

# Risks
- Missing canonical placeholders would break controller round reads.

# Deferred
- all colab-specific implementation work in this repository

# Decision Records
- 2026-04-09: register colab as a parked canonical line while history is active_primary.
