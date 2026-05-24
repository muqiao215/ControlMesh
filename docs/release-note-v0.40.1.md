# ControlMesh v0.40.1

This patch release fixes installed-version detection when package metadata is not available, such as direct source checkouts or partially editable environments.

## Highlights

- Falls back to `controlmesh.__version__` when `importlib.metadata.version("controlmesh")` cannot find installed package metadata.
- Keeps the final fallback at `0.0.0` only when neither package metadata nor the module version is available.
- Adds regression coverage for both fallback paths.

## Verification

- `ruff check .`
- `pytest tests/infra/test_version.py`: 30 passed

## Upgrade Notes

- Push tag `v0.40.1` to trigger the existing GitHub Actions `Publish to PyPI` workflow.
- GitHub Release creation remains gated on successful PyPI publication and PyPI visibility.
