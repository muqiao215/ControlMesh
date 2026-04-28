# ControlMesh v0.24.0

Compared to `v0.23.6`, this release moves ControlMesh forward as a more unified
chat task runtime: memory is simplified, native command routing is more
explicit, task evaluation gained stronger scoring/evidence paths, and the
Telegram `/start` surface is now productized for bilingual onboarding.

## Highlights

- Unified durable memory around `MEMORY.md` as the primary authority, removing
  the old `MAINMEMORY.md` compatibility path from the main runtime flow.
- Added native command registry and workunit evaluation support so provider
  routing, fallback ownership, and task scoring behave more consistently across
  transports.
- Hardened background task tool bootstrap so routing scripts no longer depend
  on ad-hoc `PYTHONPATH` injection just to normalize provider aliases.
- Refreshed Telegram `/start` onboarding with a new bilingual welcome image and
  Chinese-first copy while keeping quick-start buttons and callback flows intact.
- Updated Codex fallback behavior to default to `gpt-5.5` when the preferred
  target is unavailable.

## Upgrade Notes

- Release this version with tag `v0.24.0`; `pyproject.toml` and
  `controlmesh/__init__.py` are aligned to `0.24.0`.
- If you rely on durable memory docs or automation prompts, treat `MEMORY.md`
  as the canonical long-term memory file.
- Telegram operators will see a new `/start` presentation immediately after
  upgrade; no config migration is required.

## Verification

- Full release pytest suite is expected as part of the formal release flow.
- Focused Telegram welcome regression coverage:
  `uv run --python 3.12 --extra dev pytest -q tests/messenger/telegram/test_welcome.py tests/messenger/telegram/test_app.py`
- Focused task tool bootstrap regression coverage:
  `uv run --python 3.12 --extra dev pytest -q tests/workspace/test_task_tools.py`
