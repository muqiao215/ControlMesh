import { afterEach, expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DeviceScheduler, RuntimeDatabase, type DeviceJob, type DeviceRunAdmission, type DeviceRunOutcome, type Principal } from "../src";
import { digest, RuntimeConflict } from "../src/value";

const actor: Principal = { id: "operator", device_id: "worker", origin: "agent_message", scopes: ["device:schedule"] };
const cleanup: (() => void | Promise<void>)[] = [];
afterEach(async () => { for (const done of cleanup.splice(0).reverse()) await done(); });
const spin = async (check: () => boolean) => { for (let i = 0; i < 100 && !check(); i++) await Bun.sleep(2); expect(check()).toBe(true); };
function fixture() {
  const root = mkdtempSync(join(tmpdir(), "cm-device-scheduler-")); cleanup.push(() => rmSync(root, { recursive: true, force: true }));
  let now = 1_000_000, elapsed = 1000, valid = true, queueFailure: string | null = null, discoveries = 0;
  const path = join(root, "runtime.sqlite"), db = new RuntimeDatabase(path, () => now); cleanup.push(() => db.close());
  const jobs = new Map<string, DeviceJob>(), calls: { id: string; job: DeviceJob; admission: DeviceRunAdmission }[] = [];
  const behavior = { async run(_job: DeviceJob, _admission: DeviceRunAdmission): Promise<DeviceRunOutcome> { return { status: "done" }; } };
  const client = {
    async queuePage(after: string | null) {
      discoveries++; if (queueFailure) throw new RuntimeConflict(queueFailure);
      const items = [...jobs.values()].filter(job => job.status === "waiting" && job.task_id > (after ?? "")).sort((a, b) => a.task_id < b.task_id ? -1 : 1);
      return { items: structuredClone(items.slice(0, 32)), next_cursor: items.length > 32 ? items[31].task_id : null };
    },
    async inspect(id: string) { const job = jobs.get(id); if (!job) throw new RuntimeConflict("assignment_unavailable"); return structuredClone(job); },
  };
  const executor = { capacity: () => 8, async run(id: string, job: DeviceJob, admission: DeviceRunAdmission) {
    admission.assertCurrent(); calls.push({ id, job, admission }); const result = await behavior.run(job, admission);
    if (result.status === "done" || result.status === "failed") jobs.get(job.task_id)!.status = result.status; return result;
  } };
  const create = (local = db, boot = "fixture-boot") => {
    const scheduler = new DeviceScheduler(local, actor, client, executor, () => { if (!valid) throw new RuntimeConflict("runtime_configuration_changed"); },
      { parallelism: 2, max_pending: 128, poll_ms: 2000, lease_ms: 10_000, max_backoff_ms: 60_000, elapsed: () => elapsed, boot_id: boot });
    cleanup.push(() => scheduler.stop()); return scheduler;
  };
  const task = (id: string) => { const execution = { provider: "fixture", prompt: id }; jobs.set(id, { task_id: id, revision: 1, status: "waiting", workspace_id: "project", capability: "fixture",
    input: {}, assignment_digest: digest([id, "assignment-1"]), execution, execution_digest: digest(execution), active_episode: false, needs_reconciliation: false }); };
  const rows = () => db.sql.query("SELECT * FROM device_scheduled_work ORDER BY task_id,attempt").all() as { work_id: string; task_id: string; state: string; attempt: number; retry_after: number | null }[];
  const scheduler = create();
  return { root, path, db, jobs, client, calls, behavior, task, rows, scheduler, create,
    advance(ms = 2000) { now += ms; elapsed += ms; }, now: () => now, setElapsed(value: number) { elapsed = value; },
    revoke() { valid = false; }, failQueue(reason: string | null) { queueFailure = reason; }, discoveries: () => discoveries };
}

test("scheduled discovery persists one run per assignment across duplicate pages and process reopen", async () => {
  const f = fixture(); f.task("one"); f.scheduler.start(); await f.scheduler.tick(); await spin(() => f.calls.length === 1 && f.rows()[0].state === "completed");
  f.advance(); await f.scheduler.tick(); expect(f.calls).toHaveLength(1); await f.scheduler.stop();
  const other = new RuntimeDatabase(f.path, f.now); cleanup.push(() => other.close()); const restored = f.create(other); restored.start();
  f.advance(); await restored.tick(); expect(f.calls).toHaveLength(1);
  const job = f.jobs.get("one")!; job.status = "waiting"; job.revision++; job.assignment_digest = digest("explicit-reassignment");
  f.advance(); await restored.tick(); await spin(() => f.calls.length === 2 && f.rows().every(row => row.state === "completed"));
  expect(f.calls[0].id).not.toBe(f.calls[1].id); expect(f.rows()).toHaveLength(2);
});

