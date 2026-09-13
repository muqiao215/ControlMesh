import { expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { RuntimeDatabase } from "../src/database";
import { CronStore } from "../src/cron-store";
import { openLocalRuntime } from "../src/local-runtime-config";
import { startLocalRuntimeService } from "../src/local-runtime-service";

test("configured service plans durable cron cursors without bootstrap or model calls", async () => {
  const root = mkdtempSync(join(tmpdir(), "cm-cron-service-")), state = join(root, "state"), workspace = join(root, "workspace");
  mkdirSync(state, { mode: 0o700 }); mkdirSync(workspace);
  const path = join(root, "config.json"), config = {
    schema_version: "controlmesh.local_runtime.v1", mode: "candidate", state_root: state,
    principal_id: "owner", device_id: "local",
    source: { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: "terminal" },
    host: { shell: realpathSync("/bin/bash") }, workspace: { directory: workspace, read_files: [], required_reads: [] },
    cron_scheduler: { generation: 1, user_timezone: "UTC" },
  };
  writeFileSync(path, JSON.stringify(config), { mode: 0o600 });
  let service: Awaited<ReturnType<typeof startLocalRuntimeService>> | undefined;
  let db: RuntimeDatabase | undefined;
  try {
    expect(() => openLocalRuntime(path)).toThrow("coordinator_not_registered");
    db = new RuntimeDatabase(join(state, "runtime.sqlite"));
    const store = new CronStore(db); store.registerCoordinator("owner");
    store.putJob({ id: "future", title: "Future", schedule: "0 0 1 1 *", task_folder: "future", agent_instruction: "Inspect",
      provider: "opencode", execution_mode: "taskhub", output_policy: "summarized_only" });
    service = await startLocalRuntimeService(path, join(root, "control.sock"));
    const cursor = db.sql.query("SELECT value FROM meta WHERE key LIKE 'cron_cursor:%'").get() as { value: string };
    expect(JSON.parse(cursor.value).next_at).toBeGreaterThan(Date.now());
    expect(db.sql.query("SELECT COUNT(*) AS n FROM tasks").get()).toEqual({ n: 0 });
    expect(db.sql.query("SELECT COUNT(*) AS n FROM provider_checks").get()).toEqual({ n: 0 });
    await service.close(); service = undefined;
    service = await startLocalRuntimeService(path, join(root, "control.sock"));
    expect(db.sql.query("SELECT value FROM meta WHERE key LIKE 'cron_cursor:%'").get()).toEqual(cursor);
    await service.close(); service = undefined;
    const worker = openLocalRuntime(path, { host_worker: true });
    try { expect(worker.cron).toBeUndefined(); } finally { await worker.close(); }
    store.incrementCoordinatorEpoch("owner", 1);
    expect(() => openLocalRuntime(path)).toThrow("stale_coordinator_fence");
  } finally { await service?.close(); db?.close(); rmSync(root, { recursive: true, force: true }); }
});
