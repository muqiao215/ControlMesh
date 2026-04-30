"""Workspace initialization: walk home defaults, copy with zone rules, sync, merge."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
from pathlib import Path

import yaml

from controlmesh.config import deep_merge_config
from controlmesh.infra.atomic_io import atomic_text_save
from controlmesh.memory.store import initialize_memory_v2
from controlmesh.workspace.cron_tasks import ensure_task_rule_files
from controlmesh.workspace.paths import ControlMeshPaths
from controlmesh.workspace.rules_selector import RulesSelector
from controlmesh.workspace.skill_sync import sync_bundled_skills, sync_skills

logger = logging.getLogger(__name__)


# Files that are ALWAYS overwritten on every start (Zone 2).
# Everything else is seeded only once (Zone 3).
_ZONE2_FILES = frozenset({"CLAUDE.md", "AGENTS.md", "GEMINI.md"})

# Directories where ALL .py files are Zone 2 (framework-managed).
# User-owned scripts should go in tools/user_tools/ (Zone 3).
# Paths are relative to home_defaults root (include workspace/ prefix).
_ZONE2_PY_DIRS = frozenset(
    {
        "workspace/tools/cron_tools",
        "workspace/tools/webhook_tools",
        "workspace/tools/agent_tools",
        "workspace/tools/task_tools",
    }
)

# Rule templates are deployed separately by RulesSelector
_SKIP_FILES = frozenset(
    {
        "RULES-claude-only.md",
        "RULES-codex-only.md",
        "RULES-gemini-only.md",
        "RULES-all-clis.md",
        "RULES.md",  # Static templates also handled by RulesSelector
    }
)

_SKIP_DIRS = frozenset({".venv", ".git", ".mypy_cache", "__pycache__", "node_modules"})


# ---------------------------------------------------------------------------
# Home defaults sync (replaces _ensure_dirs + _copy_framework + _seed_defaults)
# ---------------------------------------------------------------------------


def _sync_home_defaults(paths: ControlMeshPaths) -> None:
    """Walk the home-defaults template and copy to ``controlmesh_home``.

    The template at ``<repo>/workspace/`` mirrors ``~/.controlmesh/`` exactly.
    Zone rules per file:

    - **Zone 2** (``_ZONE2_FILES``): always overwritten so framework updates
      reach users on restart.  ``CLAUDE.md`` also produces a matching
      ``AGENTS.md`` mirror automatically.
    - **Zone 3** (everything else): seeded on first run only, never
      overwritten so user modifications persist.
    """
    if not paths.home_defaults.is_dir():
        logger.warning("Home defaults directory not found: %s", paths.home_defaults)
        return
    _walk_and_copy(paths.home_defaults, paths.controlmesh_home)
    # Ensure logs dir exists for the main agent only.  Sub-agents share the
    # central log file and don't need their own logs directory.
    # Sub-agent homes live under <main_home>/agents/<name>/.
    if paths.controlmesh_home.parent.name != "agents":
        paths.logs_dir.mkdir(parents=True, exist_ok=True)


def _should_skip_entry(entry: Path) -> bool:
    """Check if entry should be skipped during workspace sync."""
    return entry.name.startswith(".") or entry.name in _SKIP_DIRS or entry.name in _SKIP_FILES


def _is_zone2_py_file(entry: Path, src: Path, root_src: Path) -> bool:
    """Check if a .py file is in a Zone 2 directory (always overwritten)."""
    if entry.suffix != ".py":
        return False
    try:
        rel_dir = src.relative_to(root_src)
        return str(rel_dir) in _ZONE2_PY_DIRS
    except ValueError:
        return False


def _copy_with_symlink_check(entry: Path, target: Path) -> None:
    """Copy file to target, removing symlink if present."""
    if target.is_symlink():
        target.unlink()
    shutil.copy2(entry, target)


def _handle_zone2_file(entry: Path, target: Path, dst: Path) -> None:
    """Handle Zone 2 file copy (always overwrite) and mirror creation."""
    _copy_with_symlink_check(entry, target)
    logger.debug("Zone 2 copy: %s", target)
    # Auto-create mirrors for every CLAUDE.md (AGENTS.md + GEMINI.md)
    if entry.name == "CLAUDE.md":
        for mirror_name in ("AGENTS.md", "GEMINI.md"):
            mirror_target = dst / mirror_name
            _copy_with_symlink_check(entry, mirror_target)
            logger.debug("Zone 2 copy: %s", mirror_target)


def _handle_regular_file(entry: Path, target: Path, src: Path, root_src: Path) -> None:
    """Handle regular file with Zone 2 .py or Zone 3 logic."""
    if _is_zone2_py_file(entry, src, root_src):
        # Zone 2 .py file: always overwrite (framework-controlled)
        _copy_with_symlink_check(entry, target)
        logger.debug("Zone 2 copy (framework tool): %s", target)
    elif not target.exists():
        # Zone 3: seed only (user-owned, never overwritten)
        shutil.copy2(entry, target)
        logger.debug("Zone 3 seed: %s", target)
    else:
        logger.debug("Zone 3 skip: %s (exists)", target)


def _walk_and_copy(src: Path, dst: Path, root_src: Path | None = None) -> None:
    """Recursively copy *src* tree into *dst* with zone-based overwrite rules.

    Args:
        src: Source directory to copy from
        dst: Destination directory to copy to
        root_src: Root source directory (for calculating relative paths). Defaults to src.
    """
    if root_src is None:
        root_src = src

    dst.mkdir(parents=True, exist_ok=True)
    for entry in sorted(src.iterdir()):
        if _should_skip_entry(entry):
            continue
        target = dst / entry.name
        if entry.is_dir():
            if target.is_symlink():
                logger.debug("Skip symlinked target: %s", target)
                continue
            _walk_and_copy(entry, target, root_src)
        elif entry.name in _ZONE2_FILES:
            _handle_zone2_file(entry, target, dst)
        else:
            _handle_regular_file(entry, target, src, root_src)


# ---------------------------------------------------------------------------
# Rule file sync (CLAUDE.md <-> AGENTS.md)
# ---------------------------------------------------------------------------


_RULE_FILE_NAMES = ("CLAUDE.md", "AGENTS.md", "GEMINI.md")


def sync_rule_files(root: Path) -> None:
    """Recursively sync CLAUDE.md <-> AGENTS.md <-> GEMINI.md by mtime.

    For each directory under root (including root itself):
    - Find the newest rule file among the three by mtime.
    - Copy the newest to all others that exist or are missing.
    - Skip directories in _SKIP_DIRS.
    """
    if not root.is_dir():
        return
    _sync_group(root)
    for dirpath in root.rglob("*"):
        if not dirpath.is_dir():
            continue
        if any(part in _SKIP_DIRS for part in dirpath.parts):
            continue
        _sync_group(dirpath)


def _sync_group(directory: Path) -> None:
    """Sync all rule files (CLAUDE.md, AGENTS.md, GEMINI.md) in a single directory."""
    if _should_skip_git_tracked_rule_root(directory):
        return

    files = {name: directory / name for name in _RULE_FILE_NAMES}
    existing = {name: path for name, path in files.items() if path.exists()}
    if not existing:
        return

    newest_name, newest_path = max(existing.items(), key=lambda item: item[1].stat().st_mtime)
    newest_mtime = newest_path.stat().st_mtime

    for name, path in files.items():
        if name == newest_name:
            continue
        if path.exists() and path.stat().st_mtime < newest_mtime:
            shutil.copy2(newest_path, path)


def _should_skip_git_tracked_rule_root(directory: Path) -> bool:
    """Skip rule sync for git worktree roots with tracked root rule files.

    This prevents the workspace watcher from mutating tracked repo-root
    `CLAUDE.md` / `AGENTS.md` / `GEMINI.md` files inside cloned worktrees.
    """
    git_marker = directory / ".git"
    if not git_marker.exists():
        return False

    for filename in _RULE_FILE_NAMES:
        if not (directory / filename).exists():
            continue
        result = subprocess.run(
            ["git", "-C", str(directory), "ls-files", "--error-unmatch", filename],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return True
    return False


# ---------------------------------------------------------------------------
# Config smart-merge
# ---------------------------------------------------------------------------


def _smart_merge_config(paths: ControlMeshPaths) -> None:
    """Create config from example or merge new keys into existing."""
    if not paths.config_example_path.exists():
        return

    try:
        defaults = json.loads(paths.config_example_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Failed to parse config example: %s", paths.config_example_path)
        return

    if not paths.config_path.exists():
        from controlmesh.infra.json_store import atomic_json_save

        atomic_json_save(paths.config_path, defaults)
        return

    try:
        existing = json.loads(paths.config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Failed to parse config: %s, skipping merge", paths.config_path)
        return
    merged, changed = deep_merge_config(existing, defaults)

    if changed:
        from controlmesh.infra.json_store import atomic_json_save

        atomic_json_save(paths.config_path, merged)


def _merge_seeded_yaml_defaults(target_path: Path, default_path: Path) -> None:
    """Additively merge new bundled YAML defaults into a user-owned seeded file."""
    if not default_path.exists() or not target_path.exists():
        return
    try:
        defaults = yaml.safe_load(default_path.read_text(encoding="utf-8")) or {}
        existing = yaml.safe_load(target_path.read_text(encoding="utf-8")) or {}
    except Exception:
        logger.warning("Failed to parse seeded YAML for migration: %s", target_path)
        return
    if not isinstance(defaults, dict) or not isinstance(existing, dict):
        return
    merged, changed = deep_merge_config(existing, defaults)
    if not changed:
        return
    target_path.write_text(yaml.safe_dump(merged, sort_keys=False), encoding="utf-8")
    logger.info("Workspace migration merged new defaults into %s", target_path)


def _apply_workspace_migrations(paths: ControlMeshPaths) -> None:
    """Apply additive migrations to seeded user-owned workspace files."""
    _smart_merge_config(paths)
    _merge_seeded_yaml_defaults(
        paths.workspace / "routing" / "capabilities.yaml",
        paths.home_defaults / "workspace" / "routing" / "capabilities.yaml",
    )


# ---------------------------------------------------------------------------
# Cleanup helpers
# ---------------------------------------------------------------------------


def _migrate_tasks_to_cron_tasks(paths: ControlMeshPaths) -> None:
    """One-time migration: rename tasks/ to cron_tasks/ if needed."""
    old_tasks = paths.workspace / "tasks"
    if old_tasks.is_dir() and not paths.cron_tasks_dir.exists():
        old_tasks.rename(paths.cron_tasks_dir)
        logger.info("Migrated workspace/tasks/ -> workspace/cron_tasks/")


def _clean_orphan_symlinks(paths: ControlMeshPaths) -> None:
    """Remove broken symlinks in the workspace root."""
    if not paths.workspace.is_dir():
        return
    for entry in paths.workspace.iterdir():
        if entry.is_symlink() and not entry.exists():
            entry.unlink()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


_REQUIRED_DIRS = (
    "workspace",
    "workspace/cron_tasks",
    "workspace/tools",
    "workspace/tools/user_tools",
    "workspace/tools/cron_tools",
    "workspace/tools/media_tools",
    "workspace/tools/webhook_tools",
    "workspace/tools/agent_tools",
    "workspace/output_to_user",
    "workspace/tasks",
    "workspace/skills",
    "config",
)


def _ensure_required_dirs(paths: ControlMeshPaths) -> None:
    """Create any required directories that are missing."""
    for rel in _REQUIRED_DIRS:
        d = paths.controlmesh_home / rel
        if not d.is_dir():
            d.mkdir(parents=True, exist_ok=True)
            logger.info("Created missing directory: %s", d)


def init_workspace(paths: ControlMeshPaths) -> None:
    """Initialize the workspace: defaults sync, rule sync, config merge, cleanup."""
    logger.info("Workspace init started home=%s", paths.controlmesh_home)
    _migrate_tasks_to_cron_tasks(paths)
    sync_bundled_skills(paths)
    _sync_home_defaults(paths)
    _ensure_required_dirs(paths)

    # Deploy provider-specific rule files based on CLI auth status
    try:
        selector = RulesSelector(paths)
        selector.deploy_rules()
    except Exception:
        logger.exception("Failed to deploy rule files")

    ensure_task_rule_files(paths.cron_tasks_dir)
    sync_rule_files(paths.workspace)
    _apply_workspace_migrations(paths)
    _clean_orphan_symlinks(paths)
    sync_skills(paths)
    initialize_memory_v2(paths)
    logger.info("Workspace init completed")


# ---------------------------------------------------------------------------
# Runtime environment injection
# ---------------------------------------------------------------------------

_DOCKER_NOTICE = """

