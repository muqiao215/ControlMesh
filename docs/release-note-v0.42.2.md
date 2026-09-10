# v0.42.2 — Explicit OpenCode session adoption

ControlMesh can now discover existing Linux/OpenCode sessions through the local
Codex-Claude-History-Viewer and adopt an explicitly selected session into TaskHub.

In the enhanced local CM terminal:

```text
/tasks sessions SpecMesh
/tasks inspect ses_<id>
/tasks adopt --session ses_<id> --revision <inspection-revision> --directory <native-cwd> --repo <target-repo> --model <provider/model> -- <new instruction>
```

The selected model must return a supervised PONG preflight before native continuation
(a single terminal period is accepted). Task subcommands are explicitly registered so
control commands cannot fall through into model prompts.
The task retains its native session ID, source identity, revision and original permissions.
Host OpenCode receives an explicit `--dir`; CM runtime state remains in its original home.
Existing TaskHub cancel/resume continues the same session. After an owner crash, inspect
the session again and use:

```text
/tasks recover --task <task-id> --revision <inspection-revision> -- <new instruction>
```

Recovery checks the old task/preflight process leases and retains the same task identity.
Terminal TaskHub execution is explicitly wired to the foreground CLI service; results and
questions appear in the terminal inbox. No automatic scheduler or public HTTP mutation
endpoint is added.

History Viewer supplies discovery evidence; OpenCode owns native dialogue; SpecMesh owns
project facts; CM owns execution and lifecycle. Old conversation claims must be reconciled
against current repository state.

This adapter supports local Linux OpenCode history and host execution. Stop independent
native clients before adoption: CM's advisory lease excludes CM runs, not arbitrary
OpenCode processes. Unsupported native tool grants continue to fail closed. Viewer is
expected on loopback port 8787; direct `/tasks inspect` works without Viewer.

Validation: 5,703 full-suite tests passed before the final recovery addition; 379 targeted
tests passed afterward, including 21 native-adoption cases. Ruff and targeted Mypy passed.
Real isolated TaskHub execution discovered a historical SpecMesh session via Viewer,
passed the MiniMax preflight, resumed the original native ID, returned historical facts
and completed normally with native tools denied. A final real TerminalRuntime run also
verified Viewer search, adoption and terminal inbox delivery in 15.99 seconds. The final
routing/probe/native/terminal regression set passed 220 tests. No WeChat application
operation was run.

Rollback: stop adopted tasks before downgrading. Older builds do not interpret their
native-session provenance and must not be used to resume them.
