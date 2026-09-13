#!/usr/bin/env bun
import { isAbsolute } from "node:path";
import { RuntimeDatabase } from "../src/database";
import { importHostJobSnapshot, snapshotHostJob, type HostJobImportSource } from "../src/host-job-import";
import { identifier, requireThat, RuntimeConflict } from "../src/value";

try {
  const args = process.argv.slice(2), values: Record<string, string> = {};
  let apply = false;
  for (let i = 0; i < args.length; i++) {
    const flag = args[i]!;
    if (flag === "--apply") { requireThat(!apply, "duplicate_migration_option"); apply = true; continue; }
    requireThat(["--job-directory", "--legacy-index", "--job-id", "--database", "--principal", "--digest"].includes(flag)
      && values[flag] === undefined && typeof args[i + 1] === "string" && !args[i + 1]!.startsWith("--"), "invalid_migration_option");
    values[flag] = args[++i]!;
  }
  for (const flag of ["--job-id", "--database", "--principal"]) requireThat(values[flag], "missing_migration_option");
  requireThat((values["--job-directory"] !== undefined) !== (values["--legacy-index"] !== undefined), "host_job_source_ambiguous");
  identifier(values["--principal"]); identifier(values["--job-id"]);
  requireThat(isAbsolute(values["--database"]!), "database_path_must_be_explicit");
  requireThat(!apply || (typeof values["--digest"] === "string" && /^[a-f0-9]{64}$/.test(values["--digest"]!)), "host_job_source_digest_required");
  const source: HostJobImportSource = values["--job-directory"] !== undefined
    ? { job_id: values["--job-id"]!, job_directory: values["--job-directory"]! }
    : { job_id: values["--job-id"]!, legacy_index: values["--legacy-index"]! };
  const snapshot = snapshotHostJob(source);
  requireThat(!apply || snapshot.source_digest === values["--digest"], "host_job_source_digest_changed");
  const report = { source_digest: snapshot.source_digest, job_id: snapshot.job.job_id, state: snapshot.job.state,
    step_count: snapshot.job.steps.length, source_bytes: snapshot.files.reduce((sum, file) => sum + file.bytes, 0), execution_authorized: false };
  if (!apply) console.log(JSON.stringify({ mode: "dry_run", ...report }));
  else {
    const db = new RuntimeDatabase(values["--database"]!);
    try {
      const imported = importHostJobSnapshot(db, { id: values["--principal"]!, origin: "human_request", scopes: ["task:admin"] }, () => {}, source, values["--digest"]!);
      console.log(JSON.stringify({ mode: "imported", ...report, revision: imported.revision }));
    } finally { db.close(); }
  }
} catch (error) {
  console.error(JSON.stringify({ error: error instanceof RuntimeConflict ? error.code : "host_job_migration_failed" }));
  process.exitCode = 2;
}