---

## Runtime Environment

**IMPORTANT: YOU ARE RUNNING INSIDE A DOCKER CONTAINER (`{container}`).**

- Your filesystem is isolated. `/controlmesh` is the mounted host directory `~/.controlmesh`.
- You cannot see or access the host system outside this mount.
- Feel free to experiment -- the host is protected.
"""

_HOST_NOTICE = """

---

## Runtime Environment

**WARNING: YOU ARE RUNNING DIRECTLY ON THE HOST SYSTEM. THERE IS NO SANDBOX.**

- Every file operation, command, and script runs on the user's real machine.
- Be careful with destructive commands (`rm -rf`, `chmod`, etc.).
- Ask before touching anything outside `workspace/`.
"""

# ---------------------------------------------------------------------------
# Transport-specific messenger rules
# ---------------------------------------------------------------------------

_TRANSPORT_TELEGRAM = """

---

## Messenger Rules

- Replies are Telegram messages (4096-char limit; auto-split is handled).
- Keep responses mobile-friendly and structured.
- To send files, use `<file:/absolute/path>`.
- Only save generated deliverables in `output_to_user/` when you are explicitly sending a file.
- Do not suggest GUI-only actions like `xdg-open`.

### Quick Reply Buttons

Use button syntax at the end of messages:

