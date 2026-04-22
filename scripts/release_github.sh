#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/release_github.sh vX.Y.Z [options]

Options:
  --branch <name>       Branch to push before pushing the tag (default: current branch)
  --commit <rev>        Commit to tag (default: HEAD)
  --title <title>       GitHub Release title (default: tag)
  --notes-file <path>   Release notes file passed to gh release create
  --skip-gate           Skip the public release gate
  --skip-tests          Skip pytest
  --skip-build          Skip uv build
  --dry-run             Print the validated plan without mutating git or GitHub
  -h, --help            Show this help

Rules:
  - This script creates or verifies the local annotated tag first.
  - It pushes the branch and tag separately.
  - It verifies the remote tag commit before creating the GitHub Release.
  - It always uses gh release create --verify-tag.
  - It refuses to move an existing remote tag to a different commit.
EOF
}

die() {
  echo "error: $*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

require_clean_worktree() {
  if [[ -n "$(git status --short)" ]]; then
    die "working tree is not clean; commit or stash changes before releasing"
  fi
}

verify_version_matches_tag() {
  local tag="$1"
  local expected="${tag#v}"

  python3 - "$expected" <<'PY'
import pathlib
import re
import sys

expected = sys.argv[1]
pyproject = pathlib.Path("pyproject.toml").read_text(encoding="utf-8")
init_py = pathlib.Path("controlmesh/__init__.py").read_text(encoding="utf-8")

project_match = re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE)
init_match = re.search(r'^__version__ = "([^"]+)"', init_py, re.MULTILINE)
if not project_match or not init_match:
    raise SystemExit("failed to read version from pyproject.toml or controlmesh/__init__.py")

project_version = project_match.group(1)
init_version = init_match.group(1)
if project_version != init_version:
    raise SystemExit(
        f"version mismatch: pyproject.toml={project_version} vs controlmesh/__init__.py={init_version}"
    )
if project_version != expected:
    raise SystemExit(f"tag/version mismatch: tag expects {expected} but project version is {project_version}")

print(f"version OK: {project_version}")
PY
}

remote_tag_commit() {
  local tag="$1"
  local peeled
  peeled="$(git ls-remote origin "refs/tags/${tag}^{}" | awk '{print $1}')"
  if [[ -n "$peeled" ]]; then
    printf '%s\n' "$peeled"
    return 0
  fi

  git ls-remote --refs origin "refs/tags/${tag}" | awk '{print $1}'
}

tag=""; branch=""; commit_ref="HEAD"; title=""; notes_file=""
skip_gate=0; skip_tests=0; skip_build=0; dry_run=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --branch)
      [[ $# -ge 2 ]] || die "--branch requires a value"
      branch="$2"
      shift 2
      ;;
    --commit)
      [[ $# -ge 2 ]] || die "--commit requires a value"
      commit_ref="$2"
      shift 2
      ;;
    --title)
      [[ $# -ge 2 ]] || die "--title requires a value"
      title="$2"
      shift 2
      ;;
    --notes-file)
      [[ $# -ge 2 ]] || die "--notes-file requires a value"
      notes_file="$2"
      shift 2
      ;;
    --skip-gate)
      skip_gate=1
      shift
      ;;
    --skip-tests)
      skip_tests=1
      shift
      ;;
    --skip-build)
      skip_build=1
      shift
      ;;
    --dry-run)
      dry_run=1
      shift
      ;;
    -*)
      die "unknown option: $1"
      ;;
    *)
      if [[ -n "$tag" ]]; then
        die "unexpected extra argument: $1"
      fi
      tag="$1"
      shift
      ;;
  esac
done

[[ -n "$tag" ]] || {
  usage
  exit 1
}
[[ "$tag" =~ ^v[0-9]+(\.[0-9]+){1,2}([.-][A-Za-z0-9]+)?$ ]] || die "tag must look like vX.Y.Z"

require_cmd git
require_cmd gh
require_cmd python3
require_cmd uv

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

branch="${branch:-$(git rev-parse --abbrev-ref HEAD)}"
title="${title:-$tag}"
commit="$(git rev-parse "$commit_ref")"

require_clean_worktree
gh auth status >/dev/null
verify_version_matches_tag "$tag"

if [[ -n "$notes_file" && ! -f "$notes_file" ]]; then
  die "notes file does not exist: $notes_file"
fi

if git rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
  local_target="$(git rev-list -n 1 "$tag")"
  [[ "$local_target" == "$commit" ]] || die "local tag $tag points to $local_target, expected $commit"
  [[ "$(git cat-file -t "$tag")" == "tag" ]] || die "local tag $tag exists but is not annotated"
else
  if [[ "$dry_run" -eq 1 ]]; then
    echo "dry-run: would create annotated tag $tag at $commit"
  else
    git tag -a "$tag" "$commit" -m "$tag"
  fi
fi

existing_remote_commit="$(remote_tag_commit "$tag")"
if [[ -n "$existing_remote_commit" && "$existing_remote_commit" != "$commit" ]]; then
  die "remote tag $tag already points to $existing_remote_commit, expected $commit; refusing to rewrite public history"
fi

echo "release branch: $branch"
echo "release tag: $tag"
echo "release commit: $commit"

if [[ "$skip_gate" -eq 0 && -f /root/.codex/skills/public-repo-release-gate/scripts/public_release_gate.py ]]; then
  [[ "$dry_run" -eq 1 ]] || python3 /root/.codex/skills/public-repo-release-gate/scripts/public_release_gate.py . --final
fi

if [[ "$skip_tests" -eq 0 ]]; then
  [[ "$dry_run" -eq 1 ]] || pytest -q
fi

if [[ "$skip_build" -eq 0 ]]; then
  [[ "$dry_run" -eq 1 ]] || uv build
fi

if [[ "$dry_run" -eq 1 ]]; then
  echo "dry-run: would push branch $branch"
  if [[ -z "$existing_remote_commit" ]]; then
    echo "dry-run: would push tag $tag"
  fi
else
  git push origin "$branch"
  if [[ -z "$existing_remote_commit" ]]; then
    git push origin "$tag"
  fi
fi

verified_remote_commit="${existing_remote_commit:-}"
if [[ "$dry_run" -eq 0 ]]; then
  verified_remote_commit="$(remote_tag_commit "$tag")"
  [[ -n "$verified_remote_commit" ]] || die "remote tag $tag was not found after push"
  [[ "$verified_remote_commit" == "$commit" ]] || die "remote tag $tag points to $verified_remote_commit, expected $commit"
fi

if [[ "$dry_run" -eq 1 ]]; then
  echo "dry-run: would run gh release create $tag --verify-tag"
  exit 0
fi

release_exists=0
if gh release view "$tag" >/dev/null 2>&1; then
  release_exists=1
fi

if [[ "$release_exists" -eq 1 ]]; then
  die "GitHub Release $tag already exists; use gh release edit after verifying the existing release intentionally"
fi

release_args=(
  "$tag"
  --verify-tag
  --title "$title"
)

if [[ -n "$notes_file" ]]; then
  release_args+=(--notes-file "$notes_file")
else
  release_args+=(--generate-notes)
fi

gh release create "${release_args[@]}"
gh release view "$tag" --json url,name,tagName,isDraft,isPrerelease
