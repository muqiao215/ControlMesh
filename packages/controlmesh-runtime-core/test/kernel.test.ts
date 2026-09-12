import { afterEach, expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { LegacyMigration, RuntimeDatabase, RuntimeKernel, decodeSnapshot, type Principal } from "../src";
import type { LegacyTask } from "../src/value";

const actor: Principal = { id: "operator", origin: "human_request", device_id: "device-a", scopes: ["task:create", "task:read", "task:execute", "task:cancel", "task:reconcile", "task:admin"] };
const dirs: string[] = [];
const databases: RuntimeDatabase[] = [];
function fixture() {
  let now = 1_000;
  const dir = mkdtempSync(join(tmpdir(), "cm-runtime-"));
  dirs.push(dir);
  const path = join(dir, "runtime.sqlite");
  const db = new RuntimeDatabase(path, () => now);
  databases.push(db);
  return { db, path, kernel: new RuntimeKernel(db), advance(ms: number) { now += ms; } };
}
function task(task_id = "task-1"): LegacyTask {
  return { task_id, chat_id: "test", status: "waiting", provider: "opencode", model: "configured/model", execution_context: { origin: "schedule" }, tool_grant: { unknown_future: true }, extension: { keep: [1, false, null] } };
}
afterEach(() => {
  for (const db of databases.splice(0)) db.close();
  for (const dir of dirs.splice(0)) rmSync(dir, { recursive: true, force: true });
});

test("unstarted admission release and expiry clear the lease while a started episode remains uncertain", () => {
  const { kernel, db, advance } = fixture();
  kernel.submit(actor, "create", task());
  const first = kernel.claim(actor, "claim", "task-1", 1, 100);
  const released = kernel.releaseUnstarted(actor, "release", first, "provider_preflight_not_ready");
  expect(released.task.status).toBe("waiting"); expect(released.active_episode).toBeNull();
  expect(kernel.releaseUnstarted(actor, "release", first, "provider_preflight_not_ready")).toEqual(released);
  expect(() => kernel.start(actor, "stale-start", first)).toThrow("stale_fence");
  const next = kernel.claim(actor, "claim2", "task-1", released.revision, 100);
  advance(150); expect(kernel.recoverExpired(actor)).toEqual(["task-1"]);
  const waiting = kernel.inspect(actor, "task-1"); expect(waiting.task.status).toBe("waiting"); expect(waiting.needs_reconciliation).toBe(false);
  expect(() => kernel.start(actor, "expired-start", next)).toThrow("stale_fence");
  const running = kernel.claim(actor, "claim3", "task-1", waiting.revision, 100);
  kernel.start(actor, "start", running);
  expect(() => kernel.releaseUnstarted(actor, "unsafe-release", running)).toThrow("started_episode_cannot_release");
  advance(150); kernel.recoverExpired(actor);
  expect(kernel.inspect(actor, "task-1").needs_reconciliation).toBe(true);
  expect(db.sql.query("SELECT COUNT(*) AS n FROM effects").get()).toEqual({ n: 0 });
});

test("idempotency binds principal, request content and provenance and survives restart", () => {
  const { kernel, db, path } = fixture();
  const first = kernel.submit(actor, "create", task());
  const secondDb = new RuntimeDatabase(path);
  databases.push(secondDb);
  const second = new RuntimeKernel(secondDb);
  expect(second.submit(actor, "create", task())).toEqual(first);
  expect(() => second.submit(actor, "create", { ...task(), model: "different" })).toThrow("idempotency_conflict");
  expect(() => second.submit({ ...actor, origin: "schedule" }, "create", task())).toThrow("idempotency_conflict");
  expect(db.sql.query("SELECT COUNT(*) AS count FROM events").get()).toEqual({ count: 1 });
  expect(first.task.tool_grant).toEqual(task().tool_grant);
});

test("only one connection can claim a revision; no old-fence write after safe reclaim", () => {
  const { kernel, path, advance } = fixture();
  kernel.submit(actor, "create", task());
  const first = kernel.claim(actor, "claim1", "task-1", 1, 100);
  const db2 = new RuntimeDatabase(path, () => 1_100);
  databases.push(db2);
  const second = new RuntimeKernel(db2);
  const next = second.claim({ ...actor, device_id: "device-b" }, "claim2", "task-1", 2, 100);
  expect(next.fence).toBeGreaterThan(first.fence);
  advance(100);
  expect(() => kernel.start(actor, "start-old", first)).toThrow("stale_fence");
  expect(() => kernel.claim(actor, "claim3", "task-1", 2, 100)).toThrow("revision_conflict");
});

test("resume preserves authority/native lineage but never revives cancelled or uncertain work", () => {
  const { kernel } = fixture();
  const owner: Principal = { ...actor, scopes: [...actor.scopes, "task:resume"] };
  kernel.submit(owner, "create", task());
  const lease = kernel.claim(owner, "claim", "task-1", 1, 30_000);
  kernel.start(owner, "start", lease);
  const done = kernel.finish(owner, "finish", lease, "done", { native_session: { session_id: "ses_Synthetic" } });
  const next = kernel.resume(owner, "resume", "task-1", done.revision, "next instruction");
  expect(next.task.status).toBe("waiting");
  expect(next.task.prompt).toBe("next instruction");
  expect(next.task.tool_grant).toEqual(task().tool_grant);
  expect(next.task.native_session).toEqual({ session_id: "ses_Synthetic" });
  const cancelled = kernel.cancel(owner, "cancel", "task-1", next.revision);
  expect(() => kernel.resume(owner, "revive", "task-1", cancelled.revision, "again")).toThrow("task_not_resumable");
  kernel.submit(owner, "create2", task("uncertain"));
  const unknown = kernel.claim(owner, "claim2", "uncertain", 1, 30_000);
  kernel.start(owner, "start2", unknown);
  kernel.dispatchEffect(owner, "dispatch", unknown, "unknown-effect", {});
  const stale = kernel.markUnknown(owner, "unknown", unknown, "native_completion_unproven");
  expect(stale.needs_reconciliation).toBe(true);
  expect(() => kernel.resume(owner, "repeat", "uncertain", stale.revision, "again")).toThrow("task_not_resumable");
});

test("cancel invalidates execution, preserves authority fields, and rejects late completion", () => {
  const { kernel } = fixture();
  kernel.submit(actor, "create", task());
  const lease = kernel.claim(actor, "claim", "task-1", 1, 100);
  const running = kernel.start(actor, "start", lease);
  const cancelled = kernel.cancel(actor, "cancel", "task-1", running.revision);
  expect(cancelled.task.status).toBe("cancelled");
  expect(cancelled.task.execution_context).toEqual(task().execution_context);
  expect(() => kernel.finish(actor, "late", lease, "done", {})).toThrow("task_not_executable");
  expect(() => kernel.claim(actor, "resurrect", "task-1", cancelled.revision, 100)).toThrow("task_not_admitted");
});

test("side-effect receipt loss is unknown, blocks redispatch, and cannot be declared done", () => {
  const { kernel, db, advance } = fixture();
  kernel.submit(actor, "create", task());
  const lease = kernel.claim(actor, "claim", "task-1", 1, 100);
  kernel.start(actor, "start", lease);
  expect(kernel.dispatchEffect(actor, "send", lease, "effect-1", { command: "synthetic" }).dispatch_permitted).toBe(true);
  expect(kernel.dispatchEffect(actor, "send", lease, "effect-1", { command: "synthetic" }).dispatch_permitted).toBe(false);
  expect(() => kernel.finish(actor, "finish", lease, "done", {})).toThrow("unresolved_effects");
  advance(101);
  expect(kernel.recoverExpired({ ...actor, origin: "recovery" })).toEqual(["task-1"]);
  expect(kernel.recoverExpired(actor)).toEqual([]);
  const state = kernel.inspect(actor, "task-1");
  expect(state.needs_reconciliation).toBe(true);
  expect(state.task.status).toBe("stale");
  expect(() => kernel.claim(actor, "retry", "task-1", state.revision, 100)).toThrow("task_not_admitted");
  expect(() => kernel.confirmEffect(actor, "late", lease, "effect-1", {})).toThrow("task_not_executable");
  expect(db.sql.query("SELECT state FROM effects").get()).toEqual({ state: "unknown" });
});

test("completed result and event commit once; conflicting final result is rejected", () => {
  const { kernel, db } = fixture();
  kernel.submit(actor, "create", task());
  const lease = kernel.claim(actor, "claim", "task-1", 1, 100);
  kernel.start(actor, "start", lease);
  kernel.dispatchEffect(actor, "dispatch", lease, "effect", {});
  kernel.confirmEffect(actor, "confirm", lease, "effect", { observed: "completed" });
  const done = kernel.finish(actor, "finish", lease, "done", { result: "verified" });
  expect(kernel.finish(actor, "finish", lease, "done", { result: "verified" })).toEqual(done);
  expect(() => kernel.finish(actor, "finish", lease, "done", { result: "different" })).toThrow("idempotency_conflict");
  expect(db.sql.query("SELECT COUNT(*) AS count FROM events WHERE kind='task.done'").get()).toEqual({ count: 1 });
});

test("backward coordinator time cannot revive an expired lease; workers cannot impersonate a device", () => {
  const { kernel, db, advance } = fixture();
  kernel.submit(actor, "create", task());
  const lease = kernel.claim(actor, "claim", "task-1", 1, 100);
  expect(() => kernel.start({ ...actor, device_id: "different" }, "start", lease)).toThrow("device_mismatch");
  advance(101);
  db.transaction(() => db.now());
  advance(-1_000);
  expect(() => kernel.start(actor, "start", lease)).toThrow("lease_expired");
});

test("denied and invalid operations leave no receipts or events", () => {
  const { kernel, db } = fixture();
  kernel.submit(actor, "create", task());
  expect(() => kernel.inspect({ ...actor, id: "other", scopes: ["task:read"] }, "task-1")).toThrow("task_access_denied");
  expect(() => kernel.claim({ ...actor, scopes: [] }, "claim", "task-1", 1, 100)).toThrow("scope_denied");
  expect(() => kernel.submit(actor, "bad", { ...task("bad"), extra: undefined })).toThrow("invalid_json_value");
  expect(db.sql.query("SELECT COUNT(*) AS count FROM receipts").get()).toEqual({ count: 1 });
});

test("migration preserves every field and cancelled task across export and repeated import", () => {
  const { db, kernel } = fixture();
  const migration = new LegacyMigration(db);
  const source = { schema_extension: { revision: "legacy" }, tasks: [task(), { ...task("cancelled"), status: "cancelled" }] };
  const plan = migration.preview("legacy", source);
  migration.importSnapshot("legacy", source, plan.digest, actor.id);
  expect(migration.exportSnapshot("legacy")).toEqual(source);
  expect(migration.originalSnapshot("legacy")).toEqual(source);
  expect(migration.importSnapshot("legacy", source, plan.digest, actor.id)).toEqual(plan);
  expect(kernel.inspect(actor, "task-1").needs_reconciliation).toBe(true);
  expect(kernel.inspect(actor, "cancelled").task.status).toBe("cancelled");
  expect(() => kernel.claim(actor, "claim", "task-1", 1, 100)).toThrow("task_not_admitted");
});

test("migration transaction rolls back every task when interrupted halfway", () => {
  const { db } = fixture();
  const migration = new LegacyMigration(db);
  const source = { tasks: [task("first"), task("second")] };
  const plan = migration.preview("legacy", source);
  db.sql.exec("CREATE TRIGGER inject_crash BEFORE INSERT ON tasks WHEN NEW.task_id='second' BEGIN SELECT RAISE(ABORT,'synthetic crash'); END;");
  expect(() => migration.importSnapshot("legacy", source, plan.digest, actor.id)).toThrow("synthetic crash");
  expect(db.sql.query("SELECT COUNT(*) AS count FROM tasks").get()).toEqual({ count: 0 });
  expect(db.sql.query("SELECT COUNT(*) AS count FROM migrations").get()).toEqual({ count: 0 });
  db.sql.exec("DROP TRIGGER inject_crash");
  migration.importSnapshot("legacy", source, plan.digest, actor.id);
  expect(migration.exportSnapshot("legacy")).toEqual(source);
});

test("corrupt, duplicate and changed legacy snapshots fail without discarding rows", () => {
  const { db } = fixture();
  const migration = new LegacyMigration(db);
  expect(() => decodeSnapshot(new TextEncoder().encode('{"tasks":['))).toThrow();
  expect(() => decodeSnapshot(new TextEncoder().encode('{"tasks":[],"tasks":[]}'))).toThrow("duplicate_json_key");
  expect(() => decodeSnapshot(new TextEncoder().encode('{"tasks":[],"future":{"counter":999999999999999999}}'))).toThrow("unsafe_json_integer");
  expect(() => migration.preview("source", { tasks: [task(), task()] })).toThrow("duplicate_legacy_task");
  expect(() => migration.preview("source", { tasks: [task(), { task_id: "bad" }] })).toThrow("invalid_chat_id");
  expect(() => migration.importSnapshot("source", { tasks: [task()] }, "wrong", actor.id)).toThrow("migration_source_changed");
  expect(db.sql.query("SELECT COUNT(*) AS count FROM tasks").get()).toEqual({ count: 0 });
});

test("clock observation survives a failed transaction and reopening the coordinator", () => {
  const { kernel, path, advance } = fixture();
  kernel.submit(actor, "create", task());
  const lease = kernel.claim(actor, "claim", "task-1", 1, 100);
  advance(101);
  expect(() => kernel.start(actor, "start", lease)).toThrow("lease_expired");
  const reopened = new RuntimeDatabase(path, () => 1);
  databases.push(reopened);
  expect(() => new RuntimeKernel(reopened).start(actor, "start", lease)).toThrow("lease_expired");
});

test("revoking administrative scope also revokes access to cached operation receipts", () => {
  const { kernel } = fixture();
  kernel.submit(actor, "create", task());
  const admin = { ...actor, id: "temporary-admin" };
  const lease = kernel.claim(admin, "claim", "task-1", 1, 100);
  kernel.start(admin, "start", lease);
  kernel.finish(admin, "finish", lease, "done", { private: "result" });
  expect(() => kernel.finish({ ...admin, scopes: ["task:execute"] }, "finish", lease, "done", { private: "result" })).toThrow("task_access_denied");
});

test("a failed event write cannot leave a completed task or an idempotency receipt", () => {
  const { kernel, db } = fixture();
  kernel.submit(actor, "create", task());
  const lease = kernel.claim(actor, "claim", "task-1", 1, 100);
  kernel.start(actor, "start", lease);
  db.sql.exec("CREATE TRIGGER event_failure BEFORE INSERT ON events WHEN NEW.kind='task.done' BEGIN SELECT RAISE(ABORT,'event storage failed'); END;");
  expect(() => kernel.finish(actor, "finish", lease, "done", { output: "synthetic" })).toThrow("event storage failed");
  expect(kernel.inspect(actor, "task-1").task.status).toBe("running");
  expect(db.sql.query("SELECT state,result FROM episodes").get()).toEqual({ state: "running", result: null });
  expect(db.sql.query("SELECT 1 FROM receipts WHERE request_id='finish'").get()).toBeNull();
  db.sql.exec("DROP TRIGGER event_failure");
  expect(kernel.finish(actor, "finish", lease, "done", { output: "synthetic" }).task.status).toBe("done");
});

test("completed output binds owner, current revision, explicit episode and confirmed effect", () => {
  const { kernel, db } = fixture();
  kernel.submit(actor, "create", task());
  const lease = kernel.claim(actor, "claim", "task-1", 1, 30_000);
  kernel.start(actor, "start", lease);
  const read = (revision: number, principal = actor) => kernel.inspectCompletedEffect(principal, "task-1", revision, lease.episode_id, "output");
  expect(() => read(kernel.inspect(actor, "task-1").revision)).toThrow("task_result_not_accepted");
  kernel.dispatchEffect(actor, "dispatch", lease, "output", { operation: "native" });
  const result = { text: "accepted output", output_digest: "test-digest" };
  kernel.confirmEffect(actor, "confirm", lease, "output", result);
  const done = kernel.finish(actor, "finish", lease, "done", result);
  expect(read(done.revision).result).toEqual(result);
  const other = { ...actor, id: "stranger", scopes: ["task:read"] };
  expect(() => read(done.revision, other)).toThrow("task_access_denied");
  expect(() => read(done.revision - 1)).toThrow("revision_conflict");
  expect(() => kernel.inspectCompletedEffect(actor, "task-1", done.revision, lease.episode_id, "wrong")).toThrow("completed_effect_unavailable");
  db.sql.query("UPDATE effects SET result=? WHERE effect_id='output'").run(JSON.stringify({ text: "unrelated" }));
  expect(() => read(done.revision)).toThrow("completed_result_mismatch");
  db.sql.query("UPDATE effects SET result=? WHERE effect_id='output'").run(JSON.stringify(result));
  const owner = { ...actor, scopes: [...actor.scopes, "task:resume"] };
  const resumed = kernel.resume(owner, "resume", "task-1", done.revision, "continue");
  expect(() => read(resumed.revision)).toThrow("task_result_not_accepted");
  const next = kernel.claim(owner, "claim-next", "task-1", resumed.revision, 30_000);
  kernel.start(owner, "start-next", next);
  const nextDone = kernel.finish(owner, "finish-next", next, "done", result);
  expect(() => read(nextDone.revision)).toThrow("completed_episode_superseded");
});