- `[button:Label]` markers
- same line = one row
- new line = new row

Keep labels short. Callback data is truncated to 64 bytes by the framework.
Do not place button markers inside code blocks.
"""

_TRANSPORT_MATRIX = """

---

## Messenger Rules

- Replies are Matrix messages (no hard character limit, but keep responses readable).
- Messages are formatted as HTML (Markdown is auto-converted by the framework).
- Keep responses structured and scannable.
- To send files, use `<file:/absolute/path>`.
- Only save generated deliverables in `output_to_user/` when you are explicitly sending a file.
- Do not suggest GUI-only actions like `xdg-open`.
- Commands use `!` prefix (e.g. `!help`, `!status`). \
`/` also works but may conflict with Element's built-in commands.

### Quick Reply Buttons

Use button syntax at the end of messages:

- `[button:Label]` markers
- same line = one row
- new line = new row

In Matrix, buttons are rendered as a numbered text list. The user types \
the label text (or number) to "press" a button — there are no clickable \
inline buttons. Keep labels short and distinctive.
Do not place button markers inside code blocks.
"""

_TRANSPORT_RULES: dict[str, str] = {
    "telegram": _TRANSPORT_TELEGRAM,
    "matrix": _TRANSPORT_MATRIX,
}

# ---------------------------------------------------------------------------
# Multi-Agent identity injection
# ---------------------------------------------------------------------------

_IDENTITY_MAIN = """

