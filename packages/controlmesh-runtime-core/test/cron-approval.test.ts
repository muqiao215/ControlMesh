import { expect, test } from "bun:test";
import { mkdtempSync, renameSync, mkdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { RuntimeDatabase } from "../src/database";
import { CronStore } from "../src/cron-store";
import { CronApprovals } from "../src/cron-approval";
import type { Principal } from "../src/kernel";
import { RuntimeKernel } from "../src/kernel";
import { CronTaskAdmission } from "../src/cron-task-admission";
import { decodeToolGrant, enforceProviderConfirmation } from "../src/execution-grants";

for (const provider of ["claude", "opencode"] as const) test(`${provider} approval permits reject JSON copies, other tasks, changed grants and revocation`, () => {
  const workspace = mkdtempSync(join(tmpdir(), "cm-cron-permit-")), db = new RuntimeDatabase(":memory:");
  try {
    const actor: Principal = { id: "owner", device_id: "device", origin: "human_request", scopes: ["task:create", "task:admin", "task:read"] };
    const kernel = new RuntimeKernel(db), store = new CronStore(db); store.registerCoordinator(actor.id);
    store.putJob({ id: "job", title: "Job", schedule: "* * * * *", task_folder: "job", agent_instruction: "Inspect",
      provider, model: "fixture", execution_mode: "taskhub", output_policy: "summarized_only" });
    const occurrence = store.createOccurrence("job", Date.now() - 1000);
    const approvals = new CronApprovals(db, workspace, "a".repeat(64), 1, () => {});
    const receipt = approvals.approve(actor, "approve", occurrence.occurrence_id, Date.now() + 60000);
    const task = new CronTaskAdmission(kernel, { ...actor, origin: "schedule" }, 1, { workspace }).submit(occurrence.occurrence_id).task.task;
    const permit = approvals.forTask(actor, task), grant = decodeToolGrant(task.tool_grant);
    expect(() => enforceProviderConfirmation(provider, grant, undefined, { permit, task_id: task.task_id })).not.toThrow();
    expect(() => enforceProviderConfirmation(provider, grant, undefined, { permit: structuredClone(permit), task_id: task.task_id })).toThrow("controller_approval_unproven");
    expect(() => enforceProviderConfirmation(provider, grant, undefined, { permit, task_id: "another" })).toThrow("controller_approval_unproven");
    expect(() => enforceProviderConfirmation(provider, { ...grant, tool_deny: ["Bash"] }, undefined, { permit, task_id: task.task_id })).toThrow("controller_approval_unproven");
    approvals.revoke(actor, "revoke", receipt);
    expect(() => enforceProviderConfirmation(provider, grant, undefined, { permit, task_id: task.task_id })).toThrow("cron_approval_revoked");
  } finally { db.close(); rmSync(workspace, { recursive: true, force: true }); }
});

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
