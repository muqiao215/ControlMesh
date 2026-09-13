import { expect, test } from "bun:test";
import { mkdtempSync, mkdirSync, realpathSync, writeFileSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { openLocalRuntime } from "../src/local-runtime-config";

for (const duration of [1000, 4000]) test(`host duration ${duration} bounds renewal of a real two-second command`, async () => {
  const root = mkdtempSync(join(tmpdir(), "cm-host-renewal-")), state = join(root, "state"), workspace = join(root, "workspace"), path = join(root, "config.json");
  mkdirSync(state, { mode: 0o700 }); mkdirSync(workspace);
  writeFileSync(path, JSON.stringify({ schema_version: "controlmesh.local_runtime.v1", mode: "candidate", state_root: state,
    principal_id: "owner", device_id: "local", source: { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: "terminal" },
    host: { shell: realpathSync("/bin/bash"), timeout_ms: duration }, limits: { lease_ms: 1000 }, workspace: { directory: workspace, read_files: [], required_reads: [] } }), { mode: 0o600 });
  const owned = openLocalRuntime(path);
  try {
    owned.runtime.submit("create", { task_id: "task", chat_id: "test", status: "waiting", workunit_kind: "long_shell", command: "printf started; sleep 2; touch finished" }, { chat_id: "test" });
    owned.runtime.enqueue("enqueue", "task", 1); await owned.runtime.drain();
    const task = owned.runtime.inspectTask("task"), db = owned.runtime.kernel.db;
    const renewals = db.sql.query("SELECT COUNT(*) AS n FROM events WHERE kind='episode.renewed'").get() as { n: number };
    if (duration === 4000) {
      expect(task.task.status).toBe("done"); expect(existsSync(join(workspace, "finished"))).toBe(true);
      expect(renewals.n).toBeGreaterThan(0);
    } else {
      expect(task.needs_reconciliation).toBe(true); expect(existsSync(join(workspace, "finished"))).toBe(false);
      expect(renewals.n).toBe(0);
    }
    const row = db.sql.query("SELECT p.lease_until,d.deadline_at FROM episodes p JOIN episode_deadlines d USING(episode_id)").get() as { lease_until: number; deadline_at: number };
    expect(row.lease_until).toBeLessThanOrEqual(row.deadline_at);
    expect(db.sql.query("SELECT COUNT(*) AS n FROM episodes").get()).toEqual({ n: 1 });
  } finally { await owned.close(); rmSync(root, { recursive: true, force: true }); }
}, 10000);
