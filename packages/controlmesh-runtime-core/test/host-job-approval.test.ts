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
