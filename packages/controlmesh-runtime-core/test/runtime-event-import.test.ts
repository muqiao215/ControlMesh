import { expect, test } from "bun:test";
import { existsSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("migration CLI previews without a database, binds source bytes and applies once", async () => {
  const root = mkdtempSync(join(tmpdir(), "cm-event-import-")), source = join(root, "events.jsonl"), database = join(root, "target.sqlite");
  const event = { event_id: "one", session_key: "tg:123", event_type: "progress", payload: {}, created_at: "2026-09-13", transport: "tg", chat_id: 123, topic_id: null };
  writeFileSync(source, JSON.stringify(event) + "\n");
  const original = readFileSync(source);
  const run = async (...extra: string[]) => {
    const child = Bun.spawn([process.execPath, join(import.meta.dir, "../scripts/migrate-runtime-events.ts"), "--source", source, "--database", database, "--principal", "owner", "--session", "tg:123", ...extra], { stdout: "pipe", stderr: "pipe" });
    const [out, err, code] = await Promise.all([new Response(child.stdout).text(), new Response(child.stderr).text(), child.exited]);
    return { code, value: JSON.parse(out || err) };
  };
  try {
    const preview = await run(); expect(preview.code).toBe(0); expect(preview.value).toMatchObject({ mode: "dry_run", unique_events: 1 });
    expect(existsSync(database)).toBe(false);
    expect((await run("--apply")).value.error).toBe("event_source_digest_required");
    writeFileSync(source, original.toString() + "\n");
    expect((await run("--apply", "--sha256", preview.value.sha256)).value.error).toBe("event_source_digest_changed");
    expect(existsSync(database)).toBe(false);
    writeFileSync(source, original);
    expect((await run("--apply", "--sha256", preview.value.sha256)).value).toMatchObject({ mode: "applied", imported: 1, replayed: 0 });
    expect((await run("--apply", "--sha256", preview.value.sha256)).value).toMatchObject({ imported: 0, replayed: 1 });
    expect(readFileSync(source)).toEqual(original);
    rmSync(source); const other = join(root, "other"); writeFileSync(other, original); symlinkSync(other, source);
    expect((await run()).value.error).toBe("event_source_must_be_canonical");
  } finally { rmSync(root, { recursive: true, force: true }); }
});
