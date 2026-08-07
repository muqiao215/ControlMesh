# Release Checklist

This checklist is the command-level gate for ControlMesh releases. Run it from a clean
`main` checkout. For the current read-only Alpha, `VERSION=0.42.0a1` and
`TAG=v0.42.0a1`.

## 1. Identity and State

```bash
git status --short
git fetch origin main --tags
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)"
test "$(git tag -l "$TAG")" = ""
```

Confirm `pyproject.toml` and `controlmesh/__init__.py` use `$VERSION`, private workspace
packages use the semver equivalent `0.42.0-alpha.1`, and
`docs/release-note-$TAG.md` exists.

## 2. Generated and Static Assets

```bash
pnpm install --frozen-lockfile
pnpm check:protocol
pnpm --filter @controlmesh/web build
git diff --exit-code -- \
  packages/controlmesh-protocol/src/generated \
  packages/controlmesh-protocol/src/validators \
  controlmesh/protocol/generated \
  controlmesh/web_static
```

## 3. Product and Runtime Gates

```bash
pnpm test:golden
pnpm test:sdk
uv run ruff check .
uv run python -m pytest -q -W error::RuntimeWarning
bash scripts/smoke_read_only_alpha.sh
```

The smoke must prove:

- import and metadata come from an isolated wheel installation;
- authenticated task/event/provider/artifact reads succeed over real HTTP;
- private/absolute paths and symlink escapes do not appear;
- SDK mutation methods are absent and mutation HTTP routes reject requests;
- the dashboard is served from assets bundled in that wheel.

## 4. Distribution

```bash
uv build
uv tool run --from twine twine check dist/*
python3 -m zipfile -l "dist/controlmesh-$VERSION-py3-none-any.whl" \
  | grep 'controlmesh/web_static/index.html'
scripts/release_github.sh "$TAG" --dry-run
```

## 5. Push and Release

Commit and push the release preparation. Wait for the final commit's `CI success` check,
then execute:

```bash
scripts/release_github.sh "$TAG" --branch main
```

The tag workflow is authoritative for PyPI publishing and GitHub Release creation. A
prerelease tag must create a GitHub prerelease and must not replace the stable “Latest”
release.

## 6. Post-release Evidence

```bash
gh run list --workflow publish.yml --branch "$TAG" --limit 1
gh release view "$TAG"
python3 - <<'PY'
import json
import urllib.request

with urllib.request.urlopen("https://pypi.org/pypi/controlmesh/json") as response:
    releases = json.load(response)["releases"]
assert "0.42.0a1" in releases
print("PyPI contains controlmesh 0.42.0a1")
PY
```

Record exact commands, results, run URLs, and remaining risks in the active task's
`progress.md` before closing it.
