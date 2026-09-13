import { expect, test } from "bun:test";
import { RuntimeDatabase } from "../src/database";
import { RuntimeKernel, type Principal } from "../src/kernel";
import { CronStore } from "../src/cron-store";
import { CronTaskAdmission } from "../src/cron-task-admission";
import { reconcileCronTaskResults } from "../src/cron-task-results";

const actor: Principal = { id: "owner", origin: "schedule", device_id: "device",
  scopes: ["task:create", "task:read", "task:execute", "task:reconcile", "task:admin"] };
for (const outcome of ["done", "failed", "unknown"] as const) test(`kernel ${outcome} evidence controls cron state and dependency release`, () => {
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
    const lease = kernel.claim(actor, "claim", admitted.task.task.task_id, admitted.task.revision, 60000);
    expect(reconcileCronTaskResults(kernel, actor, 1)).toBe(0);
    kernel.start(actor, "start", lease);
    kernel.dispatchEffect(actor, "dispatch", lease, "effect", { fixture: true });
    expect(reconcileCronTaskResults(kernel, actor, 1)).toBe(1);
    expect(store.getAttempt(admitted.attempt.attempt_id)?.state).toBe("running");
    expect(store.getDependencyLock("resource")).not.toBeNull();
    if (outcome === "unknown") {
      now += 60001;
      kernel.recoverExpired(actor);
      expect(reconcileCronTaskResults(kernel, actor, 1)).toBe(1);
      expect(store.getAttempt(admitted.attempt.attempt_id)?.state).toBe("uncertain");
      expect(store.getDependencyLock("resource")).not.toBeNull();
      expect(reconcileCronTaskResults(kernel, actor, 1)).toBe(0);
      return;
    }
    expect(() => kernel.finish(actor, "premature", lease, outcome, {})).toThrow("unresolved_effects");
    kernel.confirmEffect(actor, "confirm", lease, "effect", { fixture: true });
    kernel.finish(actor, "finish", lease, outcome, { fixture: true });
    expect(reconcileCronTaskResults(kernel, actor, 1)).toBe(1);
    expect(store.getAttempt(admitted.attempt.attempt_id)?.state).toBe(outcome === "done" ? "completed" : "failed");
    expect(store.getDependencyLock("resource")).toBeNull();
    expect(reconcileCronTaskResults(kernel, actor, 1)).toBe(0);
    store.incrementCoordinatorEpoch(actor.id, 1);
    expect(() => reconcileCronTaskResults(kernel, actor, 1)).toThrow("stale_coordinator_fence");
  } finally { db.close(); }
});
