# Skill System

Cross-tool skill sync between controlmesh workspace and CLI skill homes.

## Files

- `workspace/skill_sync.py`: discovery, canonical selection, sync, cleanup, watcher
- `workspace/init.py`: startup one-shot sync calls
- `orchestrator/observers.py`: starts/stops background skill-sync watcher
- `workspace/paths.py`: skill-related path properties

## Sync directories

```text
<agent-home>/workspace/skills/
<-> ~/.claude/skills/
<-> ~/.codex/skills/ (or $CODEX_HOME/skills)
<-> ~/.gemini/skills/
```

`<agent-home>`:

- main: `~/.controlmesh`
- sub-agent: `~/.controlmesh/agents/<name>`

## Bundled skills

Bundled source: `controlmesh/_home_defaults/workspace/skills/`.

`sync_bundled_skills(paths)` mirrors bundled skills into each agent's workspace skill dir.

- normal mode: links/junctions
- Docker mode: managed copies (`.controlmesh_managed`)

## Sync algorithm (`sync_skills`)

1. discover skill dirs in all roots
2. union names
3. pick canonical source by priority (`controlmesh > claude > codex > gemini`)
4. mirror to other roots
5. cleanup broken managed links

## Docker-mode behavior

When `docker_active=True`:

- uses managed copies instead of links
- updates only managed copies
- preserves unmanaged user directories

## Cleanup on shutdown

`cleanup_controlmesh_links(paths)` removes managed links under CLI skill dirs whose targets point to managed roots.

## Safety guarantees

- unmanaged real directories are preserved
- broken links are cleaned
- hidden/system dirs are skipped
- cross-platform link handling (incl. Windows junction fallback)
