# ControlMesh TypeScript Porting Rules

ControlMesh keeps the Python runtime as the reference implementation. TypeScript code may wrap, validate, visualize, or consume Python behavior, but it must not replace runtime behavior without golden parity coverage.

## Allowed Now

- Add JSON Schema protocol contracts under `schemas/controlmesh/v1/`.
- Generate TypeScript types and validators from those schemas.
- Build read-only SDK, dashboard, and facade clients against existing Python API surfaces.
- Add golden fixtures and parity runners that compare against Python output.

## Not Allowed Without Explicit Parity Work

- Rewriting `TaskHub`, provider runners, recovery loops, file-backed memory writes, workspace path resolution, or transport adapters.
- Changing task status strings, provider names, transport names, persisted field names, timestamp units, or artifact path semantics.
- Letting TypeScript write Python runtime private files directly.

## Source Of Truth

- Behavior: Python core wins.
- Cross-language shape: JSON Schema wins.
- Generated files: never edit manually.

Run protocol generation before committing schema changes:

```bash
pnpm generate:protocol
```

Then verify generated files are clean:

```bash
git diff --exit-code packages/controlmesh-protocol/src/generated
```
