# TypeScript Migration Decision Log

## 0001: Keep Python Runtime Authoritative

Decision: TypeScript starts at protocol, SDK, facade, and dashboard layers. Python remains the runtime reference.

Reason: Current risk is runtime behavior drift, not lack of TypeScript syntax. Task state, provider process handling, memory writes, and transport delivery require parity fixtures before any port.

## 0002: JSON Schema Is The Cross-Language Contract

Decision: Cross-language DTOs are defined as JSON Schema under `schemas/controlmesh/v1/`.

Reason: JSON Schema can feed TypeScript generation, runtime validation, OpenAPI, and Python validation without creating parallel hand-written model sets.

## 0003: Identify Artifact Downloads By Task And Relative Path

Decision: The artifact download operation is `GET /api/v1/tasks/{task_id}/artifacts/content?relative_path=...`. The query value must exactly match a `relative_path` returned by the task artifact metadata facade. The task folder is the only filesystem allowlist root, including when persisted per-agent `tasks_dir` is used.

Reason: `controlmesh.artifact.v1` has no stable `artifact_id`, and clients must never construct or send absolute filesystem paths. The alpha SDK scaffold method using `/api/v1/artifacts/{artifact_id}/download` is unsupported and does not define server behavior.

The operation was registered only after the security matrix in `ARTIFACT_DOWNLOAD_CONTRACT.md` passed. It authenticates before path or resource inspection and streams from an already validated open file handle rather than asking `FileResponse` to reopen a pathname.
