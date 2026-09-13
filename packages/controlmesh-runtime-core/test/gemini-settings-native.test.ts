import { expect, test } from "bun:test";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

const module = process.env.CM_GEMINI_SETTINGS_MODULE, node = process.env.CM_GEMINI_SETTINGS_NODE;
test.skipIf(!module || !node)("native Gemini settings preflight preserves deprecated settings under Node write denial", async () => {
  const root = mkdtempSync(join(tmpdir(), "cm-gemini-readonly-")), home = join(root, "home"), workspace = join(root, "workspace");
  mkdirSync(home); mkdirSync(join(home, ".gemini")); mkdirSync(workspace);
  const path = join(home, ".gemini/settings.json"), original = JSON.stringify({ general: { disableAutoUpdate: true }, custom_fixture_secret: "never-emit-fixture-secret" });
  writeFileSync(path, original);
  const script = join(import.meta.dir, "../scripts/gemini-settings-probe.mjs");
  const launch = async (restricted: boolean, writable = false) => {
    const child = Bun.spawn([node!, ...(restricted ? ["--experimental-permission", "--allow-fs-read=*"] : []), ...(writable ? [`--allow-fs-write=${home}`] : []), script, module!, workspace, "--ignore-env"], {
      cwd: workspace, env: { HOME: home, GEMINI_CLI_HOME: home, PATH: "/usr/bin:/bin",
        GEMINI_CLI_SYSTEM_SETTINGS_PATH: join(root, "system.json"), GEMINI_CLI_SYSTEM_DEFAULTS_PATH: join(root, "defaults.json") },
      stdin: "ignore", stdout: "pipe", stderr: "pipe",
    });
    const timeout = setTimeout(() => child.kill("SIGKILL"), 10000);
    try { return { code: await child.exited, out: await new Response(child.stdout).text(), err: await new Response(child.stderr).text() }; }
    finally { clearTimeout(timeout); }
  };
  try {
    const denied = await launch(false); expect(denied.code).toBe(2); expect(denied.out).toContain("gemini_settings_probe_failed");
    expect((await launch(true, true)).code).toBe(2);
    const first = await launch(true); expect(first.code).toBe(0);
    expect(first.out + first.err).not.toContain("never-emit-fixture-secret");
    expect(JSON.parse(first.out).settings_digest).toMatch(/^[a-f0-9]{64}$/);
    expect(JSON.parse(first.out).sources).toContain(path);
    expect(readFileSync(path, "utf8")).toBe(original);
    writeFileSync(path, JSON.stringify({ general: { enableAutoUpdate: true } }));
    const second = await launch(true); expect(second.code).toBe(0);
    expect(JSON.parse(second.out).settings_digest).not.toBe(JSON.parse(first.out).settings_digest);
  } finally { rmSync(root, { recursive: true, force: true }); }
}, 20000);
