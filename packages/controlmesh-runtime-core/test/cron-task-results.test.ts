import { expect, test } from "bun:test";
import { RuntimeDatabase } from "../src/database";
import { RuntimeKernel, type Principal } from "../src/kernel";
import { CronStore } from "../src/cron-store";
import { CronTaskAdmission } from "../src/cron-task-admission";
import { reconcileCronTaskResults } from "../src/cron-task-results";

const actor: Principal = { id: "owner", origin: "schedule", device_id: "device",
  scopes: ["task:create", "task:read", "task:execute", "task:reconcile", "task:admin", "task:cancel"] };
for (const outcome of ["done", "failed", "unknown", "cancel_queued", "cancel_dispatched", "done_after_restart", "failed_after_restart", "done_after_device_change", "failed_after_device_change"] as const) test(`kernel ${outcome} evidence controls cron state and dependency release`, () => {
  let now = Date.now();
  const db = new RuntimeDatabase(":memory:", () => now);
  try {
    const kernel = new RuntimeKernel(db), store = new CronStore(db);
    store.registerCoordinator(actor.id);
    store.putJob({ id: "job", title: "Job", schedule: "* * * * *", task_folder: "job", agent_instruction: "Inspect",
      provider: "opencode", execution_mode: "taskhub", output_policy: "summarized_only", dependency: "resource" });
    const occurrence = store.createOccurrence("job", 1773400000000);
    const admitted = new CronTaskAdmission(kernel, actor, 1).submit(occurrence.occurrence_id);
    expect(reconcileCronTaskResults(kernel, actor, 1)).toBe(0);
    if (outcome === "cancel_queued") {
      kernel.cancel(actor, "cancel", admitted.task.task.task_id, admitted.task.revision);
      expect(reconcileCronTaskResults(kernel, actor, 1)).toBe(1);
      expect(store.getAttempt(admitted.attempt.attempt_id)).toMatchObject({ state: "failed", result_status: "cancelled" });
      expect(store.getDependencyLock("resource")).toBeNull();
      expect(reconcileCronTaskResults(kernel, actor, 1)).toBe(0);
      return;
    }
    const lease = kernel.claim(actor, "claim", admitted.task.task.task_id, admitted.task.revision, 60000);
    expect(reconcileCronTaskResults(kernel, actor, 1)).toBe(0);
    kernel.start(actor, "start", lease);
    kernel.dispatchEffect(actor, "dispatch", lease, "effect", { fixture: true });
    expect(reconcileCronTaskResults(kernel, actor, 1)).toBe(1);
    expect(store.getAttempt(admitted.attempt.attempt_id)?.state).toBe("running");
    expect(store.getDependencyLock("resource")).not.toBeNull();
    if (outcome === "cancel_dispatched") {
      const current = kernel.inspect(actor, admitted.task.task.task_id);
      kernel.cancel(actor, "cancel", current.task.task_id, current.revision);
      expect(reconcileCronTaskResults(kernel, actor, 1)).toBe(1);
      expect(store.getAttempt(admitted.attempt.attempt_id)).toMatchObject({ state: "uncertain", result_status: "cancelled" });
      expect(store.getDependencyLock("resource")).not.toBeNull();
      expect(reconcileCronTaskResults(kernel, actor, 1)).toBe(0);
      return;
    }
    if (outcome === "unknown") {
      now += 60001;
      kernel.recoverExpired(actor);
      expect(reconcileCronTaskResults(kernel, actor, 1)).toBe(1);
      expect(store.getAttempt(admitted.attempt.attempt_id)?.state).toBe("uncertain");
      expect(store.getDependencyLock("resource")).not.toBeNull();
      expect(reconcileCronTaskResults(kernel, actor, 1)).toBe(0);
      return;
    }
    const terminal = outcome.startsWith("done") ? "done" : "failed";
    const restarted = outcome.includes("_after_"), generation = restarted ? 2 : 1;
    const reviewer = outcome.endsWith("device_change") ? { ...actor, device_id: "replacement-device" } : actor;
    if (restarted) {
      store.incrementCoordinatorEpoch(actor.id, 1);
      expect(() => reconcileCronTaskResults(kernel, actor, 1)).toThrow("stale_coordinator_fence");
      expect(reconcileCronTaskResults(kernel, reviewer, 2)).toBe(0);
      expect(store.getDependencyLock("resource")).not.toBeNull();
    }
    expect(() => kernel.finish(actor, "premature", lease, terminal, {})).toThrow("unresolved_effects");
    kernel.confirmEffect(actor, "confirm", lease, "effect", { fixture: true });
    kernel.finish(actor, "finish", lease, terminal, { fixture: true });
    if (reviewer.device_id !== actor.device_id) {
      db.sql.query("UPDATE episodes SET device_id=? WHERE episode_id=?").run(reviewer.device_id!, lease.episode_id);
      expect(() => reconcileCronTaskResults(kernel, reviewer, generation)).toThrow("cron_terminal_evidence_unconfirmed");
      expect(store.getDependencyLock("resource")).not.toBeNull();
      db.sql.query("UPDATE episodes SET device_id=? WHERE episode_id=?").run(actor.device_id!, lease.episode_id);
    }
    expect(reconcileCronTaskResults(kernel, reviewer, generation)).toBe(1);
    expect(store.getAttempt(admitted.attempt.attempt_id)?.state).toBe(terminal === "done" ? "completed" : "failed");
    expect(store.getAttempt(admitted.attempt.attempt_id)?.fencing_generation).toBe(1);
    expect(store.getAttempt(admitted.attempt.attempt_id)?.executor_device_id).toBe(actor.device_id);
    expect(store.getDependencyLock("resource")).toBeNull();
    expect(reconcileCronTaskResults(kernel, reviewer, generation)).toBe(0);
    store.incrementCoordinatorEpoch(actor.id, generation);
    expect(() => reconcileCronTaskResults(kernel, actor, generation)).toThrow("stale_coordinator_fence");
  } finally { db.close(); }
});
