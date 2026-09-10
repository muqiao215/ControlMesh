# Findings

- Baseline: origin/main fe1ef45 (v0.42.1), isolated feature worktree.
- TaskSubmit currently has no native-session reference; TaskHub supports resume only after CM owns a task.
- OpenCode native resume previously wrote an answer but its CLI did not exit/output. Explicit --dir may resolve event subscription directory mismatch; not yet verified.
- Viewer already indexes native OpenCode history and supplies read-only session/audit endpoints. Copying a native command is not TaskHub adoption.
- Existing OpenCode explicit tool grants fail closed. Integration must not remove these grants to execute.
- Verified explicit `--dir` fixes native resumed output and exit on installed OpenCode 1.18.29: exit 0, text events, original session ID, historical 6 phases/R01–R12 recalled.
- Integration uses trusted local `/tasks sessions|inspect|adopt` commands; no public mutation API or automation is added.
- Native working directory can differ from project target. Runtime home/environment must remain CM-owned when cwd changes.
- CM advisory leases exclude other CM runs only; native clients do not honor them. Revision checks detect intervening writes but cannot promise cross-client exclusivity.

- Full terminal acceptance exposed an existing command-registry gap: `/tasks` was exact-only; parameterized task commands fell through to provider conversation. Added `/tasks ` prefix registration and a real-orchestrator regression asserting no model call for inspection. The failed isolated attempt was terminated; no application work was authorized by that command.
- Native MiniMax sometimes replies `PONG.`. Preflight now accepts only PONG or PONG plus one period, still rejecting prompt echoes/errors/explanations; the synchronous probe also binds --dir explicitly.
- Final real TerminalRuntime startup (no mocked execution or delivery) searched Viewer, adopted the native session, passed preflight, completed, and delivered its historical answer into TerminalInbox in 15.99 seconds.
