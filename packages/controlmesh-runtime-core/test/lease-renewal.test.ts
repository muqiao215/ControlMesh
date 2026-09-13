import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "bun:test";
import { RuntimeDatabase } from "../src/database";
import { RuntimeKernel, type Principal } from "../src/kernel";
const actor: Principal = { id: "owner", device_id: "local", origin: "human_request", scopes: ["task:create", "task:read", "task:execute", "task:cancel"] };

test("renewals preserve fencing and an immutable absolute deadline", () => {
  let now = 10000;
  const db = new RuntimeDatabase(":memory:", () => now), kernel = new RuntimeKernel(db);
  try {
    kernel.submit(actor, "create", { task_id: "task", chat_id: "test", status: "waiting" });
    const first = kernel.claim(actor, "claim", "task", 1, 1000, 2500);
    expect(kernel.executionDeadline(actor, first)).toBe(12500);
    now += 600;
    db.sql.exec("CREATE TRIGGER fail_renew BEFORE INSERT ON events WHEN NEW.kind='episode.renewed' BEGIN SELECT RAISE(ABORT,'renewal persistence failed'); END;");
    expect(() => kernel.renewLease(actor, "renew", first, 1000)).toThrow("renewal persistence failed");
    expect(db.sql.query("SELECT lease_until FROM episodes WHERE episode_id=?").get(first.episode_id)).toEqual({ lease_until: first.lease_until });
    db.sql.exec("DROP TRIGGER fail_renew;");
    const next = kernel.renewLease(actor, "renew", first, 1000);
    expect(next).toEqual({ ...first, lease_until: 11600 });
    expect(kernel.renewLease(actor, "renew", first, 1000)).toEqual(next);
    expect(() => kernel.renewLease(actor, "old-proof", first, 1000)).toThrow("lease_renewal_stale");
    expect(() => kernel.renewLease({ ...actor, device_id: "other" }, "other", next, 1000)).toThrow("device_mismatch");
    expect(() => kernel.renewLease({ ...actor, id: "other", scopes: [...actor.scopes, "task:admin"] }, "other-owner", next, 1000)).toThrow("lease_renewal_owner_mismatch");
    now = 11200;
    const capped = kernel.renewLease(actor, "cap", next, 300000);
    expect(capped.lease_until).toBe(12500);
    expect(capped.fence).toBe(first.fence);
    now = 12400;
    expect(() => kernel.renewLease(actor, "extend-hard-limit", capped, 1000)).toThrow("execution_deadline_reached");
    now = 12500;
    expect(() => kernel.renewLease(actor, "expired", capped, 1000)).toThrow("lease_expired");
  } finally { db.close(); }
});

test("cancellation, missing budgets and default legacy leases cannot gain more time", () => {
  let now = 10000;
  const db = new RuntimeDatabase(":memory:", () => now), kernel = new RuntimeKernel(db);
  try {
    kernel.submit(actor, "create", { task_id: "task", chat_id: "test", status: "waiting" });
    const proof = kernel.claim(actor, "claim", "task", 1, 1000);
    now += 500;
    expect(() => kernel.renewLease(actor, "widen", proof, 1000)).toThrow("execution_deadline_reached");
    kernel.cancel(actor, "cancel", "task", kernel.inspect(actor, "task").revision);
    expect(() => kernel.renewLease(actor, "cancelled", proof, 1000)).toThrow("task_not_executable");
    kernel.submit(actor, "new", { task_id: "other", chat_id: "test", status: "waiting" });
    const missing = kernel.claim(actor, "new-claim", "other", 1, 1000, 5000);
    db.sql.query("DELETE FROM episode_deadlines WHERE episode_id=?").run(missing.episode_id);
    expect(() => kernel.renewLease(actor, "missing", missing, 1000)).toThrow("execution_deadline_unproven");
  } finally { db.close(); }
});

test("schema 32 migration keeps the old episode expiry as its hard deadline", () => {
  const root = mkdtempSync(join(tmpdir(), "cm-lease-upgrade-")), path = join(root, "runtime.sqlite");
  let db = new RuntimeDatabase(path, () => 10000);
  try {
    const kernel = new RuntimeKernel(db); kernel.submit(actor, "create", { task_id: "task", chat_id: "test", status: "waiting" });
    const proof = kernel.claim(actor, "claim", "task", 1, 1000);
    db.sql.exec("DROP TABLE episode_deadlines; DROP TABLE IF EXISTS telegram_conversations; DROP TABLE IF EXISTS telegram_event_aliases; DROP TABLE IF EXISTS telegram_inbox; DROP TABLE IF EXISTS delivery_retry_after; DROP TABLE IF EXISTS telegram_callbacks; DROP TABLE IF EXISTS telegram_poll_updates; DROP TABLE IF EXISTS telegram_polling; PRAGMA user_version=32;"); db.close();
    db = new RuntimeDatabase(path, () => 10500);
    const upgraded = new RuntimeKernel(db);
    expect(upgraded.executionDeadline(actor, proof)).toBe(11000);
    expect(() => upgraded.renewLease(actor, "upgrade-renew", proof, 1000)).toThrow("execution_deadline_reached");
  } finally { db.close(); rmSync(root, { recursive: true, force: true }); }
});

test("device renewal entry point cannot bypass a host execution deadline", () => {
  let now = 10000;
  const db = new RuntimeDatabase(":memory:", () => now), kernel = new RuntimeKernel(db);
  try {
    kernel.submit(actor, "create", { task_id: "host", chat_id: "test", status: "waiting", provider: "host" });
    const first = kernel.claim(actor, "claim", "host", 1, 1000, 1500);
    now += 600;
    const next = kernel.renew(actor, "renew", first, 300000);
    expect(next.lease_until).toBe(11500);
    now += 100;
    expect(() => kernel.renew(actor, "bypass", next, 300000)).toThrow("execution_deadline_reached");
    kernel.cancel(actor, "cancel", "host", kernel.inspect(actor, "host").revision);
    expect(() => kernel.renew(actor, "replay-after-cancel", next, 1000)).toThrow("task_not_executable");
  } finally { db.close(); }
});
