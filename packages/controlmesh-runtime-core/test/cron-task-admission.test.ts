import { expect, test } from "bun:test";
import { RuntimeDatabase } from "../src/database";
import { RuntimeKernel, type Principal } from "../src/kernel";
import { CronStore } from "../src/cron-store";
import { CronTaskAdmission } from "../src/cron-task-admission";

const actor: Principal = { id: "scheduler", origin: "schedule", device_id: "device", scopes: ["task:create", "task:read"] };
function fixture(clock: () => number = Date.now) {
  const db = new RuntimeDatabase(":memory:", clock), kernel = new RuntimeKernel(db), store = new CronStore(db);
  store.putJob({ id: "scheduled", title: "Scheduled", schedule: "* * * * *", task_folder: "scheduled", agent_instruction: "Inspect current files",
    execution_mode: "taskhub", output_policy: "summarized_only", provider: "opencode", model: "configured-model", chat_id: 123 });
  store.registerCoordinator(actor.id);
  const occurrence = store.createOccurrence("scheduled", 1773400000000);
  return { db, kernel, store, occurrence };
}

test("cron TaskIngress binds one task/attempt and schedule provenance on repeated submission", () => {
  const f = fixture();
  try {
    const admission = new CronTaskAdmission(f.kernel, actor, 1);
    const first = admission.submit(f.occurrence.occurrence_id);
    const again = admission.submit(f.occurrence.occurrence_id);
    expect(again).toEqual(first);
    expect(first.task.task.execution_context).toMatchObject({ origin: "cron", source_scope: "cron", transport: "cron" });
    expect(first.task.task.tool_grant).toMatchObject({ confirmation_policy: "controller_required" });
    expect(f.store.listAttempts(f.occurrence.occurrence_id)).toHaveLength(1);
    const origins = f.db.sql.query("SELECT DISTINCT origin FROM events WHERE task_id=?").all(first.task.task.task_id);
    expect(origins).toEqual([{ origin: "schedule" }]);
    expect(first.task.active_episode).toBeNull(); // Admission does not start a provider.
    expect(f.store.getOccurrence(f.occurrence.occurrence_id)!.state).toBe("enqueued");
    f.store.updateAttemptState(first.attempt.attempt_id, { coordinatorId: actor.id, fence: 1 }, { state: "running" });
    expect(f.store.getOccurrence(f.occurrence.occurrence_id)!.state).toBe("running");
  } finally { f.db.close(); }
});

test("failed TaskIngress authorization rolls back attempted cron linkage", () => {
  const f = fixture();
  try {
    const admission = new CronTaskAdmission(f.kernel, { ...actor, scopes: [] }, 1);
    expect(() => admission.submit(f.occurrence.occurrence_id)).toThrow("scope_denied");
    expect(f.store.listAttempts(f.occurrence.occurrence_id)).toHaveLength(0);
    expect(f.store.getOccurrence(f.occurrence.occurrence_id)!.state).toBe("scheduled");
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM tasks").get()).toEqual({ n: 0 });
  } finally { f.db.close(); }
});

test("coordinator rotation fences both submission and idempotent reads", () => {
  const f = fixture();
  try {
    const admission = new CronTaskAdmission(f.kernel, actor, 1);
    admission.submit(f.occurrence.occurrence_id);
    f.store.incrementCoordinatorEpoch(actor.id, 1);
    expect(() => admission.submit(f.occurrence.occurrence_id)).toThrow("stale_coordinator_fence");
    expect(f.store.listAttempts(f.occurrence.occurrence_id)).toHaveLength(1);
    expect(() => new CronTaskAdmission(f.kernel, actor, 2).submit(f.occurrence.occurrence_id)).toThrow("cron_attempt_requires_reconciliation");
  } finally { f.db.close(); }
});

test("disabled definition rolls back the TaskIngress task and its command receipts", () => {
  const f = fixture();
  try {
    f.store.setEnabled("scheduled", false);
    const admission = new CronTaskAdmission(f.kernel, actor, 1);
    expect(() => admission.submit(f.occurrence.occurrence_id)).toThrow("cron_definition_not_active");
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM tasks").get()).toEqual({ n: 0 });
    expect(f.store.listAttempts(f.occurrence.occurrence_id)).toHaveLength(0);
    f.store.setEnabled("scheduled", true);
    expect(admission.submit(f.occurrence.occurrence_id).task.task.status).toBe("waiting");
  } finally { f.db.close(); }
});

