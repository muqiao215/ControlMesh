# ControlMesh v0.42.0a1

This prerelease makes the authenticated read-only product layer installable and
independently evaluable without changing Python runtime ownership.

## Highlights

- Ships the compiled local dashboard inside the Python wheel.
- Adds `controlmesh api serve`, a standalone read-only facade/dashboard server restricted
  to `127.0.0.1`.
- Exposes authenticated task, event, provider, topology, artifact metadata, and safe
  artifact-content reads through `/api/v1`.
- Removes unsupported task mutation methods from the Alpha TypeScript SDK surface.
- Adds a required CI smoke that installs the wheel in an isolated environment, exercises
  real HTTP through the SDK, checks path containment and mutation rejection, and loads the
  bundled dashboard.

## Install Alongside Stable

```bash
pipx install --suffix=-alpha "controlmesh[api]==0.42.0a1"
controlmesh-alpha api serve
```

See [Read-only Alpha](read-only-alpha.md) for the five-minute evaluation flow.

## Boundaries

- The Alpha is local-only and read-only.
- Python remains authoritative for task/runtime mutation and persistence.
- TypeScript workspace packages remain private and are not published independently.
- Remote dashboard deployment, browser credential policy, and mutation APIs are not part
  of this release.

## Validation

- Full Python suite with runtime warnings promoted to errors.
- Ruff, protocol synchronization, provider/protocol goldens, SDK smoke, and Web build.
- Isolated wheel installation and real-environment read-only Alpha smoke.
