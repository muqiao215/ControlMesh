# ControlMesh v0.29.1

This release hardens the v0.29 HostJob line with CI regression fixes and a stricter PyPI publish gate.

## Fixes

- Fixed the `/mesh` workflow regression introduced during the v0.29.0 release sequence.
  - `create_mesh_workflow()` now uses a consistent `source_command` interface across definition and callers.
  - This removes the `NameError` / Ruff `F821` failure that broke the main CI run after `v0.29.0` was tagged.
- Landed the pending lint/test cleanups around the HostJob rollout.
  - Minor typing, import ordering, assertion, and string-format fixes in HostJob runtime and `/mesh` workflow tests are now in `main`.
- Gated PyPI publishing on successful main CI for the tagged commit.
  - Tag-triggered publish no longer proceeds directly to build/upload.
  - The publish workflow now verifies:
    - the git tag matches the package version
    - the tagged commit is reachable from `origin/main`
    - the `CI` workflow for the same `head_sha` completed successfully
  - Only after those checks pass will the build/upload-to-PyPI jobs run.

## Why v0.29.1 exists

`v0.29.0` introduced the HostJob execution boundary, but its release ordering exposed a bad sequence:

1. tag was pushed
2. PyPI publish succeeded
3. main CI later failed on a real `/mesh` regression

`v0.29.1` exists to correct that line:

- the code regression is fixed
- the release mechanism now enforces `CI green -> publish`

## Impact

- `/mesh` phased workflow startup is stable again on the v0.29 line.
- Future PyPI releases cannot bypass a failing main CI run for the same tagged commit.
- The HostJob architecture from `v0.29.0` remains intact; this release tightens correctness around it.