test("monitor disables after atomic submission and replay does not create another task", () => {
  const f = fixture();
  try {
    const job = f.store.getJob("scheduled")!;
    f.store.putJob({ ...job.raw_metadata, job_kind: "monitor" } as Parameters<CronStore["putJob"]>[0]);
    const occurrence = f.store.createOccurrence("scheduled", 1773400060000);
    const admission = new CronTaskAdmission(f.kernel, actor, 1);
    const first = admission.submit(occurrence.occurrence_id);
    expect(f.store.getJob("scheduled")!.enabled).toBe(false);
    expect(admission.submit(occurrence.occurrence_id)).toEqual(first);
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM tasks").get()).toEqual({ n: 1 });
  } finally { f.db.close(); }
});

test("future occurrence cannot create a task until its actual due instant", () => {
  let now = Date.parse("2026-06-01T13:00:00Z");
  const f = fixture(() => now);
  try {
    const occurrence = f.store.createOccurrence("scheduled", now + 60000);
    const admission = new CronTaskAdmission(f.kernel, actor, 1);
    expect(() => admission.submit(occurrence.occurrence_id)).toThrow("cron_occurrence_not_due");
    expect(f.store.listAttempts(occurrence.occurrence_id)).toHaveLength(0);
    now += 60000;
    expect(admission.submit(occurrence.occurrence_id).task.task.status).toBe("waiting");
  } finally { f.db.close(); }
});

test("explicit overnight quiet window uses configured user zone without recurrence-zone substitution", () => {
  const now = Date.parse("2026-06-01T13:00:00Z"); // 21:00 Shanghai, 09:00 New York.
  const f = fixture(() => now);
  try {
    f.store.putJob({ ...f.store.getJob("scheduled")!.raw_metadata, timezone: "America/New_York", quiet_start: 21, quiet_end: 8 } as Parameters<CronStore["putJob"]>[0]);
    const occurrence = f.store.createOccurrence("scheduled", now - 60000);
    expect(() => new CronTaskAdmission(f.kernel, actor, 1, { userTimezone: "Asia/Shanghai" }).submit(occurrence.occurrence_id)).toThrow("cron_quiet_hours");
    expect(f.store.listAttempts(occurrence.occurrence_id)).toHaveLength(0);
    expect(new CronTaskAdmission(f.kernel, actor, 1, { userTimezone: "UTC" }).submit(occurrence.occurrence_id).task.task.status).toBe("waiting");
  } finally { f.db.close(); }
});

test("shared dependency rejects competing task atomically even after the lock deadline", () => {
  let now = Date.parse("2026-06-01T13:00:00Z");
  const f = fixture(() => now);
  try {
    const template = f.store.getJob("scheduled")!.raw_metadata;
    f.store.putJob({ ...template, dependency: "shared-resource" } as Parameters<CronStore["putJob"]>[0]);
    f.store.putJob({ ...template, id: "competitor", dependency: "shared-resource" } as Parameters<CronStore["putJob"]>[0]);
    const first = f.store.createOccurrence("scheduled", now - 60000);
    const second = f.store.createOccurrence("competitor", now - 60000);
    const admission = new CronTaskAdmission(f.kernel, actor, 1);
    const submitted = admission.submit(first.occurrence_id);
    expect(f.store.getDependencyLock("shared-resource")!.active_attempt_id).toBe(submitted.attempt.attempt_id);
    expect(() => admission.submit(second.occurrence_id)).toThrow("cron_dependency_busy");
    now += 120000;
    expect(() => admission.submit(second.occurrence_id)).toThrow("cron_dependency_busy");
    expect(f.store.listAttempts(second.occurrence_id)).toHaveLength(0);
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM tasks").get()).toEqual({ n: 1 });
    f.store.incrementCoordinatorEpoch(actor.id, 1);
    expect(() => f.store.acquireDependencyLock("shared-resource", first.occurrence_id, submitted.attempt.attempt_id, 60000)).toThrow("stale_coordinator_fence");
  } finally { f.db.close(); }
});
