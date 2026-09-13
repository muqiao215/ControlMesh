import { command, requireScope } from "./commands";
import { RuntimeDatabase } from "./database";
import { decodeHostJob, mergeHostJob, type HostJob } from "./host-job-model";
import type { Principal } from "./kernel";
import { canonical, identifier, requireThat } from "./value";

export interface HostJobSnapshot { revision: number; job: HostJob }
/** Internal persistence only: a stored PID/approval is never a process dispatch capability. */
export class HostJobStore {
  constructor(private readonly db: RuntimeDatabase, private readonly authorize: () => void) {}
  private current(actor: Principal, scope: string) {
    requireScope(actor, scope);
    const result: unknown = this.authorize();
    if (result !== undefined) { void Promise.resolve(result).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
  }
  private row(principal: string, id: string): HostJobSnapshot | null {
    const row = this.db.sql.query("SELECT revision,payload FROM host_jobs WHERE principal=? AND job_id=?").get(principal, id) as { revision: number; payload: string } | null;
    if (!row) return null;
    const job = decodeHostJob(JSON.parse(row.payload)); requireThat(job.job_id === id, "host_job_identity_changed");
    return { revision: row.revision, job };
  }
  get(actor: Principal, id: string): HostJobSnapshot | null {
    this.current(actor, "task:read"); identifier(id); return this.row(actor.id, id);
  }
  list(actor: Principal, after = "", limit = 20) {
    this.current(actor, "task:read"); if (after) identifier(after);
    requireThat(Number.isSafeInteger(limit) && limit >= 1 && limit <= 100, "invalid_host_job_page");
    const rows = this.db.sql.query("SELECT job_id,revision,state,substr(json_extract(payload,'$.summary'),1,512) AS summary FROM host_jobs WHERE principal=? AND job_id>? ORDER BY job_id LIMIT ?")
      .all(actor.id, after, limit + 1) as { job_id: string; revision: number; state: string; summary: string }[];
    const jobs = rows.slice(0, limit);
    return { jobs, next_after: rows.length > limit ? jobs.at(-1)!.job_id : null };
  }
  put(actor: Principal, requestId: string, expectedRevision: number, raw: unknown): HostJobSnapshot {
    this.current(actor, "task:admin");
    requireThat(Number.isSafeInteger(expectedRevision) && expectedRevision >= 0, "invalid_host_job_revision");
    const incoming = decodeHostJob(raw);
    return command(this.db, actor, requestId, "host_job.put", { expected_revision: expectedRevision, job: incoming }, () => {
      this.current(actor, "task:admin");
      const prior = this.row(actor.id, incoming.job_id);
      requireThat((prior?.revision ?? 0) === expectedRevision, "host_job_revision_conflict");
      if (prior) requireThat(["repo", "source_task_id", "plan_id"].every(key => prior.job[key as keyof HostJob] === incoming[key as keyof HostJob]), "host_job_binding_changed");
      const job = prior ? mergeHostJob(prior.job, incoming) : incoming;
      const revision = expectedRevision + 1; requireThat(Number.isSafeInteger(revision), "invalid_host_job_revision");
      this.db.sql.query("INSERT INTO host_jobs(principal,job_id,revision,state,payload) VALUES(?,?,?,?,?) ON CONFLICT(principal,job_id) DO UPDATE SET revision=excluded.revision,state=excluded.state,payload=excluded.payload")
        .run(actor.id, job.job_id, revision, job.state, canonical(job));
      return { revision, job };
    }, value => { this.current(actor, "task:admin"); return value; });
  }
}
