# Primary review 2 — repair bridge before acceptance

Resume the existing CBC session. Your implementation exists but is NOT accepted.
Only own the same relevant bridge/CLI/HostJob files and tests, plus bridge result/spec.
Do not edit global progress or AGY documents. No commit/push, no production service/state,
no native browser/account operations. Run focused tests; don't repeat 1000-test suites.

Required fixes:
1. Two OS processes calling run on the same cold job can execute twice. Serialize start
   using a durable local ownership primitive and persisted dispatch intent; demonstrate
   exactly one command side effect under concurrent cold start. Reopening a started or
   uncertain attempt must never invoke runner.start to re-execute. No prompt-only lock.
2. Bind job ID to parent, command, workspace and approved attempt definition at first run.
   Same ID with changed command/parent/cwd must reject, not return an unrelated receipt.
   Wait/consume must enforce that persisted parent binding. Arbitrary other parent must
   not create a second delivery target. Validate job/parent identifiers before path use.
3. consume has read/check/mark races: two processes can both return terminal data. Make
   same-parent consumption atomic across OS processes and test one winner. Retain existing
   inbox owner, no second standalone task registry. Document crash-before-return at-most-once
   semantics; don't call it guaranteed delivery.
4. _pid_alive treats EPERM as dead; worker missing/unknown is not confirmed termination of
   child processes. Retain an explicit uncertain outcome requiring review rather than infer
   safe resource release. Do not revive/re-execute such jobs. Test relevant failure path.
5. run always issues local_foreground; correct the report's false claim that a cron input
   was actually tested/denied. Document this as an explicitly local controller CLI bridge,
   not general authenticated remote task ingress or native session adoption.
6. Update exact CLI help timeout flags/report. Capture native CBC session ID from caller
   supplied identity 01a09a29-a069-7afe-9ab4-909d055fa089 (original CLI JSON confirms it),
   rather than claiming none exists. This is not evidence of AGY native adoption.

This repair is launched through the bridge's current CM hostjob run in a separate CM
state directory, single owner. Do not modify its running state or kill the parent. Main
will wait for actual exit through CM, inspect results and consume one event. New source
changes take effect in later processes; current invocation imported the pre-review code.

Record implementation/test files, commands, exit codes and limitations in
plans/runtime-convergence/delegation/taskhub-parent-bridge-result.md. Save raw test log to
/tmp/cm-parent-bridge-r2-tests.log, final concise. Stop rather than repeated quota probes.
