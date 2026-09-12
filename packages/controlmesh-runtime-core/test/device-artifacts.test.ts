import { afterEach, expect, test } from "bun:test";
import { createHash, randomBytes } from "node:crypto";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { DeviceClient, DeviceCoordinator, RuntimeDatabase, RuntimeKernel, type Principal } from "../src";
import { digest } from "../src/value";
const cleanups: (() => void)[] = [];
afterEach(() => { for (const close of cleanups.splice(0).reverse()) close(); });
const owner: Principal = { id: "owner", device_id: "coordinator", origin: "human_request",
  scopes: ["task:create", "task:read", "task:execute", "task:cancel", "device:assign", "device:revoke"] };
const sha = (value: string) => createHash("sha256").update(value).digest("hex");
async function fixture(transfer = true) {
  let elapsed = 0;
  const db = new RuntimeDatabase(":memory:", () => Date.now() + elapsed); cleanups.push(() => db.close());
  const kernel = new RuntimeKernel(db), tokens = [randomBytes(32).toString("base64url"), randomBytes(32).toString("base64url")];
  const devices = tokens.map((token, i) => ({ device_id: `device-${i}`, principal_id: owner.id, token_sha256: sha(token), capabilities: ["native"], workspace_ids: ["project"] }));
  const coordinator = new DeviceCoordinator(kernel, devices), server = coordinator.listen(); cleanups.push(() => server.stop(true));
  const clients = devices.map((device, i) => new DeviceClient({ endpoint: server.url.origin, token: tokens[i]!, device_id: device.device_id }));
  kernel.submit(owner, "create", { task_id: "task", status: "waiting", provider: "claude", model: "fixture", chat_id: "test",
    completion_requirements: { schema_version: "controlmesh.task_completion.v1", files: ["one", "two", "three", "four", "five"].map(path => ({ path, mode: "read" })) } });
  coordinator.assign(owner, "assign", "task", 1, { workspace_id: "project", capability: "native", device_ids: ["device-0"], input: {}, artifact_transfer: transfer });
  const job = await clients[0]!.inspect("task"), authority = await clients[0]!.claim("task", job.revision, job.assignment_digest, 10000);
  cleanups.push(() => authority.stop());
  const worker: Principal = { ...owner, device_id: "device-0", origin: "agent_message" };
  kernel.start(worker, "start", authority.lease);
  // Synthetic evidence reference: these tests qualify the inbox/HTTP authority boundary only.
  const manifest = { schema_version: "controlmesh.device_evidence.v1", task_id: "task", device_id: "device-0", episode_id: authority.lease.episode_id,
    effect_id: "effect", fence: authority.lease.fence, assignment_digest: job.assignment_digest, manifest_digest: digest("fixture") };
  kernel.dispatchEffect(worker, "dispatch", authority.lease, "effect", {}, manifest);
  const base = { lease: authority.lease, effect_id: "effect", path: "one", sha256: sha("abcdef"), size: 6, offset: 0, content_base64: Buffer.from("abc").toString("base64") };
  return { db, kernel, coordinator, clients, base, advance: () => { elapsed += 20000; } };
}
test("artifact chunk receipts are idempotent, ordered and hash checked; invalid input cannot alter stored bytes", async () => {
  const f = await fixture(), client = f.clients[0]!;
  for (const patch of [{ path: "../secret" }, { path: "unknown" }, { offset: 2 }, { content_base64: "YWJj=" }, { size: 4194305 }]) {
    await expect(client.command("artifact_put", { ...f.base, ...patch })).rejects.toThrow();
  }
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM device_artifact_files").get()).toEqual({ n: 0 });
  const first = await client.command("artifact_put", f.base, "first");
  expect(await client.command("artifact_put", f.base, "first")).toEqual(first);
  expect(await client.command("artifact_put", f.base, "duplicate-bytes")).toEqual(first);
  await expect(client.command("artifact_put", { ...f.base, path: "two" }, "first")).rejects.toThrow("idempotency_conflict");
  await expect(client.command("artifact_put", { ...f.base, content_base64: "eHl6" })).rejects.toThrow("device_artifact_chunk_conflict");
  await expect(client.command("artifact_put", { ...f.base, sha256: sha("other") })).rejects.toThrow("device_artifact_transfer_changed");
  await expect(client.command("artifact_put", { ...f.base, offset: 3, content_base64: "eHl6" })).rejects.toThrow("device_artifact_hash_mismatch");
  expect(f.db.sql.query("SELECT received FROM device_artifact_files").get()).toEqual({ received: 3 });
  await client.command("artifact_put", { ...f.base, offset: 3, content_base64: "ZGVm" });
  const row = f.db.sql.query("SELECT content,received FROM device_artifact_files").get() as { content: Uint8Array; received: number };
  expect(Buffer.from(row.content).toString()).toBe("abcdef"); expect(row.received).toBe(6);
});
test.each(["foreign", "revoked", "expired", "cancelled", "disabled"])("artifact writes refuse %s authority before storing bytes", async scenario => {
  const f = await fixture(scenario !== "disabled");
  if (scenario === "revoked") f.coordinator.revoke(owner, "device-0");
  if (scenario === "expired") f.advance();
  if (scenario === "cancelled") f.kernel.cancel(owner, "cancel", "task", f.kernel.inspect(owner, "task").revision);
  await expect(f.clients[scenario === "foreign" ? 1 : 0]!.command("artifact_put", f.base)).rejects.toThrow();
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM device_artifact_files").get()).toEqual({ n: 0 });
});
test("declared partial-file reservations enforce the aggregate budget before additional allocation", async () => {
  const f = await fixture(), client = f.clients[0]!;
  for (const path of ["one", "two", "three", "four"]) await client.command("artifact_put", { ...f.base, path, size: 4194304 });
  await expect(client.command("artifact_put", { ...f.base, path: "five" })).rejects.toThrow("device_artifact_budget_exceeded");
  expect(f.db.sql.query("SELECT SUM(size) AS reserved,SUM(received) AS received FROM device_artifact_files").get()).toEqual({ reserved: 16777216, received: 12 });
});
test("schema 26 upgrade preserves existing tasks and receipts and creates an empty durable artifact inbox", () => {
  const root = mkdtempSync(join(tmpdir(), "cm-artifact-upgrade-")); cleanups.push(() => rmSync(root, { recursive: true, force: true }));
  const path = join(root, "runtime.sqlite"); let db = new RuntimeDatabase(path); cleanups.push(() => db.close());
  new RuntimeKernel(db).submit(owner, "create", { task_id: "old", status: "waiting", chat_id: "fixture" });
  const tasks = db.sql.query("SELECT * FROM tasks").all(), receipts = db.sql.query("SELECT * FROM receipts").all();
  db.sql.exec("DROP TABLE workspace_seed_files; DROP TABLE workspace_seed_transfers; DROP TABLE topology_artifact_publications; DROP TABLE device_artifact_files; PRAGMA user_version=26"); db.close(); db = new RuntimeDatabase(path);
  expect(db.sql.query("PRAGMA user_version").get()).toEqual({ user_version: 29 });
  expect(db.sql.query("SELECT * FROM tasks").all()).toEqual(tasks); expect(db.sql.query("SELECT * FROM receipts").all()).toEqual(receipts);
  expect(db.sql.query("SELECT COUNT(*) AS n FROM device_artifact_files").get()).toEqual({ n: 0 });
});
