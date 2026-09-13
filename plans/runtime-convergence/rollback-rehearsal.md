# Offline TaskHub compatibility export

Status: implemented for the task-registry artifact; full production rollback remains open.

From the repository root, using Bun:

```sh
bun packages/controlmesh-runtime-core/scripts/legacy-export.ts \
  --database /absolute/path/to/candidate.sqlite \
  --source-id reviewed-import-id \
  --output /absolute/path/to/new-rollback.json
```

The database must already exist and contain the named import. The destination must not
exist. The command reads one SQLite transaction without schema migration, retains the
original registry envelope and all current task rows, and verifies that no imported task
has disappeared. It reports only counts and digests on stdout; task contents go to the
private output file. A write failure can leave a partial new file and never emits success.

The artifact includes active statuses as facts, not execution permission. Do not point a
running Python registry at it. The old writer must remain fenced until current episodes,
unknown effects, device leases, native sessions, delivery receipts and other runtime
stores have their own compatible recovery evidence. This command exports only TaskHub
rows; it does not restore those other stores or authorize a production rollback.

`test/legacy-export.test.ts` exercises the command in another OS process with a real
Python serializer fixture, adds a TS-created task, verifies retained fields and source
bytes, then imports the artifact into a fresh candidate. It also verifies output privacy,
overwrite/symlink refusal, and missing-source/task failures. Python startup and multi-store
rollback still require a separate rehearsal before CM-R7.
