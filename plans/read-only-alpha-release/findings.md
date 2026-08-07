# Findings

## Requirements

- The alpha must be evaluated from built/installed artifacts in isolated temporary state.
- Documentation must preserve the read-only facade/dashboard boundary and local-only Web
  default.
- Completion requires evidence for versioning, install, minimal usage, checklist, smoke,
  local gates, and final remote CI.

## Research Findings

- The previous CI task established a required protocol/SDK/Web gate and a stable aggregate
  `CI success` check.
- Python metadata is currently `0.41.9` and classified Beta, while private TypeScript/Web
  packages already use `0.41.9-alpha.0`; release-version ownership is inconsistent.
- The tag-triggered publish workflow requires the tag to equal the Python project version,
  proves the tagged SHA belongs to `main`, waits for that SHA's CI, builds/checks wheel and
  sdist, publishes through PyPI trusted publishing, verifies PyPI visibility, and then
  creates the GitHub Release from `docs/release-note-v<version>.md`.
- The existing README describes the stable Python runtime but does not yet give the
  shortest authenticated read-only API/SDK/Web alpha evaluation flow.
- CI builds Python distributions but does not install the built wheel or exercise the
  installed read-only facade in an isolated runtime, so artifact installability and the
  intended Alpha user journey still need direct evidence.
- GitHub's current latest release is `v0.41.9`; its publish workflow succeeded. A new
  read-only alpha must use a new version/tag rather than reusing or moving public history.
- PyPI has no existing prerelease for this project and `0.42.0a1` is available. Python can
  use PEP 440 `0.42.0a1`, while private workspace packages use the semver-equivalent
  `0.42.0-alpha.1` under one documented ControlMesh 0.42.0 Alpha 1 release identity.
- The SDK still exports mutation-shaped methods (`createTask`, `tellTask`, `resumeTask`,
  `cancelTask`, ask-parent response, and doctor POST) that have no supported facade routes.
  A truthful read-only alpha should remove these methods from the public SDK surface rather
  than merely warning users not to call them.
- The production `ApiServer` already registers the complete read-only facade and can bind
  localhost for a smoke harness. A temporary seeded Python state plus actual HTTP requests,
  the real TypeScript SDK, and the built Web preview can verify the end-user path without
  touching operator state.
- The existing Python wheel includes only `controlmesh` and `controlmesh_runtime`; the Web
  build output is ignored and no installed CLI serves it. An alpha installed from PyPI
  would therefore expose the facade but not the promised dashboard. The release needs
  bundled compiled assets plus a localhost-only static launcher.
- Candidate Actions run `31201196298` passed the new installed-wheel smoke and every
  existing required job on GitHub-hosted runners, proving the local release result is not
  host-specific.
- PyPI prereleases appear under `releases[expected]` while `info.version` continues to name
  the latest stable release. Visibility automation must check exact-version files, not
  require a prerelease to replace the stable default.

## Technical Decisions

| Decision | Rationale |
|---|---|

## Issues Encountered

| Issue | Resolution |
|---|---|
| The host does not expose `python` directly | Use `python3` or `uv run python`; release scripts should not assume `python` on the host. |
| A base wheel install cannot import `ApiServer` because PyNaCl is optional | The read-only Alpha install and smoke must use `controlmesh[api]`; keep the optional dependency boundary explicit. |
| Bun does not resolve `@controlmesh/sdk` from a root `scripts/` entrypoint | The repository smoke uses the explicit workspace SDK entrypoint; normal package tests retain workspace package-name resolution. |
| This host exposes `uv` without the `uvx` alias | Release commands use `uv tool run --from twine` so they work with the installed tool surface. |
