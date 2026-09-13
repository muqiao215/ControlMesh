import { expect, test } from "bun:test";
import { mkdtempSync, readFileSync, rmSync, statSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { LegacyMigration, RuntimeDatabase, RuntimeKernel, type Principal } from "../src";
import fixture from "../../../tests/golden/fixtures/tasks/legacy-registry.json";

const script = join(import.meta.dir, "../scripts/legacy-export.ts");
const actor: Principal = { id: "operator", origin: "internal", scopes: ["task:create"] };
async function run(database: string, output: string) {
  const child = Bun.spawn([process.execPath, script, "--database", database, "--source-id", "python", "--output", output], { stdout: "pipe", stderr: "pipe" });
  const [code, stdout, stderr] = await Promise.all([child.exited, new Response(child.stdout).text(), new Response(child.stderr).text()]);
  return { code, stdout, stderr };
}

test("offline compatibility export preserves Python fields plus new TS tasks without mutating its source", async () => {
  const root = mkdtempSync(join(tmpdir(), "cm-export-")), path = join(root, "runtime.sqlite"), output = join(root, "rollback.json");
  try {
    const db = new RuntimeDatabase(path), migration = new LegacyMigration(db);
    migration.importSnapshot("python", fixture, migration.preview("python", fixture).digest, actor.id);
    const created = { task_id: "created-in-ts", chat_id: "test", status: "waiting", future: { retained: true } };
    new RuntimeKernel(db).submit(actor, "new", created); db.close();
    const before = readFileSync(path); const result = await run(path, output);
    expect(result.code).toBe(0); expect(readFileSync(path)).toEqual(before);
    const exported = JSON.parse(readFileSync(output, "utf8"));
    expect(exported).toEqual({ ...fixture, tasks: [...fixture.tasks, created] });
    expect(statSync(output).mode & 0o777).toBe(0o600);
    expect(JSON.parse(result.stdout).writer_authority).toBe("not_transferred");
    // Rehearse loading the artifact into an empty candidate, retaining cancelled status.
    const target = new RuntimeDatabase(join(root, "rehearsal.sqlite"));
    try { const replay = new LegacyMigration(target); replay.importSnapshot("export", exported, replay.preview("export", exported).digest, actor.id);
      expect(replay.exportSnapshot("export")).toEqual(exported); }
    finally { target.close(); }
    const bytes = readFileSync(output); expect((await run(path, output)).code).toBe(1); expect(readFileSync(output)).toEqual(bytes);
    const link = join(root, "linked.json"); symlinkSync(output, link);
    expect((await run(path, link)).code).toBe(1); expect(readFileSync(output)).toEqual(bytes);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("export refuses missing databases and lost imported tasks without creating output", async () => {
  const root = mkdtempSync(join(tmpdir(), "cm-export-invalid-")), path = join(root, "runtime.sqlite"), output = join(root, "rollback.json");
  try {
    expect((await run(path, output)).code).toBe(1); expect(await Bun.file(path).exists()).toBe(false);
    const db = new RuntimeDatabase(path), migration = new LegacyMigration(db);
    migration.importSnapshot("python", fixture, migration.preview("python", fixture).digest, actor.id);
    db.sql.query("DELETE FROM tasks WHERE task_id=?").run(fixture.tasks[0].task_id); db.close();
    const result = await run(path, output); expect(result.code).toBe(1); expect(result.stderr).toContain("migration_task_missing");
    expect(await Bun.file(output).exists()).toBe(false);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
