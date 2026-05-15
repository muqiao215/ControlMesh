#!/usr/bin/env python3
"""Create a bounded monitor cron job with TaskHub-backed defaults.

This is the explicit creation entry for short-lived release/CI monitors.
It is intentionally separate from ``cron_add.py`` so recurring automation
and temporary monitors stay semantically distinct.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import cron_add
from _shared import CRON_TASKS_DIR, JOBS_PATH, load_jobs_or_default, save_jobs

_TEMPLATE_DIR = (
    Path(__file__).resolve().parents[2] / "cron_tasks" / "release-ci-monitor-template"
)
_RULES_TEMPLATE = "RULES-template.md"
_TUTORIAL = """\
CRON MONITOR -- Create a short-lived release/CI monitor.

Use this for temporary high-frequency monitoring that should stop after a
useful terminal state and hand control back to the main conversation.

This entry is different from cron_add.py:
  - recurring cron => stable wall-clock automation
  - monitor cron   => bounded release/CI wait window with TaskHub handoff

Required:
  --name
  --title
  --description
  --schedule

Example:
  python tools/cron_tools/cron_monitor.py \\
      --name "release-ci-watch" \\
      --title "Release CI Monitor" \\
      --description "Watch one release CI run and hand back the next step" \\
      --schedule "*/2 * * * *" \\
      --provider claude \\
      --model sonnet
