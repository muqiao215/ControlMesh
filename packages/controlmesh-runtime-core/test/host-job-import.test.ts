import { expect, test } from "bun:test";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { snapshotHostJob, importHostJobSnapshot } from "../src/host-job-import";
import { RuntimeDatabase } from "../src/database";
import { HostJobStore } from "../src/host-job-store";
import type { Principal } from "../src/kernel";

const actor: Principal = { id: "owner", origin: "human_request", scopes: ["task:admin", "task:read"] };
test("Python host-job authority files import coherently, without trusting derived results", async () => {
  const root = mkdtempSync(join(tmpdir(), "cm-host-import-")), jobs = join(root, "jobs"), directory = join(jobs, "job"), index = join(root, "index.json");
  const db = new RuntimeDatabase(":memory:"); mkdirSync(jobs);
  try {
    const child = Bun.spawn(["uv", "run", "python", "-c", "import sys,json; from pathlib import Path; from types import SimpleNamespace; from controlmesh.runtime.host_jobs import HostJob,HostJobStep,HostJobStore; r=Path(sys.argv[1]); p=SimpleNamespace(runtime_host_jobs_path=r/'index.json',runtime_host_jobs_dir=r/'jobs',runtime_host_job_artifacts_dir=r/'artifacts'); s=HostJobStore(p); j=s.put(HostJob(job_id='job',state='running',steps=[HostJobStep(id='one',title='fixture',command='echo fixture',state='running',pid=12345)],created_at='2026-09-13',updated_at='2026-09-13')); print(json.dumps(s.get('job').to_dict()))", root], { cwd: join(import.meta.dir, "../../.."), stdout: "pipe", stderr: "pipe" });
    const output = await new Response(child.stdout).text(); expect(await child.exited).toBe(0);
    const source = { job_id: "job", job_directory: directory };
    const snapshot = snapshotHostJob(source); expect(snapshot.job).toEqual(JSON.parse(output));
    expect(() => importHostJobSnapshot(db, { ...actor, scopes: [] }, () => {}, source, snapshot.source_digest)).toThrow("scope_denied");
    writeFileSync(join(directory, "TOOL_RESULT.json"), '{"status":"completed","exit_code":0}');
    expect(snapshotHostJob(source).source_digest).toBe(snapshot.source_digest);
    const imported = importHostJobSnapshot(db, actor, () => {}, source, snapshot.source_digest);
    expect(imported.job.state).toBe("running"); expect(imported.job.steps[0]!.pid).toBe(12345);
    expect(importHostJobSnapshot(db, actor, () => {}, source, snapshot.source_digest)).toEqual(imported);
    expect(snapshotHostJob({ job_id: "job", legacy_index: index }).job).toEqual(snapshot.job);
    const stepsPath = join(directory, "STEPS.json"), original = readFileSync(stepsPath, "utf8"), steps = JSON.parse(original);
    writeFileSync(stepsPath, JSON.stringify({ ...steps, updated_at: "different" }));
    expect(() => snapshotHostJob(source)).toThrow("host_job_authority_files_inconsistent");
    writeFileSync(stepsPath, original + "\n");
    expect(() => importHostJobSnapshot(db, actor, () => {}, source, snapshot.source_digest)).toThrow("host_job_source_digest_changed");
    const changed = snapshotHostJob(source);
    expect(() => importHostJobSnapshot(db, actor, () => {}, source, changed.source_digest)).toThrow("host_job_revision_conflict");
    expect(new HostJobStore(db, () => {}).get(actor, "job")).toEqual(imported);
    rmSync(stepsPath);
    expect(() => snapshotHostJob(source)).toThrow(); // Explicit directory mode never falls back to the existing index.
    writeFileSync(index, JSON.stringify({ jobs: [snapshot.job, snapshot.job] }));
    expect(() => snapshotHostJob({ job_id: "job", legacy_index: index })).toThrow("host_job_index_identity_ambiguous");
  } finally { db.close(); rmSync(root, { recursive: true, force: true }); }
});
