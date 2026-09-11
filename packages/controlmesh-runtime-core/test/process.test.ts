import { expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { RuntimeDatabase, RuntimeKernel, type Principal } from "../src";
import fixture from "../../../tests/golden/fixtures/tasks/legacy-registry.json";
import { AgentMailbox, LegacyMigration } from "../src";

const actor: Principal = { id: "operator", origin: "internal", scopes: ["task:create", "task:read"] };
const worker = join(import.meta.dir, "process-worker.ts");

async function waitForFile(path: string) {
  const until = performance.now() + 5_000;
  while (!(await Bun.file(path).exists())) {
    if (performance.now() > until) throw new Error("worker did not reach barrier");
    await Bun.sleep(10);
  }
}

test("two OS processes race for one lease, producing exactly one claim event", async () => {
  const dir = mkdtempSync(join(tmpdir(), "cm-process-"));
  const path = join(dir, "runtime.sqlite");
  const db = new RuntimeDatabase(path);
  const kernel = new RuntimeKernel(db);
  kernel.submit(actor, "create", { task_id: "race", chat_id: "synthetic", status: "waiting" });
  const children = ["a", "b"].map(id => Bun.spawn([process.execPath, worker, "race", path, join(dir, id)], { stdin: "pipe", stdout: "pipe", stderr: "pipe" }));
  try {
    await Promise.all([waitForFile(join(dir, "a")), waitForFile(join(dir, "b"))]);
    for (const child of children) { child.stdin.write("go\n"); child.stdin.end(); }
    const outputs = await Promise.all(children.map(async child => {
      const [stdout, stderr, code] = await Promise.all([new Response(child.stdout).text(), new Response(child.stderr).text(), child.exited]);
      expect({ stderr, code }).toEqual({ stderr: "", code: 0 });
      return JSON.parse(stdout);
    }));
    expect(outputs.filter(value => value.won)).toHaveLength(1);
    expect(outputs.filter(value => !value.won)[0].error).toBe("revision_conflict");
    expect(db.sql.query("SELECT COUNT(*) AS n FROM events WHERE kind='episode.claimed'").get()).toEqual({ n: 1 });
  } finally {
    for (const child of children) { if (child.exitCode === null) child.kill("SIGKILL"); }
    await Promise.all(children.map(child => child.exited));
    db.close();
    rmSync(dir, { recursive: true, force: true });
  }
}, 10_000);

test("SIGKILL during a write leaves no partial task after database reopen", async () => {
  const dir = mkdtempSync(join(tmpdir(), "cm-crash-"));
  const path = join(dir, "runtime.sqlite");
  const db = new RuntimeDatabase(path);
  db.close();
  const child = Bun.spawn([process.execPath, worker, "uncommitted", path, join(dir, "barrier")], { stdin: "pipe", stdout: "pipe", stderr: "pipe" });
  try {
    await waitForFile(join(dir, "barrier"));
    child.kill("SIGKILL");
    await child.exited;
    const reopened = new RuntimeDatabase(path);
    try {
      expect(reopened.sql.query("SELECT COUNT(*) AS n FROM tasks").get()).toEqual({ n: 0 });
      expect(reopened.sql.query("PRAGMA integrity_check").get()).toEqual({ integrity_check: "ok" });
    } finally { reopened.close(); }
  } finally {
    if (child.exitCode === null) child.kill("SIGKILL");
    await child.exited;
    rmSync(dir, { recursive: true, force: true });
  }
}, 10_000);

test("actual Python TaskEntry serializer fixture round-trips without dropped fields", () => {
  const db = new RuntimeDatabase(":memory:");
  try {
    const migration = new LegacyMigration(db);
    const preview = migration.preview("python", fixture);
    migration.importSnapshot("python", fixture, preview.digest, "operator");
    expect(migration.exportSnapshot("python")).toEqual(fixture);
    expect(Object.keys((migration.exportSnapshot("python") as typeof fixture).tasks[0])).toEqual(Object.keys(fixture.tasks[0]).sort());
  } finally { db.close(); }
});

test("SIGKILL after observing an effect preserves its dispatch manifest and original result for explicit reconciliation", async () => {
  const dir = mkdtempSync(join(tmpdir(), "cm-evidence-crash-")), path = join(dir, "runtime.sqlite"), barrier = join(dir, "observed.json");
  const child = Bun.spawn([process.execPath, worker, "observed", path, barrier], { stdin: "pipe", stdout: "pipe", stderr: "pipe" });
  try {
    await waitForFile(barrier);
    const lease = await Bun.file(barrier).json();
    child.kill("SIGKILL"); await child.exited;
    const db = new RuntimeDatabase(path);
    try {
      const kernel = new RuntimeKernel(db), owner: Principal = { ...actor, device_id: lease.device_id, scopes: [...actor.scopes, "task:execute", "task:reconcile"] };
      kernel.markUnknown(owner, "observed-death", lease, "worker_process_exited");
      const revision = kernel.inspect(owner, "observed").revision;
      const evidence = kernel.inspectReconciliation(owner, "observed", revision, "effect");
      expect(evidence.manifest).toEqual({ before: "durable" });
      expect(evidence.observation).toEqual({ after: "durable" });
      expect(db.sql.query("PRAGMA integrity_check").get()).toEqual({ integrity_check: "ok" });
      expect(kernel.inspect(owner, "observed").task.status).toBe("stale");
    } finally { db.close(); }
  } finally {
    if (child.exitCode === null) child.kill("SIGKILL");
    await child.exited; rmSync(dir, { recursive: true, force: true });
  }
}, 10_000);

test("received mailbox items survive closing and reopening the on-disk runtime", () => {
  const dir = mkdtempSync(join(tmpdir(), "cm-mailbox-restart-"));
  const path = join(dir, "runtime.sqlite");
  let db = new RuntimeDatabase(path);
  const owner: Principal = { ...actor, device_id: "test", scopes: [...actor.scopes, "task:execute", "message:send", "message:read", "message:ack"] };
  try {
    const kernel = new RuntimeKernel(db);
    kernel.submit(owner, "create", { task_id: "task", chat_id: "test", status: "waiting" });
    const lease = kernel.claim(owner, "claim", "task", 1, 30_000);
    const mailbox = new AgentMailbox(kernel);
    const sent = mailbox.send(owner, "send", { recipient_task: "task", sender_lease: null, kind: "tell", payload: { context: "synthetic" }, causation_id: null, ttl_ms: 30_000 });
    mailbox.acknowledge(owner, "receipt", lease, sent.message_id, "received", null);
    db.close();
    db = new RuntimeDatabase(path);
    const restarted = new AgentMailbox(new RuntimeKernel(db));
    expect(restarted.pending(owner, lease)[0].status).toBe("received");
    restarted.acknowledge(owner, "consume", lease, sent.message_id, "consumed", "synthetic-application-evidence");
    expect(restarted.pending(owner, lease)).toEqual([]);
  } finally { db.close(); rmSync(dir, { recursive: true, force: true }); }
});

test("schema v1 upgrades transactionally to v5 without replacing tasks or their metadata", () => {
  const dir = mkdtempSync(join(tmpdir(), "cm-schema-upgrade-"));
  const path = join(dir, "runtime.sqlite");
  let db = new RuntimeDatabase(path);
  try {
    const kernel = new RuntimeKernel(db);
    const original = kernel.submit(actor, "create", { task_id: "upgrade", chat_id: "synthetic", status: "waiting", future: { preserved: true } });
    // Restore the exact v1 table set before replaying the additive migrations.
    db.sql.exec("DROP TABLE provider_checks; DROP TABLE device_assignments; DROP TABLE device_revocations; DROP TABLE execution_manifests; DROP TABLE effect_observations; DROP TABLE device_execution_records; PRAGMA user_version=1");
    db.close();
    db = new RuntimeDatabase(path);
    expect(db.sql.query("PRAGMA user_version").get()).toEqual({ user_version: 6 });
    expect(new RuntimeKernel(db).inspect(actor, "upgrade")).toEqual(original);
    expect(db.sql.query("SELECT COUNT(*) AS n FROM provider_checks").get()).toEqual({ n: 0 });
  } finally { db.close(); rmSync(dir, { recursive: true, force: true }); }
});
