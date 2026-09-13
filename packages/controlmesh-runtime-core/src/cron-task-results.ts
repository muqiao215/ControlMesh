import { requireScope } from "./commands";
import { CronStore } from "./cron-store";
import type { Principal, RuntimeKernel } from "./kernel";
import { requireThat } from "./value";

/** Project accepted kernel results; never infer completion from process/queue exit. */
export function reconcileCronTaskResults(kernel: RuntimeKernel, actor: Principal, generation: number): number {
  requireScope(actor, "task:read"); requireScope(actor, "task:reconcile");
  const store = new CronStore(kernel.db), authority = { coordinatorId: actor.id, fence: generation };
  return kernel.db.transaction(() => {
    requireThat(store.getCoordinatorEpoch(actor.id).current_generation === generation, "stale_coordinator_fence");
    const rows = kernel.db.sql.query(`SELECT attempt_id FROM cron_execution_attempts
      WHERE coordinator_id=? AND fencing_generation<=? AND task_id IS NOT NULL
      AND state IN ('initiated','running','cancelling','uncertain') ORDER BY attempt_id LIMIT 4097`)
      .all(actor.id, generation) as { attempt_id: string }[];
    requireThat(rows.length <= 4096, "cron_result_scan_limit");
    let changed = 0;
    for (const row of rows) {
      const attempt = store.getAttempt(row.attempt_id)!, task = kernel.inspect(actor, attempt.task_id!);
      const currentAttempt = attempt.fencing_generation === generation;
      requireThat(task.task.cron_occurrence_id === attempt.occurrence_id, "cron_task_result_binding_mismatch");
      if (task.needs_reconciliation) {
        if (currentAttempt && attempt.state !== "uncertain") { store.updateAttemptState(attempt.attempt_id, authority, { state: "uncertain" }); changed++; }
        continue;
      }
      if (task.active_episode) {
        const active = kernel.db.sql.query("SELECT state FROM episodes WHERE episode_id=? AND task_id=? AND fence=?")
          .get(task.active_episode, attempt.task_id!, task.fence) as { state: string } | null;
        if (currentAttempt && attempt.state === "initiated" && active?.state === "running") {
          store.updateAttemptState(attempt.attempt_id, authority, { state: "running" }); changed++;
        }
        continue;
      }
      const status = task.task.status;
      if (status !== "done" && status !== "failed" && status !== "cancelled") continue;
      const unresolved = kernel.db.sql.query("SELECT 1 FROM effects WHERE task_id=? AND state!='confirmed'").get(attempt.task_id!);
      if (status === "cancelled") {
        // Cancellation revokes execution authority but cannot retract dispatched effects.
        if (unresolved) {
          if (currentAttempt && attempt.state !== "uncertain") {
            store.updateAttemptState(attempt.attempt_id, authority, { state: "uncertain", resultStatus: "cancelled" }); changed++;
          }
          continue;
        }
        requireThat(!kernel.db.sql.query("SELECT 1 FROM episodes WHERE task_id=? AND state IN ('leased','running')")
          .get(attempt.task_id!), "cron_cancellation_not_quiescent");
      } else {
        const episode = kernel.db.sql.query("SELECT episode_id,state,device_id FROM episodes WHERE task_id=? AND fence=?")
          .get(attempt.task_id!, task.fence) as { episode_id: string; state: string; device_id: string } | null;
        requireThat(episode && episode.state === status && episode.device_id === attempt.executor_device_id
          && !unresolved, "cron_terminal_evidence_unconfirmed");
      }
      const state = status === "done" ? "completed" : "failed";
      const locks = kernel.db.sql.query("SELECT dependency,status FROM cron_dependency_locks WHERE active_attempt_id=?")
        .all(attempt.attempt_id) as { dependency: string; status: string }[];
      requireThat(locks.length <= 1, "cron_attempt_dependency_mismatch");
      store.acceptReconciledAttemptResult(attempt.attempt_id, authority, attempt.fencing_generation, { state, status });
      const occurrence = store.getOccurrence(attempt.occurrence_id)!;
      if (store.getJob(occurrence.job_id)) store.recordRunStatus(occurrence.job_id, status === "done" ? "success" : status);
      changed++;
    }
    return changed;
  });
}
