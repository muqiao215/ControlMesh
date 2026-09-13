import { expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { openLocalRuntime } from "../src/local-runtime-config";
import { GeminiSessionStore, geminiProjectHash } from "../src/providers/gemini-session";
const node = process.env.CM_GEMINI_SETTINGS_NODE;
// Real Node probe and supervised CLI fixture; no live model, operator auth or mocked adapter.
test.skipIf(!node).each([false, true])("configured Gemini performs preflight, native continuation and reopen recovery (lost=%s)", async lost => {
  const root = mkdtempSync(join(tmpdir(), "cm-gemini-config-")), state = join(root, "state"), workspace = join(root, "workspace"), sessions = join(root, "chats"), policy = join(root, "policy");
  for (const path of [state, workspace, sessions, policy]) mkdirSync(path, { mode: 0o700 });
  const settingsFile = join(root, "settings.json"), module = join(root, "native.mjs"), executable = join(root, "gemini"), events = join(root, "events");
  writeFileSync(settingsFile, "{}");
  const credentials = join(root, "credentials.json"); writeFileSync(credentials, "old-fixture");
  writeFileSync(join(policy, "cm.toml"), '[[rule]]\ntoolName="*"\ndecision="deny"\npriority=998\n');
  writeFileSync(module, `import fs from 'node:fs';
export const loadSettings=()=>({merged:JSON.parse(fs.readFileSync(${JSON.stringify(settingsFile)},'utf8')),errors:[],user:{path:${JSON.stringify(settingsFile)}}});
export const DEFAULT_CORE_POLICIES_DIR=${JSON.stringify(policy)};
export const getPolicyDirectories=()=>[DEFAULT_CORE_POLICIES_DIR];
export const createPolicyEngineConfig=async()=>({rules:[{toolName:'*',decision:'deny',priority:5.998,source:'Admin: cm.toml'}]});\n`);
  const id = "11111111-2222-3333-4444-555555555555", session = join(sessions, "session-fixture-11111111.jsonl");
  writeFileSync(session, JSON.stringify({ sessionId: id, projectHash: geminiProjectHash(workspace), startTime: "now", lastUpdated: "now" }) + "\n");
  writeFileSync(executable, `#!${process.execPath}\nconst fs=require('node:fs'),crypto=require('node:crypto');
if(process.argv.includes('--version')) { console.log('0.59.0');process.exit(0); }
let prompt='';for await(const chunk of process.stdin) prompt+=chunk;
const resume=process.argv.includes('--resume'), id=resume?process.argv[process.argv.indexOf('--resume')+1]:crypto.randomUUID();
fs.appendFileSync(process.env.EVENTS,(resume?'resume':'probe')+'\\n');
const row=value=>JSON.stringify(value)+'\\n',answer=resume?'Remembered':'PONG',turn=crypto.randomUUID();
if(resume)fs.appendFileSync(process.env.SESSION,row({id:turn+'u',type:'user',content:prompt,timestamp:'now'})+row({id:turn+'a',type:'gemini',content:answer,model:'fixture',timestamp:'now'}));
process.stdout.write(row({type:'init',session_id:id,model:'fixture'})+row({type:'message',role:'user',content:prompt})+row({type:'message',role:'assistant',delta:true,content:answer})+row({type:'result',status:'success'}));
`, { mode: 0o700 });
  const config = { schema_version: "controlmesh.local_runtime.v1", mode: "candidate", state_root: state, principal_id: "operator", device_id: "desktop",
    source: { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: "terminal" },
    workspace: { directory: workspace, read_files: [], required_reads: [] },
    gemini: { cli_version: "0.59.0", executable, model: "fixture", sessions_directory: sessions, credential_sources: [credentials], settings: {
      node_executable: realpathSync(node!), settings_module: module, workspace, environment: { HOME: root, EVENTS: events, SESSION: session },
      runtime_files: [module, executable], settings_sources: [settingsFile],
      effective_policy: { module, admin_directory: policy, policy_filename: "cm.toml", allowed_tools: [], sources: [policy] } } } };
  const path = join(root, "runtime.json"); writeFileSync(path, JSON.stringify(config), { mode: 0o600 });
  let owned: ReturnType<typeof openLocalRuntime> | undefined;
  try {
    owned = openLocalRuntime(path); expect(owned.describe().providers).toEqual([{ provider: "gemini", model: "fixture" }]);
    const baseline = new GeminiSessionStore(session, "desktop", workspace).baseline(id);
    const task = owned.runtime.submit("create", { task_id: "task", status: "waiting", chat_id: "fixture", provider: "gemini", model: "fixture", repo_root: workspace, prompt: "Continue",
      native_session: { ...baseline, provider: "gemini", device_id: "desktop", directory: workspace, model: "fixture" } }, { chat_id: "fixture" });
    if (lost) owned.runtime.kernel.recordEffectObservation = () => { throw new Error("fixture loss"); };
    const run = owned.runtime.enqueue("run", "task", task.revision); await owned.runtime.drain();
    const observed = owned.runtime.inspectTask("task");
    if (lost) {
      expect(observed.needs_reconciliation).toBe(true);
      const effect = (owned.runtime.kernel.db.sql.query("SELECT effect_id FROM effects").get() as { effect_id: string }).effect_id;
      await owned.close(); writeFileSync(credentials, "rotated-fixture"); owned = openLocalRuntime(path);
      const binding = owned.recovery.inspect("task", observed.revision, effect);
      expect((await owned.recovery.accept("recover", "task", observed.revision, binding)).task.status).toBe("done");
    } else expect(owned.runtime.inspect(run.run_id).state, JSON.stringify(owned.runtime.inspect(run.run_id))).toBe("completed");
    expect(readFileSync(events, "utf8").trim().split("\n")).toEqual(["probe", "resume"]);
  } finally { await owned?.close(); rmSync(root, { recursive: true, force: true }); }
}, 20000);
