"""Central path resolution for the workspace layout.

This module is the SINGLE SOURCE OF TRUTH for all paths in the framework.
Every path the framework needs is either a field or property of ``ControlMeshPaths``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# controlmesh/workspace/paths.py -> controlmesh/workspace -> controlmesh
_PKG_DIR = Path(__file__).resolve().parent.parent


def _default_home_defaults() -> Path:
    return _PKG_DIR / "_home_defaults"


def _default_framework_root() -> Path:
    return _PKG_DIR.parent


@dataclass(frozen=True)
class ControlMeshPaths:
    """Resolved, immutable paths for the workspace layout.

    All framework paths are derived from three roots:

    - ``controlmesh_home``:    User data directory (default ``~/.controlmesh``).
    - ``home_defaults``:  Bundled template that mirrors ``controlmesh_home`` (package-internal).
    - ``framework_root``: Repository root (for Dockerfile, config.example.json).
    """

    controlmesh_home: Path
    home_defaults: Path = field(default_factory=_default_home_defaults)
    framework_root: Path = field(default_factory=_default_framework_root)

    # -- User data paths (inside controlmesh_home) --

    @property
    def workspace(self) -> Path:
        return self.controlmesh_home / "workspace"

    @property
    def config_dir(self) -> Path:
        return self.controlmesh_home / "config"

    @property
    def config_path(self) -> Path:
        return self.config_dir / "config.json"

    @property
    def sessions_path(self) -> Path:
        return self.controlmesh_home / "sessions.json"

    @property
    def cron_jobs_path(self) -> Path:
        return self.controlmesh_home / "cron_jobs.json"

    @property
    def webhooks_path(self) -> Path:
        return self.controlmesh_home / "webhooks.json"

    @property
    def logs_dir(self) -> Path:
        return self.controlmesh_home / "logs"

    @property
    def cron_tasks_dir(self) -> Path:
        return self.workspace / "cron_tasks"

    @property
    def tools_dir(self) -> Path:
        return self.workspace / "tools"

    @property
    def output_to_user_dir(self) -> Path:
        return self.workspace / "output_to_user"

    @property
    def telegram_files_dir(self) -> Path:
        return self.workspace / "telegram_files"

    @property
    def matrix_files_dir(self) -> Path:
        return self.workspace / "matrix_files"

    @property
    def feishu_files_dir(self) -> Path:
        return self.workspace / "feishu_files"

    @property
    def api_files_dir(self) -> Path:
        return self.workspace / "api_files"

    @property
    def memory_system_dir(self) -> Path:
        return self.workspace / "memory_system"

    @property
    def skills_dir(self) -> Path:
        return self.workspace / "skills"

    @property
    def bundled_skills_dir(self) -> Path:
        """Package-internal skill directory (read-only, ships with controlmesh)."""
        return self.home_defaults / "workspace" / "skills"

    @property
    def tasks_dir(self) -> Path:
        """Per-task metadata folders (TASKMEMORY.md etc.)."""
        return self.workspace / "tasks"

    @property
    def team_state_dir(self) -> Path:
        """Canonical additive team state root under the workspace."""
        return self.workspace / "team-state"

    @property
    def tasks_registry_path(self) -> Path:
        """Task registry persistence."""
        return self.controlmesh_home / "tasks.json"

    @property
    def transcripts_dir(self) -> Path:
        """Frontstage-visible transcript storage root."""
        return self.controlmesh_home / "transcripts"

    @property
    def runtime_events_dir(self) -> Path:
        """Dedicated backstage runtime-event storage root."""
        return self.controlmesh_home / "runtime-events"

    @property
    def history_index_path(self) -> Path:
        """Derived SQLite history index (never authoritative)."""
        return self.workspace / ".history" / "index.sqlite3"

    @property
    def team_control_snapshots_dir(self) -> Path:
        """Derived compact control-plane snapshots (never authoritative)."""
        return self.workspace / ".team-snapshots"

    @property
    def chat_activity_path(self) -> Path:
        return self.controlmesh_home / "chat_activity.json"

    @property
    def named_sessions_path(self) -> Path:
        return self.controlmesh_home / "named_sessions.json"

    @property
    def startup_state_path(self) -> Path:
        return self.controlmesh_home / "startup_state.json"

    @property
    def inflight_turns_path(self) -> Path:
        return self.controlmesh_home / "inflight_turns.json"

    @property
    def env_file(self) -> Path:
        """User-managed ``.env`` for external API secrets."""
        return self.controlmesh_home / ".env"

    @property
    def mainmemory_path(self) -> Path:
        """Legacy compatibility memory path, created lazily when compat sync needs it."""
        return self.memory_system_dir / "MAINMEMORY.md"

    @property
    def authority_memory_path(self) -> Path:
        """Canonical long-term memory authority for the additive memory-v2 layer."""
        return self.workspace / "MEMORY.md"

    @property
    def dream_diary_path(self) -> Path:
        """Dream diary markdown for cross-day synthesis output."""
        return self.workspace / "DREAMS.md"

    @property
    def memory_v2_daily_dir(self) -> Path:
        """Per-day memory notes used by memory-v2."""
        return self.workspace / "memory"

    @property
    def memory_v2_machine_state_dir(self) -> Path:
        """Machine-managed dreaming state under ``memory/.dreams``."""
        return self.memory_v2_daily_dir / ".dreams"

    @property
    def dreaming_sweep_state_path(self) -> Path:
        return self.memory_v2_machine_state_dir / "sweep_state.json"

    @property
    def dreaming_checkpoints_path(self) -> Path:
        return self.memory_v2_machine_state_dir / "checkpoints.json"

    @property
    def dreaming_lock_path(self) -> Path:
        return self.memory_v2_machine_state_dir / "dreaming.lock.json"

    @property
    def memory_promotion_log_path(self) -> Path:
        return self.memory_v2_machine_state_dir / "promotion_log.json"

    @property
    def memory_search_index_path(self) -> Path:
        return self.memory_v2_machine_state_dir / "search.sqlite3"

    @property
    def dreaming_sweep_log_path(self) -> Path:
        return self.memory_v2_machine_state_dir / "sweep_log.jsonl"

    @property
    def join_notification_path(self) -> Path:
        return self.workspace / "JOIN_NOTIFICATION.md"

    # -- Framework paths (bundled with package or repo root) --

    @property
    def config_example_path(self) -> Path:
        """Config example: repo root (dev) or package-bundled (installed)."""
        repo_path = self.framework_root / "config.example.json"
        if repo_path.is_file():
            return repo_path
        return _PKG_DIR / "_config_example.json"

    @property
    def dockerfile_sandbox_path(self) -> Path:
        """Dockerfile.sandbox: repo root (dev) or package-bundled (installed)."""
        repo_path = self.framework_root / "Dockerfile.sandbox"
        if repo_path.is_file():
            return repo_path
        return _PKG_DIR / "_Dockerfile.sandbox"


def resolve_paths(
    controlmesh_home: str | Path | None = None,
    *,
    framework_root: str | Path | None = None,
    home_defaults: str | Path | None = None,
) -> ControlMeshPaths:
    """Build ControlMeshPaths from explicit values, env vars, or defaults.

    Args:
        controlmesh_home: User data directory. Falls back to ``$CONTROLMESH_HOME`` or ``~/.controlmesh``.
        framework_root: Repository root. Falls back to ``$CONTROLMESH_FRAMEWORK_ROOT``.
        home_defaults: Template directory. Falls back to ``controlmesh/_home_defaults/``.
    """
    if controlmesh_home is not None:
        home = Path(controlmesh_home).expanduser().resolve()
    else:
        home = (
            Path(
                os.environ.get("CONTROLMESH_HOME", str(Path.home() / ".controlmesh")),
            )
            .expanduser()
            .resolve()
        )

    if framework_root is not None:
        fw = Path(framework_root).expanduser().resolve()
    else:
        env_fw = os.environ.get("CONTROLMESH_FRAMEWORK_ROOT")
        fw = Path(env_fw).resolve() if env_fw else _default_framework_root()

    hd = Path(home_defaults).resolve() if home_defaults is not None else _default_home_defaults()

    return ControlMeshPaths(controlmesh_home=home, home_defaults=hd, framework_root=fw)
