# Findings

## Requirements

- Project knowledge must load progressively rather than forcing every agent to read the
  whole repository.
- `PROJECT.md` owns stable intent, constraints, state, and priority.
- `docs/ARCHITECTURE.md` owns the system map and invariants.
- `docs/DECISIONS.md` owns durable rationale and rejected alternatives.
- Complex tasks own a minimal plan, findings, and progress trio.

## Repository Findings

- `REQUIREMENTS.md`, `IMPLEMENTATION.md`, and `HANDOFF.md` currently overlap with the new
  intended ownership model.
- `docs/typescript-migration/` contains useful deep migration contracts that should remain
  available through links, but should not be part of the default startup read.
- The existing `docs/architecture.md` is a detailed runtime map. It should become the
  uppercase architecture entry rather than coexist with a second competing document.
- `docs/README.md` currently prescribes a 29-step onboarding sequence; it is useful as a
  broad documentation catalog but conflicts with progressive default loading.
- Repository coordination tests explicitly enforce the superseded
  `REQUIREMENTS/IMPLEMENTATION/HANDOFF` authority and must be rewritten with the new
  ownership map.
- Python remains the authoritative runtime. The TypeScript layer is currently protocol,
  SDK, facade consumption, and local Web UI.
- The immediate verified development gap is two OpenCode auth tests that inherit the
  operator's XDG directories; production auth discovery should not change.

## Skill Findings

- Installed upstream commit `ad1b692` at `~/.local/share/planning-with-files`.
- Both `~/.agents/skills/planning-with-files` and
  `~/.claude/skills/planning-with-files` resolve to the same checkout.
- The skill requires persistent task files, reading the plan before major decisions,
  recording discoveries, and updating progress after each phase.
- External/web content belongs in findings rather than the auto-injected task plan.

## Technical Decisions

| Decision | Rationale |
|---|---|
| Use concise indexes and link to migration detail | Preserves knowledge without loading it by default. |
| Keep historical plans | Git history alone does not convey all historical intent, and old plans are not active authority. |
| Replace rather than duplicate canonical ownership | Two competing sources of truth would defeat the new memory model. |

## Resources

- Upstream skill: https://github.com/OthmanAdi/planning-with-files
- Existing migration detail: `docs/typescript-migration/`
- Existing plan history: `plans/`
