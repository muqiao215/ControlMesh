# ControlMesh v0.39.1

This release keeps the packaged hotfix support from `v0.39.0` and adds the follow-up fixes needed to get the release line back onto a passing CI/publish path.

## Highlights

- Fixes lint issues in the hotfix packaging and upgrade flow changes.
- Aligns Docker wrapper test expectations with the current `IS_SANDBOX=1` container env injection.
- Preserves the packaged hotfix runtime model introduced in `v0.39.0`.

## Verification

- GitHub Actions `CI` workflow on `main`
- GitHub Actions `Publish to PyPI` workflow on tag `v0.39.1`

## Upgrade Notes

- `v0.39.0` remains the failed release candidate commit.
- Use tag `v0.39.1` for the corrected public release and PyPI publish path.