test("parallelism is shared by one persisted scheduler owner and pauses drain without starting more work", async () => {
  const f = fixture(), release: (() => void)[] = [];
  for (const id of ["one", "two", "three"]) f.task(id);
  f.behavior.run = async (_job, admission) => { await new Promise<void>(resolve => release.push(resolve)); admission.assertCurrent(); return { status: "done" }; };
  f.scheduler.start(); await f.scheduler.tick(); await spin(() => f.calls.length === 2);
  const competitor = f.create(); expect(() => competitor.start()).toThrow("device_scheduler_already_running");
  const paused = f.scheduler.pause("pause"); release.splice(0).forEach(done => done()); await paused;
  expect(f.calls).toHaveLength(2); expect(f.scheduler.status()).toMatchObject({ enabled: false, running: false, active: 0 });
  const restored = f.create(); expect(restored.start()).toMatchObject({ enabled: false, running: false });
  f.behavior.run = async () => ({ status: "done" }); restored.start("explicit-resume"); f.advance(); await restored.tick(); await spin(() => f.calls.length === 3);
});

test("known reset waits survive reopen while quota without reset and changed revisions never become repeated probes", async () => {
  const f = fixture(); f.task("quota"); f.task("transient"); let transient = 0;
  f.behavior.run = async job => {
    f.jobs.get(job.task_id)!.revision++;
    return job.task_id === "quota" ? { status: "unavailable", reason: "quota_exhausted", retry_after: null }
      : transient++ === 0 ? { status: "unavailable", reason: "rate_limited", retry_after: f.now() + 6000 } : { status: "done" };
  };
  f.scheduler.start(); await f.scheduler.tick(); await spin(() => f.rows().every(row => row.state !== "running"));
  expect(f.rows().map(row => row.state)).toEqual(["blocked", "waiting"]); expect(f.calls).toHaveLength(2);
  await f.scheduler.stop(); const restored = f.create(); restored.start();
  for (let i = 0; i < 2; i++) { f.advance(); await restored.tick(); } expect(f.calls).toHaveLength(2);
  f.advance(); await restored.tick(); await spin(() => f.calls.length === 3 && f.rows()[1].state === "completed");
  expect(f.calls.filter(call => call.job.task_id === "quota")).toHaveLength(1);
  for (let i = 0; i < 4; i++) { f.advance(); await restored.tick(); } expect(f.calls).toHaveLength(3);
});

test("unknown outcomes are not rerun after restart; coordinator completion or an explicit verified retry is required", async () => {
  const f = fixture(); f.task("uncertain"); f.behavior.run = async () => ({ status: "unknown" });
  f.scheduler.start(); await f.scheduler.tick(); await spin(() => f.rows()[0]?.state === "unknown"); await f.scheduler.stop();
  const restored = f.create(); restored.start();
  for (let i = 0; i < 3; i++) { f.advance(); await restored.tick(); } expect(f.calls).toHaveLength(1);
  const row = f.rows()[0]; f.jobs.get("uncertain")!.needs_reconciliation = true;
  await expect(restored.retry("retry-denied", row.work_id, row.attempt)).rejects.toThrow("scheduled_retry_not_admitted");
  f.jobs.get("uncertain")!.needs_reconciliation = false; f.jobs.get("uncertain")!.status = "done";
  f.advance(); await restored.tick(); expect(f.rows()[0].state).toBe("completed"); expect(f.calls).toHaveLength(1);
});

test("blocked first pages do not starve later assignments", async () => {
  const f = fixture(); for (let i = 0; i < 36; i++) f.task(`task-${String(i).padStart(3, "0")}`);
  f.behavior.run = async job => job.task_id < "task-034" ? { status: "unavailable", reason: "quota_exhausted", retry_after: null } : { status: "done" };
  f.scheduler.start(); await f.scheduler.tick();
  for (let i = 0; i < 25; i++) { await spin(() => !f.rows().some(row => row.state === "running")); f.advance(); await f.scheduler.tick(); }
  await spin(() => f.rows().filter(row => row.state === "completed").length === 2);
  expect(f.calls).toHaveLength(36); expect(new Set(f.calls.map(call => call.job.task_id)).size).toBe(36);
});

