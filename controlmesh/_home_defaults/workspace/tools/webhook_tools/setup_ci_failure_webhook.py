#!/usr/bin/env python3
"""Enable webhook listener and register the GitHub CI failure task hook."""

from __future__ import annotations

import json
import secrets
from pathlib import Path

from _shared import CONFIG_PATH, HOOKS_PATH


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    config = _load_json(CONFIG_PATH)
    webhooks_cfg = dict(config.get("webhooks") or {})
    token = str(webhooks_cfg.get("token") or "").strip()
    if not token or token == "disabled":
        token = secrets.token_urlsafe(24)
    webhooks_cfg.update(
        {
            "enabled": True,
            "host": "0.0.0.0",
            "port": 8742,
            "token": token,
            "max_body_bytes": int(webhooks_cfg.get("max_body_bytes") or 262144),
            "rate_limit_per_minute": int(webhooks_cfg.get("rate_limit_per_minute") or 30),
        }
    )
    config["webhooks"] = webhooks_cfg
    _save_json(CONFIG_PATH, config)

    hooks_doc = _load_json(HOOKS_PATH)
    hooks = list(hooks_doc.get("hooks") or [])
    hook_id = "github-ci-failed"
    existing = next((h for h in hooks if h.get("id") == hook_id), None)
    hook_token = secrets.token_urlsafe(24)
    hook = {
        "id": hook_id,
        "title": "GitHub CI Failed",
        "description": "Create a background triage task for failed CI runs",
        "mode": "task",
        "prompt_template": (
            "Repository: {{repo}}\n"
            "Ref: {{ref}}\n"
            "SHA: {{sha}}\n"
            "Workflow: {{workflow}}\n"
            "Actor: {{actor}}\n"
            "Run URL: {{run_url}}\n"
            "Lint: {{lint_result}}\n"
            "Test: {{test_result}}\n"
            "Build: {{build_result}}\n"
            "Synthetic failure: {{synthetic_failure_result}}\n\n"
            "Summarize the CI failure, identify the concrete broken tests or lint issues, "
            "and propose the next smallest code fix."
        ),
        "enabled": True,
        "task_folder": None,
        "auth_mode": "bearer",
        "token": existing.get("token", hook_token) if existing else hook_token,
        "hmac_secret": "",
        "hmac_header": "",
        "hmac_algorithm": "sha256",
        "hmac_encoding": "hex",
        "hmac_sig_prefix": "sha256=",
        "hmac_sig_regex": "",
        "hmac_payload_prefix_regex": "",
        "created_at": existing.get("created_at", "") if existing else "",
        "trigger_count": int(existing.get("trigger_count", 0)) if existing else 0,
        "last_triggered_at": existing.get("last_triggered_at") if existing else None,
        "last_error": existing.get("last_error") if existing else None,
        "provider": "codex",
        "model": "gpt-5.5",
        "reasoning_effort": "high",
        "cli_parameters": [],
        "quiet_start": None,
        "quiet_end": None,
        "dependency": None,
        "task_name": "CI failure triage",
        "parent_agent": "main",
        "task_transport": "telegram",
        "workunit_kind": "test_execution",
        "topology": "pipeline",
        "route": "auto",
    }
    if existing is None:
        hooks.append(hook)
    else:
        hooks[hooks.index(existing)] = hook
    hooks_doc["hooks"] = hooks
    _save_json(HOOKS_PATH, hooks_doc)

    print(
        json.dumps(
            {
                "status": "ok",
                "webhooks_enabled": True,
                "listener": "http://0.0.0.0:8742",
                "hook_id": hook_id,
                "hook_endpoint": f"/hooks/{hook_id}",
                "hook_token": hook["token"],
                "repo_secret_url_hint": "http://<PUBLIC_OR_TAILSCALE_HOST>:8742/hooks/github-ci-failed",
                "repo_secret_token_hint": hook["token"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
