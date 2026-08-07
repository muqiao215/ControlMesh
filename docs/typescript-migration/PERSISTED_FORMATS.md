# Persisted Formats Audit

Initial migration status: incomplete audit, no runtime mutation.

Known persisted or user-visible formats that TypeScript must not change:

- Task registry entries derived from `controlmesh/tasks/models.py`.
- Runtime event records from `controlmesh/runtime/models.py`.
- Transcript/history index records used by `controlmesh/api/admin_read.py`.
- Workspace paths from `controlmesh/workspace/paths.py`.
- Memory files and promotion outputs from `controlmesh/memory/`.
- Task artifact relative paths and evidence files.
- Team state and topology files from `controlmesh/team/state/`.

Any future TypeScript write path must add golden fixtures before it is enabled.
