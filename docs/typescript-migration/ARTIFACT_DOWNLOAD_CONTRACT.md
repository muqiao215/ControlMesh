# Artifact Download Contract

Status: implemented and exposed after all security gates passed.

Requirements: `MW-003`, `MW-004`, `MW-005`, `MW-006`, `OS-002`, `NFR-002`.

## Public Operation

```http
GET /api/v1/tasks/{task_id}/artifacts/content?relative_path=generated%2FEVIDENCE.json
Authorization: Bearer <token>
```

`relative_path` is the exact POSIX-style value returned by `GET /api/v1/tasks/{task_id}/artifacts`. It is not an absolute path, URL, file URI, artifact ID, or client-derived workspace path.

The alpha SDK scaffold route `/api/v1/artifacts/{artifact_id}/download` is unsupported because `controlmesh.artifact.v1` has no `artifact_id`. It must not be implemented or treated as compatibility surface.

## Resolution Order

The future handler must perform these steps in order:

1. Verify the Bearer token before task lookup, path parsing, or filesystem access.
2. Look up `task_id` through the existing derived catalog and return `TASK_NOT_FOUND` when absent.
3. Decode `relative_path` once and reject empty values, absolute POSIX paths, Windows drive or UNC paths, NUL/control characters, backslashes, and `.` or `..` path segments.
4. Read the persisted task folder through `AdminHistoryCatalogReader.task_folder()`. Do not instantiate `TaskRegistry`.
5. Recompute the safe artifact metadata allowlist and require an exact `relative_path` match.
6. Open the matched regular file without following a final symlink, then verify the opened object still belongs to the resolved task folder. Do not reopen the file by pathname after validation.
7. Stream the validated handle with MIME determined by Python. Set a safe attachment filename, `Cache-Control: no-store`, and `X-Content-Type-Options: nosniff`.

The task folder is the sole allowlist root. Global `/files` configuration, including `file_access=all`, cannot widen it. Missing, unreadable, non-regular, allowlist-missing, or containment-failing candidates return the same `ARTIFACT_NOT_FOUND` 404 envelope so the endpoint does not disclose filesystem state.

Invalid lexical paths return `INVALID_ARTIFACT_PATH` with HTTP 400. Missing or wrong tokens return `PERMISSION_DENIED` with HTTP 401. Error envelopes use `controlmesh.error.v1` and must not contain absolute paths.

## Security Test Matrix

Every row is required before the production route or a supported SDK method is added.

| ID | Boundary | Required proof |
|---|---|---|
| AD-AUTH-001 | Authentication | Missing Authorization header returns 401 `PERMISSION_DENIED`. |
| AD-AUTH-002 | Authentication | Wrong Bearer token returns 401 `PERMISSION_DENIED`. |
| AD-AUTH-003 | Authentication | Correct Bearer token is required before resource resolution. |
| AD-AUTH-004 | Authentication order | Invalid or secret-looking paths without auth still return 401 without path details. |
| AD-PATH-001 | Empty input | Missing or empty `relative_path` returns 400 `INVALID_ARTIFACT_PATH`. |
| AD-PATH-002 | POSIX absolute path | `/etc/passwd` and file URI forms are rejected before filesystem access. |
| AD-PATH-003 | Windows absolute path | Drive, UNC, and backslash-separated paths are rejected on every host OS. |
| AD-PATH-004 | Traversal | Plain, percent-encoded, and mixed `..` segments are rejected after one decode. |
| AD-PATH-005 | Invalid bytes | NUL and control characters are rejected without exception leakage. |
| AD-PATH-006 | Non-disclosure | Success headers and all error bodies contain no absolute task or artifact path. |
| AD-TASK-001 | Missing task | Unknown `task_id` returns 404 `TASK_NOT_FOUND`. |
| AD-DIR-001 | Custom task root | Persisted per-agent `tasks_dir` works without constructing `TaskRegistry`. |
| AD-ALLOW-001 | Allowlist hit | Exact metadata `relative_path` for a regular readable file downloads successfully. |
| AD-ALLOW-002 | Allowlist miss | A path absent from the safe metadata list returns 404 `ARTIFACT_NOT_FOUND`. |
| AD-ALLOW-003 | File type | Directories and other non-regular objects are not downloadable. |
| AD-SYMLINK-001 | Final symlink escape | A file symlink resolving outside the task folder returns 404. |
| AD-SYMLINK-002 | Parent symlink escape | A symlinked directory resolving outside the task folder cannot be traversed. |
| AD-SYMLINK-003 | TOCTOU replacement | Replacing an allowlisted file with an external symlink before open cannot leak bytes. |
| AD-FILE-001 | Missing race | A file removed between allowlist construction and open returns 404. |
| AD-FILE-002 | Permissions | An unreadable file returns 404 without failing the request or leaking its path. |
| AD-MIME-001 | Content type | Successful content type follows Python MIME detection with octet-stream fallback. |
| AD-MIME-002 | Response headers | Attachment filename is injection-safe; `nosniff` and `no-store` are present. |

## Exposure Gate

Before registering the operation, the implementation work unit must:

1. Add automated tests for every matrix ID and link those IDs to test names.
2. Run the Python facade/security gates and the SDK/Web gates if those layers change.
3. Remove `x-controlmesh-status: planned` only after all cases pass.
4. Update migration status and the active task's `progress.md` in the same work unit;
   promote durable architecture or decisions only when they changed.

The production route is registered with `HEAD` disabled and remains gated by every matrix case.

## Implementation Progress

The unregistered safe-open primitive in `controlmesh/api/artifact_access.py` now has explicit test links for 16 cases:

- `AD-PATH-001` through `AD-PATH-005`;
- `AD-TASK-001` and `AD-DIR-001`;
- `AD-ALLOW-001` through `AD-ALLOW-003`;
- `AD-SYMLINK-001` through `AD-SYMLINK-003`;
- `AD-FILE-001`, `AD-FILE-002`, and `AD-MIME-001`.

`AD-AUTH-001` through `AD-AUTH-004`, `AD-PATH-006`, and `AD-MIME-002` are covered by `tests/api/test_artifact_download_http.py`. All 22 cases are automated and the route is active.
