# Findings
- The completion-pack promotion bridge already created a first bounded canonical write surface, but it still carried execution plan/result coupling from the pack-era runtime closure.
- The narrowest post-summary hardening cut is to accept only:
  - review facts
  - latest task summary
  - latest line summary
- Latest summaries should remain promotion provenance, not direct authors of canonical prose.
- Promotion eligibility should be explicit and inspectable before any file write; otherwise the bridge remains an opaque write helper.
- The canonical write-back target for v1 should stay narrow:
  - `plans/<line>/task_plan.md`
  - `plans/<line>/progress.md`
- `findings.md` is intentionally kept out of this cut so latest summaries do not immediately become durable long-horizon facts without a separate adjudication scope.
- `progress.md #Notes` should preserve human text and only host a replaceable machine-owned provenance block.

# Risks Kept Closed
- raw evidence or replay outputs bypassing summary/review and promoting directly
- worker-side promotion shortcuts
- summary snapshots being mistaken for direct canonical truth
- canonical write-back spreading into broader file mutation or automation behavior
