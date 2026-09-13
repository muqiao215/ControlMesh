import { parseRuntimeCli } from "../src/runtime-cli";
import { expect, test } from "bun:test";
import { mkdtempSync, mkdirSync, realpathSync, writeFileSync, readFileSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { openLocalRuntime } from "../src/local-runtime-config";
import { LocalRuntimeControl } from "../src/local-runtime-control";
import { HostJobStore } from "../src/host-job-store";
import type { Principal } from "../src/kernel";

for (const mode of ["success", "failure", "forged-completion", "between-steps"]) test(`whole host plan advances only confirmed successful steps: ${mode}`, async () => {
  const root = mkdtempSync(join(tmpdir(), "cm-host-plan-")), state = join(root, "state"), workspace = join(root, "workspace"), path = join(root, "config.json");
  mkdirSync(state, { mode: 0o700 }); mkdirSync(workspace);
  writeFileSync(path, JSON.stringify({ schema_version: "controlmesh.local_runtime.v1", mode: "candidate", state_root: state,
    principal_id: "owner", device_id: "local", source: { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: "terminal" },
    host: { shell: realpathSync("/bin/bash") }, workspace: { directory: workspace, read_files: [], required_reads: [] } }), { mode: 0o600 });
  let owned = openLocalRuntime(path);
  const control = () => new LocalRuntimeControl(owned.runtime);
  try {
    const job = { job_id: "job", steps: [{ id: "one", command: `printf 'one\\n' >> marker; exit ${mode === "failure" ? 7 : 0}` }, { id: "two", command: "printf 'two\\n' >> marker" }] };
    expect(await control().handle({ id: "create", op: "create_host_job", job })).toMatchObject({ ok: true });
    const registered = await control().handle({ id: "run-plan", op: "run_host_job", job_id: "job", expected_revision: 1 });
    expect(registered).toMatchObject({ ok: true, result: { run_id: "run-plan", schema_version: "controlmesh.host_plan_run.v1" } });
    expect(existsSync(join(workspace, "marker"))).toBe(false);
    await owned.close(); owned = openLocalRuntime(path);
    if (mode === "forged-completion") {
      const actor: Principal = { id: "owner", device_id: "local", origin: "human_request", scopes: ["task:admin", "task:read"] };
      const store = new HostJobStore(owned.runtime.kernel.db, () => {}), initial = store.get(actor, "job")!;
      const running = store.put(actor, "fake-start", 1, { ...initial.job, state: "running", steps: initial.job.steps.map(step => step.id === "one" ? { ...step, state: "running" } : step) });
      store.put(actor, "fake-finish", 2, { ...running.job, steps: running.job.steps.map(step => step.id === "one" ? { ...step, state: "completed" } : step) });
    }
    if (mode === "between-steps") {
      owned.runtime.kernel.db.sql.exec("CREATE TRIGGER stop_second_enqueue BEFORE INSERT ON local_runs WHEN (SELECT COUNT(*) FROM local_runs)>0 BEGIN SELECT RAISE(ABORT,'interrupted step dispatch'); END;");
      await expect(owned.runtime.drain()).rejects.toThrow("interrupted step dispatch");
      expect(readFileSync(join(workspace, "marker"), "utf8")).toBe("one\n");
      owned.runtime.kernel.db.sql.exec("DROP TRIGGER stop_second_enqueue;");
      await owned.close(); owned = openLocalRuntime(path);
    }
    await owned.runtime.drain();
    const status = await control().handle({ id: "status", op: "inspect_host_plan", run_id: "run-plan" });
    expect(status).toMatchObject({ ok: true, result: { state: ["success", "between-steps"].includes(mode) ? "completed" : mode === "failure" ? "failed" : "blocked" } });
    if (mode === "forged-completion") {
      expect(status).toMatchObject({ result: { reason: "host_plan_predecessor_unproven" } });
      expect(existsSync(join(workspace, "marker"))).toBe(false);
    } else expect(readFileSync(join(workspace, "marker"), "utf8")).toBe(["success", "between-steps"].includes(mode) ? "one\ntwo\n" : "one\n");
    const count = owned.runtime.kernel.db.sql.query("SELECT COUNT(*) AS n FROM tasks").get();
    expect(count).toEqual({ n: ["success", "between-steps"].includes(mode) ? 2 : mode === "failure" ? 1 : 0 });
    expect(await control().handle({ id: "run-plan", op: "run_host_job", job_id: "job", expected_revision: 1 })).toEqual(registered);
    await owned.close(); owned = openLocalRuntime(path); await owned.runtime.drain();
    expect(owned.runtime.kernel.db.sql.query("SELECT COUNT(*) AS n FROM tasks").get()).toEqual(count);
    if (["success", "between-steps"].includes(mode)) expect(owned.runtime.kernel.db.sql.query("SELECT COUNT(*) AS n FROM events WHERE kind='host.plan.step_enqueued' AND origin='internal'").get()).toEqual({ n: 2 });
  } finally { await owned.close(); rmSync(root, { recursive: true, force: true }); }
});

test("whole-plan CLI separates explicit running from inspection", () => {
  expect(parseRuntimeCli(["run-host-job", "job", "--revision", "3", "--socket", "/tmp/host.sock"])?.request).toMatchObject({ op: "run_host_job", job_id: "job", expected_revision: 3 });
  expect(parseRuntimeCli(["inspect-host-plan", "run", "--socket", "/tmp/host.sock"])?.request).toMatchObject({ op: "inspect_host_plan", run_id: "run" });
});