"""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a bounded monitor cron job with TaskHub defaults",
        epilog="Run without arguments or with --help for the monitor tutorial.",
    )
    parser.add_argument("--name", help="Unique job/folder ID")
    parser.add_argument("--title", help="Short human-readable title")
    parser.add_argument("--description", help="What the monitor watches")
    parser.add_argument("--schedule", help="Cron expression for monitor cadence")
    parser.add_argument("--timezone", help="IANA timezone override")
    parser.add_argument("--provider", choices=list(cron_add.SUPPORTED_PROVIDER_CHOICES))
    parser.add_argument("--model")
    parser.add_argument("--reasoning-effort", choices=["low", "medium", "high", "xhigh"])
    parser.add_argument("--cli-parameters")
    parser.add_argument("--quiet-start", type=int, choices=range(24), metavar="HOUR")
    parser.add_argument("--quiet-end", type=int, choices=range(24), metavar="HOUR")
    parser.add_argument("--dependency")
    parser.add_argument("--delivery-primary")
    parser.add_argument("--delivery-format")
    parser.add_argument("--artifact-mode")
    parser.add_argument("--artifact-path")
    publish_enabled_group = parser.add_mutually_exclusive_group()
    publish_enabled_group.add_argument("--publish-enabled", action="store_true")
    publish_enabled_group.add_argument("--publish-disabled", action="store_true")
    parser.add_argument("--publish-target")
    parser.add_argument("--publish-mode")
    publish_review_group = parser.add_mutually_exclusive_group()
    publish_review_group.add_argument("--publish-require-review", action="store_true")
    publish_review_group.add_argument("--publish-no-review", action="store_true")
    return parser


def _apply_monitor_template(task_dir: Path, *, description: str, schedule: str) -> None:
    rules_source = (_TEMPLATE_DIR / _RULES_TEMPLATE).read_text(encoding="utf-8")
    for name in ("CLAUDE.md", "AGENTS.md", "GEMINI.md"):
        path = task_dir / name
        if path.exists():
            path.write_text(rules_source, encoding="utf-8")

    task_desc_path = task_dir / "TASK_DESCRIPTION.md"
    existing = task_desc_path.read_text(encoding="utf-8") if task_desc_path.exists() else ""
    monitor_block = (
        "\n## Monitor Contract\n\n"
        f"- This is a bounded release/CI monitor.\n"
        f"- Schedule: `{schedule}`\n"
        f"- Description: {description}\n"
        "- Stop after a useful terminal state.\n"
        "- If the run succeeds, resume the main release conversation with the exact next step.\n"
        "- If the run fails, inspect immediately and prefer a narrow repair before handoff.\n"
    )
    if "## Monitor Contract" not in existing:
        task_desc_path.write_text(existing.rstrip() + monitor_block, encoding="utf-8")


def _set_monitor_defaults(job_id: str) -> None:
    data = load_jobs_or_default(JOBS_PATH)
    for job in data.get("jobs", []):
        if job.get("id") != job_id:
            continue
        job["execution_mode"] = "taskhub"
        job["workunit_kind"] = cron_add._DEFAULT_MONITOR_WORKUNIT
        job["risk"] = cron_add._DEFAULT_MONITOR_RISK
        job["output_policy"] = cron_add._DEFAULT_MONITOR_OUTPUT_POLICY
        save_jobs(JOBS_PATH, data)
        return
    msg = f"Monitor job '{job_id}' was created but could not be updated"
    raise RuntimeError(msg)


def _build_cron_add_args(args: argparse.Namespace) -> list[str]:
    built = [
        "--name",
        args.name,
        "--title",
        args.title,
        "--description",
        args.description,
        "--schedule",
        args.schedule,
        "--job-kind",
        "monitor",
    ]
    optional_pairs = (
        ("timezone", args.timezone),
        ("provider", args.provider),
        ("model", args.model),
        ("reasoning-effort", args.reasoning_effort),
        ("cli-parameters", args.cli_parameters),
        ("dependency", args.dependency),
        ("delivery-primary", args.delivery_primary),
        ("delivery-format", args.delivery_format),
        ("artifact-mode", args.artifact_mode),
        ("artifact-path", args.artifact_path),
        ("publish-target", args.publish_target),
        ("publish-mode", args.publish_mode),
    )
    for flag, value in optional_pairs:
        if value:
            built.extend([f"--{flag}", str(value)])
    for flag, value in (("quiet-start", args.quiet_start), ("quiet-end", args.quiet_end)):
        if value is not None:
            built.extend([f"--{flag}", str(value)])
    for flag, enabled in (
        ("publish-enabled", args.publish_enabled),
        ("publish-disabled", args.publish_disabled),
        ("publish-require-review", args.publish_require_review),
        ("publish-no-review", args.publish_no_review),
    ):
        if enabled:
            built.append(f"--{flag}")
    return built


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    missing = [p for p in ("name", "title", "description", "schedule") if not getattr(args, p)]
    if missing:
        print(_TUTORIAL)
        print(f"Missing required parameters: {', '.join('--' + m for m in missing)}")
        sys.exit(1)

    cron_add_args = _build_cron_add_args(args)
    original_argv = sys.argv[:]
    try:
        sys.argv = [str(Path(cron_add.__file__).resolve()), *cron_add_args]
        with redirect_stdout(io.StringIO()):
            cron_add.main()
    finally:
        sys.argv = original_argv

    job_id = cron_add.sanitize_name(args.name)
    task_dir = CRON_TASKS_DIR / job_id
    _apply_monitor_template(task_dir, description=args.description, schedule=args.schedule)
    _set_monitor_defaults(job_id)

    data = load_jobs_or_default(JOBS_PATH)
    job = next(job for job in data["jobs"] if job["id"] == job_id)
    result = {
        "job_id": job_id,
        "job_kind": job.get("job_kind", "monitor"),
        "execution_mode": job.get("execution_mode"),
        "workunit_kind": job.get("workunit_kind"),
        "risk": job.get("risk"),
        "output_policy": job.get("output_policy"),
        "task_folder": f"cron_tasks/{job_id}",
        "template": "release-ci-monitor-template",
        "monitor_entry": "cron_monitor.py",
        "semantic_split": {
            "recurring": "Use cron_add.py for stable schedule-driven automation.",
            "monitor": "Use cron_monitor.py for bounded release/CI wait windows.",
        },
        "handoff_notes": [
            "This monitor defaults to TaskHub-backed background execution.",
            "When the watched target reaches a terminal state, the result is handed back through the main conversation path instead of relying on a foreground watch loop.",
            "Fill in cron_tasks/<name>/TASK_DESCRIPTION.md with the concrete run id, phase, and next-step instructions.",
        ],
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
