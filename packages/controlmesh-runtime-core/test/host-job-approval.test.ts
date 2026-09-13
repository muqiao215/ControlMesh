import { expect, test } from "bun:test";
import { RuntimeDatabase } from "../src/database";
import { HostJobStore } from "../src/host-job-store";
import { HostJobApprovals } from "../src/host-job-approval";
import type { Principal } from "../src/kernel";
const actor: Principal = { id: "owner", origin: "human_request", device_id: "desktop", scopes: ["task:read", "task:admin", "task:execute"] };
const raw = { job_id: "job", created_at: "2026-09-13", updated_at: "2026-09-13", steps: [
  { id: "one", command: "echo one", approval_required: true, approved_at: "imported", approved_by: "somebody" },
  { id: "two", command: "echo two", approval_required: true }] };
test("host approval requires a runtime-issued human receipt and the current exact next step", () => {
  const db = new RuntimeDatabase(":memory:"), store = new HostJobStore(db, () => {}), approvals = new HostJobApprovals(db, () => {});
  try {
    const saved = store.put(actor, "create", 0, raw);
    expect(() => approvals.approve({ ...actor, origin: "agent_message" }, "bot", "job", 1, "one")).toThrow("host_job_human_approval_required");
    expect(() => approvals.approve(actor, "skip", "job", 1, "two")).toThrow("host_job_step_not_next");
    const proof = approvals.approve(actor, "approve", "job", 1, "one");
    expect(approvals.approve(actor, "approve", "job", 1, "one")).toEqual(proof);
    expect(approvals.assertApproved({ ...actor, origin: "internal" }, proof)).toEqual(proof);
    expect(() => approvals.assertApproved(actor, { ...proof, request_id: "forged" })).toThrow("host_job_approval_unproven");
    expect(() => approvals.assertApproved(actor, { ...proof, approved_at: "changed" })).toThrow("host_job_approval_unproven");
    expect(() => approvals.assertApproved({ ...actor, id: "other" }, proof)).toThrow("invalid_host_job_approval");
    expect(() => approvals.assertApproved({ ...actor, scopes: ["task:read"] }, proof)).toThrow("scope_denied");
    store.put(actor, "update", 1, { ...saved.job, summary: "new revision" });
    expect(() => approvals.assertApproved(actor, proof)).toThrow("host_job_revision_conflict");
    expect(() => approvals.approve(actor, "approve", "job", 2, "one")).toThrow("idempotency_conflict");
  } finally { db.close(); }
});
test("imported running step requires reconciliation even when approval metadata exists", () => {
  const db = new RuntimeDatabase(":memory:"), store = new HostJobStore(db, () => {});
  try {
    store.put(actor, "import", 0, { ...raw, state: "running", steps: [{ ...raw.steps[0], state: "running", pid: 12345 }] });
    expect(() => new HostJobApprovals(db, () => {}).approve(actor, "approve", "job", 1, "one")).toThrow("host_job_reconciliation_required");
    expect(db.sql.query("SELECT COUNT(*) AS n FROM receipts WHERE request_id='approve'").get()).toEqual({ n: 0 });
  } finally { db.close(); }
});

test("host-job CLI names the current step and revision without accepting issuer fields", async () => {
  const { parseRuntimeCli } = await import("../src/runtime-cli");
  expect(parseRuntimeCli(["host-jobs", "--socket", "/tmp/cm.sock"])?.request).toMatchObject({ op: "host_jobs", limit: 20 });
  expect(parseRuntimeCli(["inspect-host-job", "job", "--socket", "/tmp/cm.sock"])?.request).toMatchObject({ op: "inspect_host_job", job_id: "job" });
  expect(parseRuntimeCli(["approve-host-step", "job", "--socket", "/tmp/cm.sock", "--step", "one", "--revision", "3"])?.request).toMatchObject({ op: "approve_host_step", job_id: "job", step_id: "one", expected_revision: 3 });
  expect(() => parseRuntimeCli(["approve-host-step", "job", "--socket", "/tmp/cm.sock", "--step", "one"])).toThrow("missing_cli_option");
  expect(() => parseRuntimeCli(["approve-host-step", "job", "--socket", "/tmp/cm.sock", "--approved-by", "user"])).toThrow("unknown_cli_option");
});

test("whole-job authorization fixes remaining step order, definitions and revision progression", () => {
  const db = new RuntimeDatabase(":memory:"), store = new HostJobStore(db, () => {}), approvals = new HostJobApprovals(db, () => {});
  try {
    const initial = store.put(actor, "create", 0, raw);
    expect(() => approvals.approvePlan({ ...actor, origin: "schedule" }, "cron", "job", 1)).toThrow("host_job_human_approval_required");
    const plan = approvals.approvePlan(actor, "plan", "job", 1);
    expect(plan.steps.map(step => [step.step_id, step.revision])).toEqual([["one", 1], ["two", 3]]);
    const first = approvals.planStep(actor, plan, 0), second = approvals.planStep(actor, plan, 1);
    expect(approvals.assertApproved(actor, first)).toEqual(first);
    expect(() => approvals.assertApproved(actor, second)).toThrow("host_job_revision_conflict");
    expect(() => approvals.planStep(actor, { ...plan, steps: [...plan.steps].reverse() }, 0)).toThrow("host_job_plan_approval_unproven");
    expect(() => approvals.assertApproved(actor, { ...first, plan_step_index: 1 })).toThrow("host_job_plan_approval_unproven");
    expect(() => approvals.planStep({ ...actor, id: "other" }, plan, 0)).toThrow("invalid_host_job_plan_approval");
    expect(() => approvals.planStep(actor, plan, 2)).toThrow("invalid_host_job_plan_step");
    const running = store.put(actor, "running", 1, { ...initial.job, state: "running", steps: initial.job.steps.map(step => step.id === "one" ? { ...step, state: "running" } : step) });
    expect(() => approvals.approvePlan(actor, "during", "job", 2)).toThrow("host_job_plan_not_pending");
    const completed = store.put(actor, "result", running.revision, { ...running.job, steps: running.job.steps.map(step => step.id === "one" ? { ...step, state: "completed" } : step) });
    expect(approvals.approvePlan(actor, "plan", "job", 1)).toEqual(plan);
    expect(approvals.inspectReceipt(actor, first)).toEqual(first);
    expect(approvals.assertApproved(actor, second)).toEqual(second);
    store.put(actor, "extra-change", completed.revision, { ...completed.job, summary: "changed after approval" });
    expect(() => approvals.assertApproved(actor, second)).toThrow("host_job_revision_conflict");
    expect(() => approvals.inspectPlan({ ...actor, scopes: [] }, plan)).toThrow("scope_denied");
  } finally { db.close(); }
});
