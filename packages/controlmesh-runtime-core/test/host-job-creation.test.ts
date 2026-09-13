import { HostJobApprovals } from "../src/host-job-approval";
import type { Principal } from "../src/kernel";
import { expect, test } from "bun:test";
import { mkdtempSync, mkdirSync, realpathSync, writeFileSync, readFileSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { openLocalRuntime } from "../src/local-runtime-config";
import { LocalRuntimeControl } from "../src/local-runtime-control";
import { parseRuntimeCli } from "../src/runtime-cli";

for (const wholePlan of [false, true]) test(`normal controls create, approve and start host steps atomically without importing state, whole plan=${wholePlan}`, async () => {
  const root = mkdtempSync(join(tmpdir(), "cm-host-create-")), state = join(root, "state"), workspace = join(root, "workspace"), path = join(root, "config.json");
  mkdirSync(state, { mode: 0o700 }); mkdirSync(workspace);
  writeFileSync(path, JSON.stringify({ schema_version: "controlmesh.local_runtime.v1", mode: "candidate", state_root: state,
    principal_id: "owner", device_id: "local", source: { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: "terminal" },
    host: { shell: realpathSync("/bin/bash") }, workspace: { directory: workspace, read_files: [], required_reads: [] } }), { mode: 0o600 });
  let owned = openLocalRuntime(path);
  const control = () => new LocalRuntimeControl(owned.runtime);
  try {
    const job = { job_id: "job", summary: "two steps", steps: ["first", "second"].map(id => ({ id, command: `printf '${id}\\n' >> marker` })) };
    const file = join(root, "job.json"); writeFileSync(file, JSON.stringify(job));
    expect(parseRuntimeCli(["create-host-job", "--file", file, "--socket", "/tmp/test.sock"])?.request).toMatchObject({ op: "create_host_job", job });
    expect(await control().handle({ id: "bad", op: "create_host_job", job: { ...job, repo: "/tmp" } })).toMatchObject({ ok: false, error: "invalid_host_job_definition" });
    expect(await control().handle({ id: "skip-approval", op: "create_host_job", job: { ...job, steps: [{ id: "step", command: "true", approval_required: false }] } }))
      .toMatchObject({ ok: false, error: "invalid_host_step_definition" });
    const created = await control().handle({ id: "create", op: "create_host_job", job });
    expect(created).toMatchObject({ ok: true, result: { revision: 1, job: { repo: workspace, state: "pending", steps: [{ approval_required: true }, { approval_required: true }] } } });
    expect(await control().handle({ id: "create", op: "create_host_job", job })).toEqual(created);
    expect(existsSync(join(workspace, "marker"))).toBe(false);
    expect(await control().handle({ id: "unapproved", op: "start_host_step", approval: {} })).toMatchObject({ ok: false });
    const actor: Principal = { id: "owner", device_id: "local", origin: "human_request", scopes: ["task:read", "task:admin", "task:execute"] };
    const plan = wholePlan ? new HostJobApprovals(owned.runtime.kernel.db, () => {}).approvePlan(actor, "whole-plan", "job", 1) : undefined;
    for (const [index, step] of ["first", "second"].entries()) {
      const revision = owned.runtime.inspectHostJob("job")!.revision;
      const approved = plan ? { ok: true, result: new HostJobApprovals(owned.runtime.kernel.db, () => {}).planStep(actor, plan, index) }
        : await control().handle({ id: `approve-${step}`, op: "approve_host_step", job_id: "job", expected_revision: revision, step_id: step });
      expect(approved.ok).toBe(true);
      const receiptFile = join(root, "approval.json"); writeFileSync(receiptFile, JSON.stringify(approved.result));
      expect(parseRuntimeCli(["start-host-step", "--file", receiptFile, "--socket", "/tmp/test.sock"])?.request)
        .toMatchObject({ op: "start_host_step", approval: approved.result });
      if (index === 0) {
        const db = owned.runtime.kernel.db;
        db.sql.exec("CREATE TRIGGER fail_enqueue BEFORE INSERT ON local_runs BEGIN SELECT RAISE(ABORT,'enqueue unavailable'); END;");
        expect(await control().handle({ id: `start-${step}`, op: "start_host_step", approval: approved.result })).toMatchObject({ ok: false });
        expect(db.sql.query("SELECT COUNT(*) AS n FROM tasks").get()).toEqual({ n: 0 });
        expect(owned.runtime.inspectHostJob("job")!.revision).toBe(revision);
        db.sql.exec("DROP TRIGGER fail_enqueue;");
      }
      const started = await control().handle({ id: `start-${step}`, op: "start_host_step", approval: approved.result });
      expect(started).toMatchObject({ ok: true, result: { task: { task: { status: "waiting", provider: "host" } }, run: { state: "queued" } } });
      expect(await control().handle({ id: `start-${step}`, op: "start_host_step", approval: approved.result })).toEqual(started);
      await owned.runtime.drain();
      expect(readFileSync(join(workspace, "marker"), "utf8")).toBe(index === 0 ? "first\n" : "first\nsecond\n");
      expect(await control().handle({ id: `duplicate-${step}`, op: "start_host_step", approval: approved.result })).toMatchObject({ ok: false });
      await owned.close(); owned = openLocalRuntime(path);
      expect(await control().handle({ id: `start-${step}`, op: "start_host_step", approval: approved.result })).toMatchObject({ ok: true, result: { task: { task: { status: "done" } } } });
    }
    expect(owned.runtime.inspectHostJob("job")!.job.state).toBe("completed");
    expect(owned.runtime.kernel.db.sql.query("SELECT COUNT(*) AS n FROM tasks").get()).toEqual({ n: 2 });
  } finally { await owned.close(); rmSync(root, { recursive: true, force: true }); }
});
