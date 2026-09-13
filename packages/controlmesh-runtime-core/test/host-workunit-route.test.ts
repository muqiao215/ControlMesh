import { RuntimeDatabase } from "../src/database";
import { RuntimeKernel, type Principal } from "../src/kernel";
import { LocalTaskRuntime } from "../src/local-task-runtime";
import { expect, test } from "bun:test";
import { mkdtempSync, mkdirSync, realpathSync, writeFileSync, readFileSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { openLocalRuntime } from "../src/local-runtime-config";
import { LocalRuntimeControl } from "../src/local-runtime-control";

test("normal explicit workunits route atomically to host while preserving the task ID", async () => {
  const root = mkdtempSync(join(tmpdir(), "cm-workunit-route-")), state = join(root, "state"), workspace = join(root, "workspace"), path = join(root, "config.json");
  mkdirSync(state, { mode: 0o700 }); mkdirSync(workspace);
  writeFileSync(path, JSON.stringify({ schema_version: "controlmesh.local_runtime.v1", mode: "candidate", state_root: state,
    principal_id: "owner", device_id: "local", source: { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: "terminal" },
    host: { shell: realpathSync("/bin/bash") }, workspace: { directory: workspace, read_files: [], required_reads: [] } }), { mode: 0o600 });
  let owned = openLocalRuntime(path);
  try {
    const raw = { task_id: "test-task", chat_id: "test", status: "waiting" as const, provider: "opencode", model: "unused/model", workunit_kind: "test_execution", command: "printf 'once\\n' >> marker" };
    expect(() => owned.runtime.submit("restricted", { ...raw, task_id: "restricted" }, { chat_id: "test" }, { no_network: true })).toThrow("host_job_grant_unenforceable");
    for (const table of ["tasks", "host_jobs", "receipts"]) expect(owned.runtime.kernel.db.sql.query(`SELECT COUNT(*) AS n FROM ${table}`).get()).toEqual({ n: 0 });
    const control = new LocalRuntimeControl(owned.runtime);
    const submitted = await control.handle({ id: "submit", op: "submit", task: raw });
    expect(submitted).toMatchObject({ ok: true, result: { task: { task_id: "test-task", provider: "host", model: "", host_route: { requested_provider: "opencode", requested_model: "unused/model", reason: "workunit=test_execution" } } } });
    expect(existsSync(join(workspace, "marker"))).toBe(false);
    expect(await control.handle({ id: "submit", op: "submit", task: raw })).toEqual(submitted);
    const job = owned.runtime.hostJobs().jobs[0]!;
    expect(owned.runtime.inspectHostJob(job.job_id)!.job.source_task_id).toBe("test-task");
    owned.runtime.enqueue("enqueue", "test-task", 1); await owned.runtime.drain();
    expect(owned.runtime.inspectTask("test-task").task.status).toBe("done");
    expect(readFileSync(join(workspace, "marker"), "utf8")).toBe("once\n");
    expect(owned.runtime.kernel.db.sql.query("SELECT COUNT(*) AS n FROM provider_checks").get()).toEqual({ n: 0 });
    await owned.close(); owned = openLocalRuntime(path);
    expect(await new LocalRuntimeControl(owned.runtime).handle({ id: "submit", op: "submit", task: raw })).toEqual(submitted);
    expect(owned.runtime.hostJobs().jobs.length).toBe(1);
  } finally { await owned.close(); rmSync(root, { recursive: true, force: true }); }
});

 test("host workunit routing cannot bypass an isolation-required source", async () => {
  const db = new RuntimeDatabase(":memory:"), kernel = new RuntimeKernel(db);
  const actor: Principal = { id: "owner", device_id: "group", origin: "human_request", scopes: ["task:read", "task:create", "task:execute", "task:admin", "task:reconcile"] };
  const runtime = new LocalTaskRuntime(kernel, actor, { command_origin: "human_request", origin: "user", source_scope: "group_message", transport: "fs" },
    () => { throw new Error("must not resolve a process"); }, () => {}, {}, "/tmp");
  try {
    expect(() => runtime.submit("group", { task_id: "task", chat_id: "group", status: "waiting", workunit_kind: "long_shell", command: "echo cannot-run" }, { chat_id: "group" }))
      .toThrow("sandbox_required_unavailable");
    for (const table of ["tasks", "host_jobs", "receipts"]) expect(db.sql.query(`SELECT COUNT(*) AS n FROM ${table}`).get()).toEqual({ n: 0 });
  } finally { await runtime.stop(); db.close(); }
});
