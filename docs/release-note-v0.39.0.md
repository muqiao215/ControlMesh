# ControlMesh v0.39.0

This release adds packaged hotfix support so source-direct runtime fixes can be sealed into a managed install instead of leaving the daemon on bare source imports.

## Highlights

- Source-direct and editable runtimes can now be sealed into a packaged hotfix wheel.
- Runtime status and startup provenance now distinguish official package, packaged hotfix, and source-direct states.
- Upgrade flow refuses to silently overwrite packaged hotfixes and keeps hotfix provenance explicit.

## Verification

- `python3 -m pytest /root/ControlMesh/tests/infra/test_install.py /root/ControlMesh/tests/infra/test_updater.py /root/ControlMesh/tests/test_main.py -q`

## Upgrade Notes

- Release this version with tag `v0.39.0`; `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.39.0`.
- Public publishing should continue through the existing GitHub Actions `Publish to PyPI` workflow triggered by pushing `v0.39.0`.
