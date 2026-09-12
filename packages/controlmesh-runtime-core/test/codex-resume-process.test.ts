import { afterEach, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { issueToolGrant } from "../src/execution-grants";
import { issueExecutionContext } from "../src/execution-context";
import { CodexSessionStore } from "../src/providers/codex-session";
import { CodexResumeProcess, verifyRetainedCodexResume, type CodexResumeAdmission, type CodexResumeInput } from "../src/providers/codex-resume-process";
const cleanup: string[] = [];
afterEach(() => { for (const path of cleanup.splice(0)) rmSync(path, { recursive: true, force: true }); });
function fixture(mode = "normal") {
  const root = mkdtempSync(join(tmpdir(), "cm-codex-resume-")); cleanup.push(root);
  const home = join(root, "codex"), sessions = join(home, "sessions"), workspace = join(root, "project"), state = join(root, "state");
  for (const path of [home, sessions, workspace, state]) mkdirSync(path, { mode: 0o700 });
  const id = "11111111-2222-7333-8444-555555555555", rollout = join(sessions, `rollout-fixture-${id}.jsonl`);
  const row = (type: string, payload: object) => JSON.stringify({ type, payload }) + "\n";
  writeFileSync(rollout, row("session_meta", { id, cwd: workspace }) + row("event_msg", { type: "task_started", turn_id: "old" })
    + row("turn_context", { turn_id: "old", cwd: workspace, model: "fixture-model" })
    + row("event_msg", { type: "user_message", message: "remember" })
    + row("event_msg", { type: "agent_message", phase: "final", message: "noted" })
    + row("event_msg", { type: "task_complete", turn_id: "old", last_agent_message: "noted" }));
  const executable = join(root, "codex-fixture");
  writeFileSync(executable, `#!${process.execPath}\nconst fs=require('node:fs');
if(process.argv.includes('--version')) { console.log('codex-cli '+(process.env.FIXTURE_MODE==='version'?'0.0.0':'0.154.0')); process.exit(0); }
if(!fs.existsSync(process.env.FIXTURE_DISPATCH)) process.exit(9);
let prompt=''; for await(const chunk of process.stdin) prompt+=chunk;
fs.writeFileSync(process.env.FIXTURE_ARGS,JSON.stringify(process.argv.slice(2)));
const emit=(type,payload)=>JSON.stringify({type,payload})+'\\n';
fs.appendFileSync(process.env.FIXTURE_ROLLOUT,
 emit('event_msg',{type:'task_started',turn_id:'new'})+
 emit('turn_context',{turn_id:'new',cwd:process.cwd(),model:'fixture-model'})+
 emit('event_msg',{type:'user_message',message:prompt})+
 emit('event_msg',{type:'agent_message',phase:'final',message:'remembered'})+
 emit('event_msg',{type:'task_complete',turn_id:'new',last_agent_message:'remembered'}));
console.log(JSON.stringify({type:'thread.started',thread_id:process.env.FIXTURE_MODE==='foreign'?'foreign':process.env.FIXTURE_SESSION}));
console.log(JSON.stringify({type:'item.completed',item:{type:'agent_message',text:'remembered'}}));
console.log(JSON.stringify({type:'turn.completed'}));
`, { mode: 0o700 });
  const dispatch = join(root, "dispatch.json"), outcome = join(root, "outcome.json");
  const input: CodexResumeInput = { executable, cli_version: "0.154.0", state_home: state, codex_home: home,
    environment: { PATH: "/usr/bin:/bin", CODEX_HOME: home, FIXTURE_MODE: mode, FIXTURE_DISPATCH: dispatch,
      FIXTURE_ROLLOUT: rollout, FIXTURE_SESSION: id, FIXTURE_ARGS: join(root, "args.json") },
    sandbox: "read-only", reference: new CodexSessionStore(rollout, "device").read(id), rollout_path: rollout,
    model: "fixture-model", prompt: "Continue with the original memory", execution_context: issueExecutionContext({ origin: "user", source_scope: "local_foreground", transport: "terminal" }),
    tool_grant: issueToolGrant({ network_policy: "no_network" }), timeout_ms: 5000 };
  const admission: CodexResumeAdmission = { assertCurrent: () => {}, assertReady: () => {},
    retainDispatch: value => writeFileSync(dispatch, JSON.stringify(value)), retainOutcome: value => writeFileSync(outcome, JSON.stringify(value)) };
  return { root, input, admission, dispatch, outcome };
}
test("Codex resume starts a supervised process only after retained dispatch and verifies appended same-session output", async () => {
  const f = fixture(), result = await new CodexResumeProcess().run(f.input, f.admission);
  expect(result.evidence.reference.session_id).toBe(f.input.reference.session_id);
  expect(result.evidence.turn_id).toBe("new"); expect(result.observation.text).toBe("remembered");
  const args = JSON.parse(readFileSync(join(f.root, "args.json"), "utf8"));
  expect(args.slice(0, 3)).toEqual(["exec", "--sandbox", "read-only"]);
  expect(args.slice(-3)).toEqual(["--", f.input.reference.session_id, "-"]);
  expect(args).not.toContain("--last"); expect(args).not.toContain(f.input.prompt);
  const retained = JSON.parse(readFileSync(f.outcome, "utf8")), dispatch = JSON.parse(readFileSync(f.dispatch, "utf8"));
  expect(retained.exit_code).toBe(0);
  expect(verifyRetainedCodexResume(f.input, dispatch, retained, () => {})).toEqual(result);
  expect(() => verifyRetainedCodexResume({ ...f.input, prompt: "substituted" }, dispatch, retained, () => {})).toThrow("codex_dispatch_changed");
  expect(() => verifyRetainedCodexResume(f.input, dispatch, retained, () => { throw new Error("revoked"); })).toThrow("revoked");
});
test("Codex incompatible version refuses before dispatch; foreign native output is retained but never accepted", async () => {
  const old = fixture("version"); let dispatched = false;
  await expect(new CodexResumeProcess().run(old.input, { ...old.admission, retainDispatch: () => { dispatched = true; } })).rejects.toThrow("codex_version_mismatch");
  expect(dispatched).toBe(false);
  const foreign = fixture("foreign");
  await expect(new CodexResumeProcess().run(foreign.input, foreign.admission)).rejects.toThrow("native_session_mismatch");
  expect(JSON.parse(readFileSync(foreign.outcome, "utf8")).exit_code).toBe(0);
});
test("Codex unready, unsupported grants, remote source and failed retention cannot launch task input", async () => {
  const f = fixture(); let runs = 0;
  const process = new CodexResumeProcess({ run: async () => { runs++; throw new Error("must not launch"); } });
  await expect(process.run(f.input, { ...f.admission, assertReady: () => { throw new Error("quota_wait"); } })).rejects.toThrow("quota_wait");
  await expect(process.run({ ...f.input, tool_grant: issueToolGrant({ tool_deny: ["shell"] }) }, f.admission)).rejects.toThrow();
  await expect(process.run({ ...f.input, execution_context: issueExecutionContext({ origin: "cron", source_scope: "cron", transport: "cron" }) }, f.admission)).rejects.toThrow();
  expect(runs).toBe(0);
  await expect(new CodexResumeProcess().run(f.input, { ...f.admission, retainDispatch: () => { throw new Error("disk_full"); } })).rejects.toThrow("disk_full");
  expect(() => readFileSync(join(f.root, "args.json"))).toThrow();
});


test("Codex executable replacement after version check withholds task input", async () => {
  const f = fixture();
  await expect(new CodexResumeProcess().run(f.input, { ...f.admission, retainDispatch: value => {
    f.admission.retainDispatch(value);
    writeFileSync(f.input.executable, "#!/bin/sh\nexit 0\n", { mode: 0o700 });
  } })).rejects.toThrow("codex_resume_configuration_changed");
  expect(() => readFileSync(join(f.root, "args.json"))).toThrow();
});
