# Findings

## Repository State

- Baseline commit `e3368b9` is clean and contains the canonical Python lifecycle matrix.
- `@controlmesh/runtime-facade` is private and currently contains only generic HTTP/SSE
  helpers; it has no mutation methods and is the narrowest suitable internal TypeScript seam.
- The public SDK and Web consume the authenticated read-only Python facade and must remain
  unchanged except for negative surface tests if needed.

## Matrix Contract

- The canonical matrix has 14 cases across create, tell, ask_parent, resume, cancel,
  recovery, workspace, and artifact.
- Expected observations contain state, stable error messages, persisted update ordering,
  workspace-relative paths, artifact metadata/content, and containment failures.
- A compliant candidate must compute these observations from case inputs or a separate
  executable case specification; reading and returning `expected` would be circular.

## Decisions

| Decision | Rationale |
|---|---|
| Add explicit case inputs to the matrix contract | A cross-language consumer cannot independently execute behavior from an operation label and expected output alone. |
| Keep Python as rollback owner even after a green candidate gate | Parity evidence is admission evidence, not an ownership migration approval. |
| Use an in-memory candidate behind the private runtime-facade package | It independently exercises lifecycle semantics without writing production files or crossing the Python ownership boundary. |
| Diff recursively by JSON path and count missing/extra cases separately | Reviewers and CI need actionable drift evidence, not a single unequal boolean. |
| Commit a digest-bound rollback gate artifact | Admission can be tied to the exact Python matrix while retaining deterministic review and fail-closed CI. |
| Bump the input-bearing matrix to v2 | Requiring case inputs is a breaking envelope change; keeping the already-committed v1 identifier would misrepresent compatibility. |

## Implemented Evidence

- The TypeScript candidate independently matches all 14 Python cases across all eight
  domains.
- Intentional value drift reports `/event_types/0`; missing and extra cases fail separately.
- The dual runner regenerates the Python oracle in-process, rejects committed-matrix drift,
  runs the TypeScript candidate, and checks a SHA-256-bound rollback gate.
- JSON Schema validates both the lifecycle matrix and rollback gate.
- OpenAPI has only GET operations; SDK prototype tests prove create/tell/resume/cancel are
  absent after candidate admission.
- Final bundle review caught that exporting the candidate from the runtime-facade barrel
  caused it to enter the public Web bundle. The export was removed; parity tools use the
  private module path and the bundled dashboard remains unchanged.
- `MUTATION_API_REVIEW.md` records authorization, idempotency/concurrency, audit, and
  rollback requirements without approving a public surface.
