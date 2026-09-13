import { expect, test } from "bun:test";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, realpathSync, rmSync, existsSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { hostJobEnvironment } from "../src/host-job-environment";
import { openLocalRuntime } from "../src/local-runtime-config";

test("trusted host environment rejects invalid process entries and snapshots input", () => {
  for (const value of [null, [], { BAD: 1 }, { "BAD=KEY": "value" }, { BAD: "nul\0value" }]) expect(() => hostJobEnvironment(value)).toThrow("invalid_host_environment");
  const source = { TOOL_MODE: "first" }, env = hostJobEnvironment(source); source.TOOL_MODE = "second";
  expect(env.TOOL_MODE).toBe("first"); expect(Object.isFrozen(env)).toBe(true);
});

for (const changed of [false, true]) test(`configured tool PATH executes only with queued environment binding unchanged=${!changed}`, async () => {
  const root = mkdtempSync(join(tmpdir(), "cm-host-env-")), state = join(root, "state"), workspace = join(root, "workspace"), bin = join(root, "bin"), path = join(root, "config.json");
  mkdirSync(state, { mode: 0o700 }); mkdirSync(workspace); mkdirSync(bin);
  writeFileSync(join(bin, "cm-fixture-build"), '#!/bin/sh\nprintf "%s" "$TOOL_MODE" > artifact\n', { mode: 0o700 });
  const config = { schema_version: "controlmesh.local_runtime.v1", mode: "candidate", state_root: state,
    principal_id: "owner", device_id: "local", source: { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: "terminal" },
    host: { shell: realpathSync("/bin/bash"), environment: { PATH: `${bin}:/usr/bin:/bin`, TOOL_MODE: "explicit-build-profile" } },
    workspace: { directory: workspace, read_files: [], required_reads: [] } };
  const save = () => writeFileSync(path, JSON.stringify(config), { mode: 0o600 }); save();
  let owned = openLocalRuntime(path);
  try {
    owned.runtime.submit("create", { task_id: "build", chat_id: "test", status: "waiting", workunit_kind: "uv_build", command: "cm-fixture-build" }, { chat_id: "test" });
    owned.runtime.enqueue("enqueue", "build", 1);
    await owned.close();
    if (changed) { config.host.environment.TOOL_MODE = "changed-profile"; save(); }
    owned = openLocalRuntime(path); await owned.runtime.drain();
    const db = owned.runtime.kernel.db;
    if (changed) {
      expect(existsSync(join(workspace, "artifact"))).toBe(false);
      expect(db.sql.query("SELECT COUNT(*) AS n FROM effects").get()).toEqual({ n: 0 });
    } else {
      expect(owned.runtime.inspectTask("build").task.status).toBe("done");
      expect(readFileSync(join(workspace, "artifact"), "utf8")).toBe("explicit-build-profile");
      const manifest = (db.sql.query("SELECT payload FROM execution_manifests").get() as { payload: string }).payload;
      expect(manifest).not.toContain("explicit-build-profile");
      expect(JSON.parse(manifest).environment_digest).toMatch(/^[a-f0-9]{64}$/);
    }
  } finally { await owned.close(); rmSync(root, { recursive: true, force: true }); }
});
