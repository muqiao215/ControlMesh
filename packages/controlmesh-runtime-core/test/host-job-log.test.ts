import { LocalRuntimeControl } from "../src/local-runtime-control";
import { parseRuntimeCli } from "../src/runtime-cli";
import { expect, test } from "bun:test";
import { mkdtempSync, mkdirSync, realpathSync, writeFileSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { openLocalRuntime } from "../src/local-runtime-config";
import { RuntimeDatabase } from "../src/database";
import { RuntimeKernel, type Principal } from "../src/kernel";
import { readHostLog } from "../src/host-job-log";
import { ProcessSupervisor } from "../src/process-supervisor";

test("host output is durable and readable before completion, with execution-bound pages", async () => {
  const root = mkdtempSync(join(tmpdir(), "cm-live-host-log-")), state = join(root, "state"), workspace = join(root, "workspace"), path = join(root, "config.json");
  mkdirSync(state, { mode: 0o700 }); mkdirSync(workspace);
  writeFileSync(path, JSON.stringify({ schema_version: "controlmesh.local_runtime.v1", mode: "candidate", state_root: state,
    principal_id: "owner", device_id: "local", source: { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: "terminal" },
    host: { shell: realpathSync("/bin/bash") }, workspace: { directory: workspace, read_files: [], required_reads: [] } }), { mode: 0o600 });
  let owned = openLocalRuntime(path);
  try {
    owned.runtime.submit("create", { task_id: "log", chat_id: "test", status: "waiting", workunit_kind: "long_shell",
      command: "printf '你🙂好'; printf '警告' >&2; while [ ! -f release ]; do sleep 0.05; done; printf '结束'" }, { chat_id: "test" });
    owned.runtime.enqueue("enqueue", "log", 1); const draining = owned.runtime.drain();
    try {
      const end = Date.now() + 5000;
      while (Date.now() < end && owned.runtime.hostLog("log").chunks.length < 2) await Bun.sleep(10);
      expect(owned.runtime.inspectTask("log").task.status).toBe("running");
      const first = owned.runtime.hostLog("log", undefined, 0, 1);
      expect(first.chunks.length).toBe(1); expect(first.has_more).toBe(true);
      const control = new LocalRuntimeControl(owned.runtime);
      expect(await control.handle({ id: "logs", op: "host_log", task_id: "log", limit: 1 })).toMatchObject({ ok: true, result: { effect_id: first.effect_id, next_after: first.next_after } });
      expect(await control.handle({ id: "override", op: "host_log", task_id: "log", principal: "other" })).toMatchObject({ ok: false, error: "unexpected_local_request_field" });
      expect(parseRuntimeCli(["host-log", "log", "--socket", "/tmp/log.sock", "--effect", first.effect_id!, "--after", String(first.next_after)])?.request)
        .toMatchObject({ op: "host_log", effect_id: first.effect_id, after: first.next_after });
      const otherDB = new RuntimeDatabase(join(state, "runtime.sqlite"));
      try {
        const actor: Principal = { id: "owner", origin: "human_request", scopes: ["task:read", "task:admin"] }, kernel = new RuntimeKernel(otherDB);
        expect(otherDB.sql.query("PRAGMA user_version").get()).toEqual({ user_version: 33 });
        const logs = readHostLog(kernel, actor, "log");
        expect(logs.chunks.map(item => item.text).join("")).toContain("你🙂好");
        expect(() => readHostLog(kernel, { ...actor, id: "other" }, "log")).toThrow("host_output_owner_mismatch");
        expect(() => readHostLog(kernel, actor, "log", undefined, first.next_after)).toThrow("host_log_cursor_binding_required");
        expect(readHostLog(kernel, actor, "log", first.effect_id!, first.next_after).chunks.length).toBeGreaterThan(0);
      } finally { otherDB.close(); }
    } finally { writeFileSync(join(workspace, "release"), "go"); await draining; }
    await owned.close(); owned = openLocalRuntime(path);
    const logs = owned.runtime.hostLog("log");
    expect(logs.chunks.filter(item => item.stream === "stdout").map(item => item.text).join("")).toBe("你🙂好结束");
    expect(logs.chunks.filter(item => item.stream === "stderr").map(item => item.text).join("")).toBe("警告");
    expect(owned.runtime.inspectTask("log").task.status).toBe("done");
    owned.runtime.kernel.db.sql.exec("UPDATE process_output_chunks SET text='corrupted' WHERE seq=(SELECT MIN(seq) FROM process_output_chunks)");
    expect(() => owned.runtime.hostLog("log")).toThrow("host_log_evidence_changed");
  } finally { await owned.close(); rmSync(root, { recursive: true, force: true }); }
});

for (const asynchronous of [false, true]) test(`output sink failure stops execution rather than reporting success, async=${asynchronous}`, async () => {
  const root = mkdtempSync(join(tmpdir(), "cm-log-sink-"));
  try {
    const result = await new ProcessSupervisor().run({ command: [realpathSync("/bin/bash"), "-c", "printf output; sleep 1; touch finished"], cwd: root,
      env: { PATH: "/usr/bin:/bin" }, timeout_ms: 5000 }, { assertCurrent() {},
      onOutput: asynchronous ? async () => {} : () => { throw new Error("sink unavailable"); } });
    expect(result.reason).toBe("output_sink_failed");
    expect(existsSync(join(root, "finished"))).toBe(false);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("schema 31 upgrades without changing persisted task state", () => {
  const root = mkdtempSync(join(tmpdir(), "cm-log-migration-")), file = join(root, "runtime.sqlite");
  let db = new RuntimeDatabase(file);
  const actor: Principal = { id: "owner", origin: "human_request", scopes: ["task:read", "task:create"] };
  try {
    const kernel = new RuntimeKernel(db), original = kernel.submit(actor, "create", { task_id: "saved", chat_id: "test", status: "waiting", provider: "host" });
    db.sql.exec("DROP TABLE episode_deadlines; DROP TABLE process_output_chunks; PRAGMA user_version=31;"); db.close();
    db = new RuntimeDatabase(file);
    expect(db.sql.query("PRAGMA user_version").get()).toEqual({ user_version: 33 });
    expect(new RuntimeKernel(db).inspect(actor, "saved")).toEqual(original);
    expect(db.sql.query("SELECT COUNT(*) AS n FROM process_output_chunks").get()).toEqual({ n: 0 });
  } finally { db.close(); rmSync(root, { recursive: true, force: true }); }
});
