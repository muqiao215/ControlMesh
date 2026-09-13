import { command, commandReceipt, requireScope } from "./commands";
import { CronStore } from "./cron-store";
import type { RuntimeDatabase } from "./database";
import type { Principal } from "./kernel";
import { directoryIdentity } from "./providers/native-manifest";
import { canonical, digest, identifier, requireThat } from "./value";

export interface CronApproval {
  schema_version: "controlmesh.cron_approval.v1";
  request_id: string; principal: string; device_id: string | null;
  occurrence_id: string; binding: string; generation: number; expires_at: number;
}
export interface CronApprovalControl {
  approve(requestId: string, occurrenceId: string, expiresAt: number): CronApproval;
  revoke(requestId: string, approval: CronApproval): void;
}

/** One occurrence per receipt. This authorizes no process by itself. */
export class CronApprovals {
  constructor(private readonly db: RuntimeDatabase, private readonly workspace: string,
    private readonly configurationDigest: string, private readonly generation: number,
    private readonly authorize: () => void) {
    requireThat(/^[a-f0-9]{64}$/.test(configurationDigest), "invalid_cron_approval_configuration");
  }
  private current(actor: Principal, scope: string): void {
    requireScope(actor, scope);
    const result: unknown = this.authorize();
    if (result !== undefined) { void Promise.resolve(result).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    requireThat(new CronStore(this.db).getCoordinatorEpoch(actor.id).current_generation === this.generation, "stale_coordinator_fence");
  }
  private binding(occurrenceId: string): string {
    identifier(occurrenceId);
    const store = new CronStore(this.db), occurrence = store.getOccurrence(occurrenceId);
    requireThat(occurrence, "occurrence_not_found");
    const job = store.getJob(occurrence.job_id);
    requireThat(job && job.storage_spec_digest === occurrence.definition_digest
      && job.storage_version === occurrence.schedule_revision, "cron_approval_definition_changed");
    const workspace = directoryIdentity(this.workspace);
    requireThat(workspace.path === this.workspace, "cron_workspace_not_canonical");
    return digest({ occurrence_id: occurrenceId, definition: occurrence.definition_digest,
      revision: occurrence.schedule_revision, workspace, configuration: this.configurationDigest });
  }
  private key(actor: Principal, requestId: string) { return `cron_approval_revoked:${digest([actor.id, requestId])}`; }
  approve(actor: Principal, requestId: string, occurrenceId: string, expiresAt: number): CronApproval {
    this.current(actor, "task:admin");
    requireThat(actor.origin === "human_request", "cron_human_approval_required");
    return this.db.transaction(() => {
      this.current(actor, "task:admin");
      requireThat(Number.isSafeInteger(expiresAt) && expiresAt > this.db.now() && expiresAt <= this.db.now() + 86400000, "invalid_cron_approval_expiry");
      const binding = this.binding(occurrenceId), body = { occurrence_id: occurrenceId, binding, generation: this.generation, expires_at: expiresAt };
      requireThat(new CronStore(this.db).getOccurrence(occurrenceId)?.state === "scheduled", "cron_approval_already_started");
      const approval = command<CronApproval>(this.db, actor, requestId, "cron.approve", body, () => ({
        schema_version: "controlmesh.cron_approval.v1", request_id: requestId, principal: actor.id,
        device_id: actor.device_id ?? null, ...body,
      }));
      return this.inspect(actor, approval);
    });
  }
  inspect(actor: Principal, approval: CronApproval): CronApproval {
    this.current(actor, "task:read");
    return this.db.transaction(() => {
      this.current(actor, "task:read");
      requireThat(approval?.schema_version === "controlmesh.cron_approval.v1" && approval.principal === actor.id
        && approval.generation === this.generation && Number.isSafeInteger(approval.expires_at)
        && approval.expires_at > this.db.now(), "cron_approval_expired_or_foreign");
      const binding = this.binding(approval.occurrence_id);
      requireThat(binding === approval.binding, "cron_approval_binding_changed");
      const issuer = { ...actor, origin: "human_request" as const, device_id: approval.device_id ?? undefined };
      const stored = commandReceipt<CronApproval>(this.db, issuer, approval.request_id, "cron.approve",
        { occurrence_id: approval.occurrence_id, binding, generation: this.generation, expires_at: approval.expires_at });
      requireThat(stored && canonical(stored.value) === canonical(approval), "cron_approval_unproven");
      requireThat(!this.db.sql.query("SELECT 1 FROM meta WHERE key=?").get(this.key(actor, approval.request_id)), "cron_approval_revoked");
      return structuredClone(stored.value);
    });
  }
  revoke(actor: Principal, requestId: string, approval: CronApproval): void {
    this.current(actor, "task:admin"); requireThat(actor.origin === "human_request", "cron_human_approval_required");
    command(this.db, actor, requestId, "cron.revoke_approval", approval, () => {
      this.inspect(actor, approval);
      this.db.sql.query("INSERT INTO meta(key,value) VALUES (?,?)").run(this.key(actor, approval.request_id), canonical({ revoked_at: this.db.now() }));
      return { revoked: true };
    });
  }
}
