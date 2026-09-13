import { expect, test } from "bun:test";
import { mkdtempSync, renameSync, mkdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { RuntimeDatabase } from "../src/database";
import { CronStore } from "../src/cron-store";
import { CronApprovals } from "../src/cron-approval";
import type { Principal } from "../src/kernel";

for (const change of ["revoke", "expire", "definition", "workspace", "configuration", "generation"] as const) test(`cron approval becomes unusable after ${change}`, () => {
  const root = mkdtempSync(join(tmpdir(), "cm-cron-approval-")), workspace = join(root, "repo"); mkdirSync(workspace);
  let now = Date.now();
  const db = new RuntimeDatabase(join(root, "runtime.sqlite"), () => now);
  try {
    const actor: Principal = { id: "owner", device_id: "device", origin: "human_request", scopes: ["task:admin", "task:read"] };
    const store = new CronStore(db); store.registerCoordinator(actor.id);
    const job = { id: "job", title: "Job", schedule: "* * * * *", task_folder: "job", agent_instruction: "Inspect" };
    store.putJob(job);
    const occurrence = store.createOccurrence(job.id, now), other = store.createOccurrence(job.id, now + 60000);
    const approvals = () => new CronApprovals(db, workspace, "a".repeat(64), 1, () => {});
    expect(() => approvals().approve({ ...actor, origin: "schedule" }, "automatic", occurrence.occurrence_id, now + 1000)).toThrow("cron_human_approval_required");
    const granted = approvals().approve(actor, "approve", occurrence.occurrence_id, now + 1000);
    expect(approvals().inspect(actor, granted)).toEqual(granted);
    expect(() => approvals().inspect(actor, { ...granted, occurrence_id: other.occurrence_id })).toThrow();
    expect(() => approvals().inspect(actor, { ...granted, request_id: "forged" })).toThrow("cron_approval_unproven");
    if (change === "revoke") {
      approvals().revoke(actor, "revoke", granted); approvals().revoke(actor, "revoke", granted);
      expect(() => approvals().approve(actor, "approve", occurrence.occurrence_id, now + 1000)).toThrow("cron_approval_revoked");
    }
    if (change === "expire") now += 1001;
    if (change === "definition") store.putJob({ ...job, agent_instruction: "Changed scope" });
    if (change === "workspace") { renameSync(workspace, join(root, "old")); mkdirSync(workspace); }
    if (change === "generation") store.incrementCoordinatorEpoch(actor.id, 1);
    const verifier = change === "configuration" ? new CronApprovals(db, workspace, "b".repeat(64), 1, () => {}) : approvals();
    expect(() => verifier.inspect(actor, granted)).toThrow();
    expect(db.sql.query("SELECT COUNT(*) AS n FROM tasks").get()).toEqual({ n: 0 });
  } finally { db.close(); rmSync(root, { recursive: true, force: true }); }
});
