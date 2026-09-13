import { expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { RuntimeDatabase } from "../src/database";
import { RuntimeKernel, type Principal } from "../src/kernel";
import { CronStore } from "../src/cron-store";
import { CronScheduler } from "../src/cron-scheduler";

const actor: Principal = { id: "scheduler", origin: "schedule", device_id: "device", scopes: ["task:create", "task:read"] };
const job = { id: "scheduled", title: "Scheduled", schedule: "* * * * *", task_folder: "scheduled", agent_instruction: "Inspect",
  execution_mode: "taskhub", output_policy: "summarized_only", provider: "opencode", model: "configured-model", chat_id: 123 };

test("durable cursor plans forward, survives reopen and skips overlap without backfill storm", () => {
  const root = mkdtempSync(join(tmpdir(), "cron-scheduler-")), path = join(root, "runtime.sqlite");
  let now = Date.parse("2026-06-01T12:00:00Z"), db = new RuntimeDatabase(path, () => now);
  try {
    let store = new CronStore(db); store.putJob(job); store.registerCoordinator(actor.id);
    let scheduler = new CronScheduler(new RuntimeKernel(db), actor, 1);
    expect(scheduler.tick()[0]).toMatchObject({ next_at: now + 60000, task_id: null, changed: true });
    expect(scheduler.tick()[0].changed).toBe(false);
    now += 60000;
    const submitted = scheduler.tick()[0];
    expect(submitted.task_id).not.toBeNull();
    expect(db.sql.query("SELECT COUNT(*) AS n FROM tasks").get()).toEqual({ n: 1 });
    db.close(); db = new RuntimeDatabase(path, () => now);
    scheduler = new CronScheduler(new RuntimeKernel(db), actor, 1); store = new CronStore(db);
    expect(scheduler.tick()[0].changed).toBe(false);
    now += 3600000;
    expect(scheduler.tick()[0]).toMatchObject({ reason: "active_or_uncertain_attempt_exists", next_at: now + 60000 });
    expect(store.listOccurrences()).toHaveLength(2); // One saved slot, not sixty missed runs.
    expect(db.sql.query("SELECT COUNT(*) AS n FROM tasks").get()).toEqual({ n: 1 });
    const first = store.listOccurrences()[0], attempt = store.listAttempts(first.occurrence_id)[0];
    store.updateAttemptState(attempt.attempt_id, { coordinatorId: actor.id, fence: 1 }, { state: "completed" });
    now += 60000;
    expect(scheduler.tick()[0].reason).toBeNull();
    expect(db.sql.query("SELECT COUNT(*) AS n FROM tasks").get()).toEqual({ n: 2 });
  } finally { db.close(); rmSync(root, { recursive: true, force: true }); }
});

test("quiet slots are recorded as skipped and never become tasks", () => {
  let now = Date.parse("2026-06-01T21:00:00Z");
  const db = new RuntimeDatabase(":memory:", () => now);
  try {
    const store = new CronStore(db); store.putJob({ ...job, quiet_start: 21, quiet_end: 8 }); store.registerCoordinator(actor.id);
    const scheduler = new CronScheduler(new RuntimeKernel(db), actor, 1);
    scheduler.tick(); now += 60000;
    expect(scheduler.tick()[0]).toMatchObject({ reason: "cron_quiet_hours", pending: null, next_at: now + 60000 });
    expect(store.listOccurrences()[0].state).toBe("skipped_quiet");
    expect(db.sql.query("SELECT COUNT(*) AS n FROM tasks").get()).toEqual({ n: 0 });
  } finally { db.close(); }
});

test("busy dependency keeps the same pending occurrence across ticks", () => {
  let now = Date.parse("2026-06-01T12:00:00Z");
  const db = new RuntimeDatabase(":memory:", () => now);
  try {
    const store = new CronStore(db);
    store.putJob({ ...job, dependency: "resource" }); store.putJob({ ...job, id: "waiting", dependency: "resource" });
    store.registerCoordinator(actor.id);
    const scheduler = new CronScheduler(new RuntimeKernel(db), actor, 1);
    scheduler.tick(); now += 60000;
    const pending = scheduler.tick().find(row => row.job_id === "waiting")!;
    expect(pending.reason).toBe("cron_dependency_busy");
    expect(pending.pending).not.toBeNull();
    expect(scheduler.tick().find(row => row.job_id === "waiting")).toMatchObject({ pending: pending.pending, changed: false });
    expect(store.listOccurrences("waiting")).toHaveLength(1);
    const running = store.listOccurrences("scheduled")[0], attempt = store.listAttempts(running.occurrence_id)[0];
    store.updateAttemptState(attempt.attempt_id, { coordinatorId: actor.id, fence: 1 }, { state: "completed" });
    store.releaseDependencyLock("resource", { attemptId: attempt.attempt_id, coordinatorId: actor.id, fence: 1 });
    expect(scheduler.tick().find(row => row.job_id === "waiting")).toMatchObject({ pending: null, reason: null });
  } finally { db.close(); }
});

test("loop aborts cleanly and coordinator rotation stops stale scheduling", async () => {
  const db = new RuntimeDatabase(":memory:", () => Date.parse("2026-06-01T12:00:00Z"));
  try {
    const store = new CronStore(db); store.putJob(job); store.registerCoordinator(actor.id);
    const scheduler = new CronScheduler(new RuntimeKernel(db), actor, 1, { intervalMs: 100 });
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 20);
    try { await scheduler.run(controller.signal); } finally { clearTimeout(timer); }
    expect(db.sql.query("SELECT COUNT(*) AS n FROM tasks").get()).toEqual({ n: 0 });
    store.incrementCoordinatorEpoch(actor.id, 1);
    expect(() => scheduler.tick()).toThrow("stale_coordinator_fence");
  } finally { db.close(); }
});