test("elapsed lease takeover fences a paused old process and cannot let its late result overwrite recovery state", async () => {
  const f = fixture(); f.task("owned"); let release!: () => void;
  f.behavior.run = async (_job, admission) => { await new Promise<void>(resolve => { release = resolve; }); admission.assertCurrent(); return { status: "done" }; };
  f.scheduler.start(); await f.scheduler.tick(); await spin(() => f.calls.length === 1);
  f.advance(10_001); const successor = f.create(); successor.start();
  expect(() => f.calls[0].admission.assertCurrent()).toThrow("device_scheduler_lease_lost");
  expect(f.rows()[0].state).toBe("unknown"); release(); await spin(() => (f.scheduler.status().active as number) === 0);
  await f.scheduler.stop(); expect(successor.status()).toMatchObject({ lease_current: true, generation: 2 });
  f.advance(); await successor.tick(); expect(f.calls).toHaveLength(1); expect(f.rows()[0].state).toBe("unknown");
});

test("coordinator network backoff is persisted and does not produce repeated execution or human requests", async () => {
  const f = fixture(); f.task("one"); f.failQueue("coordinator_transport_unknown"); f.scheduler.start();
  await expect(f.scheduler.tick()).rejects.toThrow("coordinator_transport_unknown"); expect(f.discoveries()).toBe(1); expect(f.calls).toHaveLength(0);
  f.advance(); await f.scheduler.tick(); expect(f.discoveries()).toBe(1);
  f.failQueue(null); f.advance(); await f.scheduler.tick(); await spin(() => f.calls.length === 1);
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM tasks").get()).toEqual({ n: 0 });
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM events").get()).toEqual({ n: 0 });
});

test("configuration revocation aborts scheduled admission and invalid clocks cannot renew ownership", async () => {
  const f = fixture(); f.task("one"); let release!: () => void;
  f.behavior.run = async (_job, admission) => { await new Promise<void>(resolve => { release = resolve; }); admission.assertCurrent(); return { status: "done" }; };
  f.scheduler.start(); await f.scheduler.tick(); await spin(() => f.calls.length === 1); f.revoke();
  await expect(f.scheduler.tick()).rejects.toThrow("runtime_configuration_changed"); expect(f.calls[0].admission.signal.aborted).toBe(true);
  release(); await f.scheduler.stop(); expect(f.rows()[0].state).toBe("unknown");
  const other = fixture(); other.scheduler.start(); await other.scheduler.tick(); other.setElapsed(999);
  await expect(other.scheduler.tick()).rejects.toThrow("scheduler_clock_invalid");
});

test("a removed unknown assignment is superseded without blocking unrelated queued work", async () => {
  const f = fixture(); f.task("old"); f.behavior.run = async () => ({ status: "unknown" });
  f.scheduler.start(); await f.scheduler.tick(); await spin(() => f.rows()[0]?.state === "unknown");
  f.jobs.delete("old"); f.task("new"); f.behavior.run = async () => ({ status: "done" });
  f.advance(); await f.scheduler.tick(); await spin(() => f.rows().some(row => row.task_id === "new" && row.state === "completed"));
  expect(f.rows().find(row => row.task_id === "old")!.state).toBe("superseded"); expect(f.calls).toHaveLength(2);
});

test("a failed competing start cannot persist a success receipt or change scheduler policy", async () => {
  const f = fixture(); f.scheduler.start(); await f.scheduler.tick();
  const before = f.db.sql.query("SELECT * FROM meta WHERE key LIKE 'device-scheduler:%'").all();
  const other = f.create(); expect(() => other.start("competing-start")).toThrow("device_scheduler_already_running");
  expect(f.db.sql.query("SELECT * FROM meta WHERE key LIKE 'device-scheduler:%'").all()).toEqual(before);
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM receipts WHERE request_id='competing-start'").get()).toEqual({ n: 0 });
});

test("confirmed task failure settles execution and survives reopen without automatic retry", async () => {
  const f = fixture(); f.task("failed");
  f.behavior.run = async () => ({ status: "failed", reason: "workspace_tool_required_read_missing" });
  f.scheduler.start(); await f.scheduler.tick(); await spin(() => f.rows()[0]?.state === "completed");
  expect(f.jobs.get("failed")!.status).toBe("failed"); await f.scheduler.stop();
  const restored = f.create(); restored.start();
  for (let i = 0; i < 3; i++) { f.advance(); await restored.tick(); }
  expect(f.calls).toHaveLength(1); expect(f.rows()).toHaveLength(1);
});
