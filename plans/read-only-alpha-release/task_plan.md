# Task: Read-only Alpha Release

## Goal

Prepare and execute a reproducible read-only ControlMesh alpha release: establish the
release version, prove clean installation, publish minimal usage documentation, add a
release checklist, and run a real-environment smoke test without weakening Python runtime
ownership or read-only product boundaries.

## Context

The read-only Python facade, TypeScript SDK, and local Web dashboard are implemented and
enforced by CI. The next project priority is turning that verified baseline into an alpha
that another user can install, start, and evaluate.

## Requirements

- Determine and consistently apply an appropriate alpha version across release surfaces.
- Verify installation from built artifacts in isolated environments, not the source tree.
- Document the shortest supported setup, startup, authentication, SDK, and Web flow.
- Provide a concrete release checklist with exact commands and pass/fail evidence.
- Exercise the installed alpha in a real temporary runtime environment, including the
  read-only facade and Web/SDK path, while proving no private paths or mutation APIs leak.
- Run all relevant local gates, push the completed work, and verify remote CI on final HEAD.

## Non-goals

- Do not push the release tag until the final `main` commit passes the complete release
  checklist and required CI.
- Do not add mutation APIs, move runtime ownership to TypeScript, or enable non-local Web
  access.
- Do not redesign packaging beyond changes required for a reproducible alpha installation.

## Plan

- [x] Audit version sources, package artifacts, startup paths, and release workflows.
- [x] Define the alpha release contract and update version/documentation surfaces.
- [x] Add or repair reproducible installation and real-environment smoke verification.
- [x] Execute release checklist and the relevant full local gates.
- [x] Update durable project memory and task evidence.
- [x] Commit, push, and verify GitHub Actions on final HEAD.

## Success

- One documented alpha version is consistent across intended release artifacts.
- Fresh isolated installs can start and exercise supported read-only behavior.
- Minimal user docs and a command-level checklist are accurate and independently usable.
- Local release evidence and final remote CI are green.
- Worktree is clean and matches `origin/main`.

## Status

Complete. The Alpha is published and the post-release main branch is green.

## Next Step

Begin the Python task-lifecycle golden parity matrix plan.

## Decisions Made

| Decision | Rationale |
|---|---|
| Publish only through the existing `v*` tag → PyPI → GitHub Release workflow after final gates | The requested release has an established approved target and automation; delaying the tag preserves the release gate. |
| Use ControlMesh 0.42.0 Alpha 1 (`0.42.0a1` Python, `0.42.0-alpha.1` private TS packages) | It is the next unused line after stable 0.41.9 and follows each ecosystem's canonical prerelease syntax. |
| Remove unsupported mutation-shaped SDK methods for the read-only alpha | Public client capability must match registered production routes; documentation alone would leave a false API promise. |
| Ship compiled dashboard assets inside the Python wheel and expose `controlmesh dashboard` on localhost | A PyPI/pipx alpha is not evaluable if its dashboard exists only in the source workspace; local static serving preserves the security boundary. |

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| Host has no bare `python` executable during live release metadata query | 1 | Use `python3` or `uv run python`, matching repository toolchain policy. |
| Audit referenced nonexistent `schemas/controlmesh/v1/openapi.yaml` | 1 | Locate the actual schema inventory with `rg --files` before reading the contract. |
| First focused Ruff run stopped on four style findings | 1 | Remove exception-constructor parentheses, an ignored-rule `noqa`, and a single-quoted test literal; rerun the same focused gate. |
| Second expanded Ruff run rejected a try/except KeyboardInterrupt pass | 1 | Use `contextlib.suppress(KeyboardInterrupt)` around the standalone server loop. |
| First isolated-wheel smoke could not import `nacl` | 1 | Install the built wheel with its documented `[api]` extra so the production `ApiServer` dependency contract is exercised exactly. |
| Second smoke could not resolve `@controlmesh/sdk` from a repository-root script | 2 | Import the workspace SDK through its explicit source entrypoint; package-name resolution is scoped to package consumers/tests, not arbitrary root scripts. |
| First architecture documentation patch used mismatched duplicate context | 1 | Locate exact repository-map and entry-point lines, then apply smaller section-specific edits. |
| Expanded focused Ruff rejected the test's all-interface literal and regex dots | 1 | Use a documentation-only non-loopback address and an explicitly escaped match pattern. |
| Host has `uv` but no standalone `uvx` executable for Twine | 1 | Use the equivalent portable form `uv tool run --from twine twine check` and update the checklist. |
| Prerelease visibility job waited for `info.version == 0.42.0a1` even though PyPI correctly kept stable `0.41.9` as latest | 1 | Confirmed `releases["0.42.0a1"]` has both files, created the verified GitHub prerelease manually, cancelled the impossible wait, and changed future verification to require files under the exact release key. |
| `gh release view` does not support the requested `isLatest` JSON field | 1 | Verify prerelease status through supported `isPrerelease` output and stable latest through `gh release list`. |
