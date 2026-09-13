import { requireScope } from "./commands";
import { basename, isAbsolute, join } from "node:path";
import { lstatSync, realpathSync } from "node:fs";
import { decodeHostJob } from "./host-job-model";
import { HostJobStore } from "./host-job-store";
import { runtimeEventFileSnapshot } from "./runtime-event-import";
import { RuntimeDatabase } from "./database";
import type { Principal } from "./kernel";
import { digest, identifier, object, requireThat } from "./value";

export type HostJobImportSource = { job_id: string; job_directory: string; legacy_index?: never } | { job_id: string; legacy_index: string; job_directory?: never };
/** Explicit source only; never scans operator directories or treats TOOL_RESULT as execution proof. */
export function snapshotHostJob(source: HostJobImportSource) {
  identifier(source.job_id);
  requireThat((typeof source.job_directory === "string") !== (typeof source.legacy_index === "string"), "host_job_source_ambiguous");
  const files: { path: string; sha256: string; bytes: number }[] = [];
  const read = (path: string): unknown => {
    const snapshot = runtimeEventFileSnapshot(path);
    files.push({ path, sha256: snapshot.sha256, bytes: snapshot.bytes });
    return JSON.parse(snapshot.text);
  };
  let raw: unknown;
  if (source.job_directory !== undefined) {
    const directory = source.job_directory;
    requireThat(isAbsolute(directory) && realpathSync(directory) === directory && lstatSync(directory).isDirectory()
      && basename(directory) === source.job_id, "host_job_directory_mismatch");
    const metadata = read(join(directory, "HOST_JOB.json")), steps = read(join(directory, "STEPS.json"));
    requireThat(object(metadata) && object(steps) && metadata.job_id === source.job_id && steps.job_id === source.job_id
      && typeof metadata.updated_at === "string" && metadata.updated_at === steps.updated_at && Array.isArray(steps.steps), "host_job_authority_files_inconsistent");
    raw = { ...metadata, steps: steps.steps };
  } else {
    const index = read(source.legacy_index!);
    requireThat(object(index) && Array.isArray(index.jobs) && index.jobs.length <= 10000, "invalid_host_job_index");
    const candidates = index.jobs.filter(job => object(job) && job.job_id === source.job_id);
    requireThat(candidates.length === 1, "host_job_index_identity_ambiguous"); raw = candidates[0];
  }
  const job = decodeHostJob(raw);
  requireThat(job.job_id === source.job_id, "host_job_identity_changed");
  // Both files must still match after decoding; an interrupted multi-file save is not a snapshot.
  for (const file of files) requireThat(runtimeEventFileSnapshot(file.path).sha256 === file.sha256, "host_job_source_changed");
  return { source_digest: digest({ source, files, job }), files, job };
}
export function importHostJobSnapshot(db: RuntimeDatabase, actor: Principal, authorize: () => void, source: HostJobImportSource, expectedDigest: string) {
  requireScope(actor, "task:admin");
  const authorization: unknown = authorize();
  if (authorization !== undefined) { void Promise.resolve(authorization).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
  requireThat(/^[a-f0-9]{64}$/.test(expectedDigest), "host_job_source_digest_required");
  const snapshot = snapshotHostJob(source);
  requireThat(snapshot.source_digest === expectedDigest, "host_job_source_digest_changed");
  // Create-only import: an existing live record cannot be overwritten by a legacy snapshot.
  return new HostJobStore(db, authorize).put(actor, `host-import-${digest([actor.id, expectedDigest])}`, 0, snapshot.job);
}
