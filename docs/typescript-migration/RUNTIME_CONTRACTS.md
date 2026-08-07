# Runtime Contracts

These contracts are frozen for TypeScript migration work:

- Task identifiers remain strings.
- `chat_id` and `thread_id` may be strings or integers.
- Task status values keep the Python spellings in `task-state.schema.json`.
- Provider and transport names are protocol values, not display names.
- Artifact paths exposed to TypeScript are relative paths from Python APIs.
- TypeScript code must preserve unknown fields when forwarding protocol objects.
- Python provider timeout, process, and recovery behavior is not reimplemented in TypeScript.
