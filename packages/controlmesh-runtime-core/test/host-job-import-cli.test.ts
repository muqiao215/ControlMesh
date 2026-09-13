import { expect, test } from "bun:test";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { RuntimeDatabase } from "../src/database";
import { HostJobStore } from "../src/host-job-store";

test("host-job migration CLI previews, pins a source and imports without running a command", async () => {
  const root = mkdtempSync(join(tmpdir(), "cm-host-cli-")), index = join(root, "index.json"), target = join(root, "target.sqlite"), marker = join(root, "executed");
  const job = { job_id: "old-job", state: "running", created_at: "2026-09-13", updated_at: "2026-09-13", steps: [{ id: "one", state: "running", command: `touch ${marker}`, pid: 12345 }] };
  writeFileSync(index, JSON.stringify({ jobs: [job] })); const original = readFileSync(index);
  const run = async (...extra: string[]) => {
    const process = Bun.spawn([Bun.argv[0]!, join(import.meta.dir, "../scripts/migrate-host-job.ts"), "--legacy-index", index, "--job-id", "old-job", "--database", target, "--principal", "owner", ...extra], { stdout: "pipe", stderr: "pipe" });
    const [stdout, stderr, code] = await Promise.all([new Response(process.stdout).text(), new Response(process.stderr).text(), process.exited]);
    return { code, value: JSON.parse(stdout || stderr) };
  };
  try {
    const preview = await run(); expect(preview.code).toBe(0); expect(preview.value).toMatchObject({ mode: "dry_run", state: "running", step_count: 1, execution_authorized: false });
    expect(JSON.stringify(preview.value)).not.toContain(marker); expect(existsSync(target)).toBe(false);
    expect((await run("--apply")).value.error).toBe("host_job_source_digest_required");
    writeFileSync(index, original.toString() + "\n");
    expect((await run("--apply", "--digest", preview.value.source_digest)).value.error).toBe("host_job_source_digest_changed"); expect(existsSync(target)).toBe(false);
    writeFileSync(index, original);
    const applied = await run("--apply", "--digest", preview.value.source_digest); expect(applied.value).toMatchObject({ mode: "imported", revision: 1, execution_authorized: false });
    expect(await run("--apply", "--digest", preview.value.source_digest)).toEqual(applied);
    expect(existsSync(marker)).toBe(false); expect(readFileSync(index)).toEqual(original);
    const db = new RuntimeDatabase(target);
    try { expect(new HostJobStore(db, () => {}).get({ id: "owner", origin: "human_request", scopes: ["task:read"] }, "old-job")?.job.steps[0]!.pid).toBe(12345); }
    finally { db.close(); }
    expect((await run("--job-directory", root)).value.error).toBe("host_job_source_ambiguous");
  } finally { rmSync(root, { recursive: true, force: true }); }
});