---

## Multi-Agent Identity

**You are the MAIN agent (`{name}`).**

- You are the primary agent and coordinator in a multi-agent system.
- You can create, manage, and communicate with sub-agents.
- Each sub-agent has its own **bot** with a separate chat (Telegram or Matrix).

### How the user interacts with sub-agents

The user has TWO ways to use a sub-agent:

1. **Direct chat**: The user opens the sub-agent's bot and chats \
directly. This is the primary way — each sub-agent is a full independent \
assistant with its own memory and workspace.
2. **Delegation via you**: The user asks YOU to delegate a task. You use \
the agent tools below to send the task. The response comes back to YOUR \
chat (never to the sub-agent's chat).

**After creating a sub-agent, always tell the user they can open the \
sub-agent's chat directly to talk to it.** Do not suggest \
Python tool commands to the user — those are for YOU to use internally.

### Agent tools (for YOUR internal use)

- `python3 tools/agent_tools/ask_agent.py TARGET "message"` — sync, blocks
- `python3 tools/agent_tools/ask_agent_async.py TARGET "message"` — async
- Add `--new` before TARGET to start a fresh session (discard prior context)
- `python3 tools/agent_tools/list_agents.py`
- `python3 tools/agent_tools/edit_shared_knowledge.py`

Responses from these tools always come back to YOU, never to the sub-agent's chat.
Use async for tasks that may take more than a few seconds.

When you delegate a task asynchronously, the sub-agent processes it in a \
Named Session called `ia-{name}`. The user can continue that session \
in the sub-agent's chat via `@ia-{name} <message>`. When \
reporting results to the user, mention this session name so they know \
how to follow up directly with the sub-agent.
"""

_IDENTITY_SUB = """

---

## Multi-Agent Identity

**You are agent `{name}` (sub-agent).**

- You are a specialized sub-agent in a multi-agent system.
- The main agent coordinates the overall system.
- You have your own workspace, memory, and {transport} bot.

### Communication Tools

- **Synchronous**: `python3 tools/agent_tools/ask_agent.py TARGET "message"` — blocks until response, answer returned to you
- **Asynchronous**: `python3 tools/agent_tools/ask_agent_async.py TARGET "message"` — returns immediately, answer delivered back to YOUR chat when ready
- **Fresh session**: Add `--new` before the target to discard prior context: `ask_agent_async.py --new TARGET "message"`

**Important**: Responses always come back to the calling agent, never to \
a different chat. There is no way to send answers to another agent's \
chat via these tools.

### Inter-Agent Named Sessions

When another agent sends you a message, it runs in a **Named Session** \
called `ia-{{sender}}` (e.g. `ia-main`). These sessions:

- Preserve context across multiple messages from the same sender agent
- Run in the background, independent of your direct chat
- Are visible to the user via `/sessions` and can be continued \
manually with `@ia-{{sender}} <message>` in your chat

When you receive an `[INTER-AGENT MESSAGE]` marker, respond directly \
and concisely. If the user asks about running tasks or background \
sessions, check `/sessions` or `named_sessions.json` for active \
inter-agent sessions.
"""


def _build_identity_notice(agent_name: str, transport: str) -> str:
    """Build the identity section for rule files."""
    if agent_name == "main":
        return _IDENTITY_MAIN.format(name=agent_name)
    transport_label = transport.capitalize()  # "telegram" → "Telegram"
    return _IDENTITY_SUB.format(name=agent_name, transport=transport_label)


def inject_runtime_environment(
    paths: ControlMeshPaths,
    *,
    docker_container: str,
    agent_name: str = "main",
    transport: str = "telegram",
) -> None:
    """Append transport rules, agent identity, and runtime environment to rule files.

    Called once after workspace init when the Docker state and transport are known.
    """
    env_notice = (
        _DOCKER_NOTICE.format(container=docker_container) if docker_container else _HOST_NOTICE
    )
    identity_notice = _build_identity_notice(agent_name, transport)
    transport_notice = _TRANSPORT_RULES.get(transport, _TRANSPORT_TELEGRAM)

    for name in _RULE_FILE_NAMES:
        target = paths.workspace / name
        if not target.exists():
            continue
        content = target.read_text(encoding="utf-8")
        # Avoid duplicate injection on restart without workspace re-init
        if "## Multi-Agent Identity" in content or "## Runtime Environment" in content:
            continue
        atomic_text_save(target, content + transport_notice + identity_notice + env_notice)
    logger.info(
        "Runtime environment injected: %s agent=%s transport=%s",
        "docker" if docker_container else "host",
        agent_name,
        transport,
    )


_RULE_SYNC_INTERVAL = 10.0  # seconds


async def watch_rule_files(workspace: Path, *, interval: float = _RULE_SYNC_INTERVAL) -> None:
    """Continuously sync CLAUDE.md <-> AGENTS.md <-> GEMINI.md across the workspace.

    Every *interval* seconds:
    1. ``ensure_task_rule_files`` adds missing rule files to existing cron
       tasks (e.g. GEMINI.md after a new provider was authenticated).
    2. ``sync_rule_files`` propagates content changes across all rule files.
    """
    cron_tasks_dir = workspace / "cron_tasks"
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(ensure_task_rule_files, cron_tasks_dir)
            await asyncio.to_thread(sync_rule_files, workspace)
        except Exception:
            logger.exception("Rule file sync failed")
