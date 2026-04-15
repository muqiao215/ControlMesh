# Findings
- Promotion bridge v1 had the right authority boundary, but safety still depended on several soft assumptions:
  - caller-supplied latest summaries were trusted
  - write-back intent was implicit in free text fields
  - markdown mutation depended on ad hoc section replacement
  - successful writes had no first-class receipt
- The coherent hardening unit is a pack, not another tiny scope.
- Structured write intent makes promotion inspectable before mutation.
- Canonical section writer contracts keep the write surface narrow and reject out-of-contract patches.
- Write-time freshness guard reduces stale snapshot promotion risk by rechecking store snapshots immediately before section patches are applied.
- Promotion receipts make canonical promotion auditable without adding a database or read API.

# Risks Kept Closed
- raw evidence or replay outputs bypassing summary/review and promoting directly
- worker-side promotion shortcuts
- summary snapshots authoring canonical prose directly
- canonical write-back spreading into broader file mutation or automation behavior
- promotion safety hardening becoming orchestrator or transport work
