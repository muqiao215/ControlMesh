# Progress

## Current

Canary patch merged onto current `main`; local verification complete.

## Completed

- Isolated work on a clean branch based on `origin/main` at `6d52099`.
- Read project ownership instructions and Feishu group/handoff implementation.
- Compared the current Python transport with the official Channel SDK sender/mention/loop
  semantics.
- Defined the canary scope and acceptance contract.
- Added typed group policy, explicit local identity validation, exact mention/reply
  metadata, coordinator/target/broadcast routing, and a bounded bot-loop guard.
- Added passive transcript observations and bounded context injection.
- Preserved existing reply/thread targeting and bypassed the older logical-agent handoff
  when real multi-bot mode owns routing.
- Added canary configuration and security/rollback documentation for
  `oc_cdf6d69446db7e9e480067de4f309192`.
- Focused regression: 157 passed.
- Repository Ruff gate: passed.
- Full regression: 5566 passed; one unrelated existing host-job process-group test failed
  because the child PID remained observable after cancellation in this container. Neither
  `controlmesh/runtime/` nor `tests/runtime/test_host_jobs.py` differs from the baseline.
- Verified downloaded ZIP SHA-256
  `a60dbb12049aebb7d236d068d3d5b84d6c2ba777ba8f2b6de69dcd98cd554ec2` and every entry in
  its `MANIFEST.sha256` before applying.
- Applied cleanly on current `main` at `ee8e2bf`; no manual conflict resolution or source
  snapshot overwrite was needed.
- Current-tree focused verification: 283 passed; full Ruff passed; full Python regression:
  5569 passed with no failures.
- Final diff check found no credentials, real bot open IDs, absolute paths, caches, or build
  output. Multi-bot mode remains disabled by default.

## Remaining

- Resolve real bot open IDs as observed by each Feishu app before enabling the canary.
- Run the documented two-node live group checklist before distributing to every server.
- A user-facing cross-server message diagnostic report and a durable distributed loop
  budget remain deliberately outside this patch.
