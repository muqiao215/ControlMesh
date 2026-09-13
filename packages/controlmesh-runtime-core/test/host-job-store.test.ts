import { expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { RuntimeDatabase } from "../src/database";
import { HostJobStore } from "../src/host-job-store";
import type { Principal } from "../src/kernel";

const actor: Principal = { id: "owner", origin: "human_request", scopes: ["task:read", "task:admin"] };
const job = { job_id: "job", repo: "/project", created_at: "2026-09-13", updated_at: "2026-09-13", steps: [{ id: "one", command: "echo fixture" }] };
test("host job store upgrades, isolates owners and rejects stale concurrent writers", () => {
  const root = mkdtempSync(join(tmpdir(), "cm-host-store-")), path = join(root, "runtime.sqlite");
  let a = new RuntimeDatabase(path); let b: RuntimeDatabase | undefined;
  try {
    a.sql.exec("DROP TABLE host_jobs; PRAGMA user_version=30;"); a.close(); a = new RuntimeDatabase(path);
    b = new RuntimeDatabase(path);
    const first = new HostJobStore(a, () => {}), second = new HostJobStore(b, () => {});
    const created = first.put(actor, "create", 0, job); expect(created.revision).toBe(1);
    const done = first.put(actor, "finish", 1, { ...created.job, state: "completed", steps: [{ ...created.job.steps[0]!, state: "completed" }] });
    expect(() => second.put(actor, "stale", 1, created.job)).toThrow("host_job_revision_conflict");
    expect(second.put(actor, "create", 0, job)).toEqual(created);
    expect(second.get(actor, "job")).toEqual(done);
    expect(second.get({ ...actor, id: "other" }, "job")).toBeNull();
    expect(() => second.put({ ...actor, scopes: [] }, "create", 0, job)).toThrow("scope_denied");
    expect(() => second.put(actor, "relocate", 2, { ...done.job, repo: "/other" })).toThrow("host_job_binding_changed");
    expect(second.put(actor, "old-state", 2, { ...done.job, state: "pending" }).job.state).toBe("completed");
    expect(second.list(actor).jobs).toHaveLength(1);
    expect(second.list({ ...actor, id: "other" }).jobs).toHaveLength(0);
    a.close(); a = new RuntimeDatabase(path);
    expect(new HostJobStore(a, () => {}).get(actor, "job")?.revision).toBe(3);
    expect(a.sql.query("SELECT COUNT(*) AS n FROM receipts WHERE request_id='stale'").get()).toEqual({ n: 0 });
  } finally { a.close(); b?.close(); rmSync(root, { recursive: true, force: true }); }
});
test("host job storage failure rolls back both state and receipt", () => {
  const db = new RuntimeDatabase(":memory:"), store = new HostJobStore(db, () => {});
  try {
    const created = store.put(actor, "create", 0, job);
    db.sql.exec("CREATE TRIGGER fail_host_update BEFORE UPDATE ON host_jobs BEGIN SELECT RAISE(ABORT,'fixture failure'); END;");
    expect(() => store.put(actor, "update", 1, { ...created.job, state: "running" })).toThrow();
    expect(store.get(actor, "job")).toEqual(created);
    expect(db.sql.query("SELECT COUNT(*) AS n FROM receipts WHERE request_id='update'").get()).toEqual({ n: 0 });
  } finally { db.close(); }
});
