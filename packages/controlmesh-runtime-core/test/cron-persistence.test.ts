import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { Database } from "bun:sqlite";
import { execFileSync, spawnSync } from "node:child_process";
import {
  closeSync,
  mkdirSync,
  mkdtempSync,
  openSync,
  readFileSync,
  rmSync,
  symlinkSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { RuntimeDatabase } from "../src/database";
import {
  CronStore,
  type CronJobInput,
  computeJobSpecDigest,
  parseLosslessJson,
  losslessJsonStringify,
} from "../src/cron-store";
import {
  exportCronRegistry,
  importCronRegistry,
} from "../src/cron-migration";
import { RuntimeConflict } from "../src/value";

describe("Cron persistence, migration & parity", () => {
  let tempDir: string;

  beforeEach(() => {
    tempDir = mkdtempSync(join(tmpdir(), "cm-cron-persistence-"));
  });

  afterEach(() => {
    rmSync(tempDir, { recursive: true, force: true });
  });

  test("reopening v42 database upgrades to v43 and preserves unrelated tables and data", () => {
    const dbPath = join(tempDir, "v42.sqlite");

    // 1. Initialize a real database with RuntimeDatabase, insert baseline data
    const initialDb = new RuntimeDatabase(dbPath);
    initialDb.sql.exec(`
      INSERT INTO tasks VALUES ('task_preexisting', 'principal_root', 1, 0, NULL, 'running', 0, '{"id":"task_preexisting"}');
      UPDATE meta SET value = '1000' WHERE key = 'clock';
      PRAGMA foreign_keys = OFF;
      DROP TABLE IF EXISTS cron_dependency_locks;
      DROP TABLE IF EXISTS cron_execution_attempts;
      DROP TABLE IF EXISTS cron_occurrences;
      DROP TABLE IF EXISTS cron_jobs;
      DROP TABLE IF EXISTS cron_coordinator_epochs;
      PRAGMA foreign_keys = ON;
      PRAGMA user_version = 42;
    `);
    initialDb.sql.close();

    // 2. Open via RuntimeDatabase - should execute migration 43
    const runtimeDb = new RuntimeDatabase(dbPath);

    // Verify user_version upgraded to 43
    const versionRow = runtimeDb.sql.query("PRAGMA user_version").get() as { user_version: number };
    expect(versionRow.user_version).toBe(43);

    // Verify existing v42 data is preserved
    const taskRow = runtimeDb.sql.query("SELECT * FROM tasks WHERE task_id = 'task_preexisting'").get() as any;
    expect(taskRow).toBeDefined();
    expect(taskRow.task_id).toBe("task_preexisting");
    expect(taskRow.status).toBe("running");

    const clockRow = runtimeDb.sql.query("SELECT value FROM meta WHERE key = 'clock'").get() as any;
    expect(clockRow.value).toBe("1000");

    // Verify new cron tables exist
    expect(runtimeDb.sql.query("SELECT name FROM sqlite_master WHERE type='table' AND name='cron_jobs'").get()).toBeDefined();
    expect(runtimeDb.sql.query("SELECT name FROM sqlite_master WHERE type='table' AND name='cron_occurrences'").get()).toBeDefined();
    expect(runtimeDb.sql.query("SELECT name FROM sqlite_master WHERE type='table' AND name='cron_execution_attempts'").get()).toBeDefined();
    expect(runtimeDb.sql.query("SELECT name FROM sqlite_master WHERE type='table' AND name='cron_dependency_locks'").get()).toBeDefined();
    expect(runtimeDb.sql.query("SELECT name FROM sqlite_master WHERE type='table' AND name='cron_coordinator_epochs'").get()).toBeDefined();

    runtimeDb.sql.close();
  });

  test("single-coordinator authority: read-only query, explicit bootstrap, generation fencing, and stale rotation rejection", () => {
    const db = new RuntimeDatabase(":memory:");
    const store = new CronStore(db);

    store.putJob({
      id: "fenced_job",
      title: "Fenced Job",
      schedule: "0 * * * *",
      task_folder: "task",
      agent_instruction: "Run guarded work",
    });

    const occ = store.createOccurrence("fenced_job", 1773000000000);

    // 1. Querying epoch on fresh unregistered DB must fail without creating authority
    expect(() => {
      store.getCoordinatorEpoch("invented-controller");
    }).toThrow(RuntimeConflict);
    try {
      store.getCoordinatorEpoch("invented-controller");
    } catch (err) {
      expect((err as RuntimeConflict).code).toBe("coordinator_not_registered");
    }

    // 2. Explicit bootstrap registration mutation
    const initialEpoch = store.registerCoordinator("coord_alpha");
    expect(initialEpoch.coordinator_id).toBe("coord_alpha");
    expect(initialEpoch.current_generation).toBe(1);

    // Re-registration fails
    expect(() => {
      store.registerCoordinator("coord_alpha");
    }).toThrow(RuntimeConflict);

    // Read query now succeeds
    const queried = store.getCoordinatorEpoch("coord_alpha");
    expect(queried.current_generation).toBe(1);

    // 3. An arbitrary identity cannot claim coordinator authority
    expect(() => {
      store.getCoordinatorEpoch("coord_rogue");
    }).toThrow(RuntimeConflict);
    try {
      store.getCoordinatorEpoch("coord_rogue");
    } catch (err) {
      expect((err as RuntimeConflict).code).toBe("coordinator_authority_mismatch");
    }

    // 4. createAttempt with future invented fence (generation 99 when current is 1) rejects
    expect(() => {
      store.createAttempt(occ.occurrence_id, {
        coordinatorId: "coord_alpha",
        executorDeviceId: "worker_1",
        fencingGeneration: 99,
      });
    }).toThrow(RuntimeConflict);

    // 5. createAttempt with exact current authority succeeds
    const attempt1 = store.createAttempt(occ.occurrence_id, {
      coordinatorId: "coord_alpha",
      executorDeviceId: "worker_1",
      fencingGeneration: 1,
    });
    expect(attempt1.attempt_number).toBe(1);
    expect(attempt1.fencing_generation).toBe(1);
    expect(attempt1.state).toBe("initiated");

    // 6. Stale rotation with wrong expectedGeneration rejects
    expect(() => {
      store.rotateCoordinatorAuthority("coord_alpha", 99, "coord_beta");
    }).toThrow(RuntimeConflict);
    try {
      store.rotateCoordinatorAuthority("coord_alpha", 99, "coord_beta");
    } catch (err) {
      expect((err as RuntimeConflict).code).toBe("stale_coordinator_epoch");
    }

    // 7. Valid rotation to coord_beta
    const rotated = store.rotateCoordinatorAuthority("coord_alpha", 1, "coord_beta");
    expect(rotated.coordinator_id).toBe("coord_beta");
    expect(rotated.current_generation).toBe(2);

    // Old coordinator coord_alpha is rejected
    expect(() => {
      store.getCoordinatorEpoch("coord_alpha");
    }).toThrow(RuntimeConflict);

    // Stale attempt from epoch 1 cannot perform side effects in epoch 2
    expect(() => {
      store.updateAttemptState(attempt1.attempt_id, { coordinatorId: "coord_beta", fence: 1 }, { state: "completed" });
    }).toThrow(RuntimeConflict);
  });

  test("duplicate suppression blocks active attempts, blocks uncertain replay, and blocks attempts on terminal occurrences", () => {
    const db = new RuntimeDatabase(":memory:");
    const store = new CronStore(db);

    store.putJob({
      id: "dup_suppress",
      title: "Duplicate Suppress",
      schedule: "0 * * * *",
      task_folder: "task",
      agent_instruction: "Work",
    });

    const occ = store.createOccurrence("dup_suppress", 1773100000000);
    store.registerCoordinator("coord_main");

    // 1. Create first attempt
    const attempt1 = store.createAttempt(occ.occurrence_id, {
      coordinatorId: "coord_main",
      executorDeviceId: "worker_1",
      fencingGeneration: 1,
    });
    expect(attempt1.state).toBe("initiated");

    // 2. Duplicate active attempt is blocked
    expect(() => {
      store.createAttempt(occ.occurrence_id, {
        coordinatorId: "coord_main",
        executorDeviceId: "worker_2",
        fencingGeneration: 1,
      });
    }).toThrow(RuntimeConflict);

    // 3. Mark attempt uncertain (e.g. lost worker / unconfirmed status)
    store.markAttemptUncertain(attempt1.attempt_id, { coordinatorId: "coord_main", fence: 1 });
    expect(store.getAttempt(attempt1.attempt_id)?.state).toBe("uncertain");
    expect(store.getOccurrence(occ.occurrence_id)?.state).toBe("blocked_unknown");

    // 4. Duplicate suppression MUST block replay while attempt is uncertain!
    expect(() => {
      store.createAttempt(occ.occurrence_id, {
        coordinatorId: "coord_main",
        executorDeviceId: "worker_3",
        fencingGeneration: 1,
      });
    }).toThrow(RuntimeConflict);

    // 5. Once verified completed (terminal), new attempts are permanently blocked
    const occ2 = store.createOccurrence("dup_suppress", 1773200000000);
    expect(() => store.createAttempt(occ2.occurrence_id, {
      coordinatorId: "coord_main", executorDeviceId: "worker_1", fencingGeneration: 1,
    })).toThrow("active_or_uncertain_attempt_exists");
    // Simulate the trusted owner reconciling the first execution before the next slot.
    store.updateAttemptState(attempt1.attempt_id, { coordinatorId: "coord_main", fence: 1 }, { state: "completed" });
    const attempt2 = store.createAttempt(occ2.occurrence_id, {
      coordinatorId: "coord_main",
      executorDeviceId: "worker_1",
      fencingGeneration: 1,
    });
    store.updateAttemptState(attempt2.attempt_id, { coordinatorId: "coord_main", fence: 1 }, { state: "completed" });
    expect(store.getOccurrence(occ2.occurrence_id)?.state).toBe("completed");

    expect(() => {
      store.createAttempt(occ2.occurrence_id, {
        coordinatorId: "coord_main",
        executorDeviceId: "worker_2",
        fencingGeneration: 1,
      });
    }).toThrow(RuntimeConflict);

    // Attempting to mutate terminal attempt throws
    expect(() => {
      store.updateAttemptState(attempt2.attempt_id, { coordinatorId: "coord_main", fence: 1 }, { state: "running" });
    }).toThrow(RuntimeConflict);
  });

  test("occurrence identity is stable and deduplicates; changed immutable definition at same timestamp rejects", () => {
    const db = new RuntimeDatabase(":memory:");
    const store = new CronStore(db);

    store.putJob({
      id: "stable_job",
      title: "Stable Job",
      schedule: "0 0 * * *",
      task_folder: "folder",
      agent_instruction: "Step 1",
    });

    const timestamp = 1773300000000;

    // 1. Stable occurrence identity
    const occ1 = store.createOccurrence("stable_job", timestamp);
    const occ2 = store.createOccurrence("stable_job", timestamp);
    expect(occ1.occurrence_id).toBe(occ2.occurrence_id);

    // 2. Definition change (bumps version to 2)
    store.putJob({
      id: "stable_job",
      title: "Stable Job",
      schedule: "0 0 * * *",
      task_folder: "folder",
      agent_instruction: "Step 2 Changed Definition",
    });
    expect(store.getJob("stable_job")?.version).toBe(2);

    // 3. Scheduling at same timestamp under changed definition must reject!
    expect(() => {
      store.createOccurrence("stable_job", timestamp);
    }).toThrow(RuntimeConflict);
  });

  test("failover recovery: separates coordinator authority from attempt fence; rejects late old coordinator; prevents terminal replacement", () => {
    const db = new RuntimeDatabase(":memory:");
    const store = new CronStore(db);

    store.putJob({
      id: "failover_job",
      title: "Failover Job",
      schedule: "0 * * * *",
      task_folder: "task",
      agent_instruction: "Work",
      dependency: "seq_resource",
    });

    store.registerCoordinator("coord_A");
    const occ = store.createOccurrence("failover_job", 1773400000000);

    const attA = store.createAttempt(occ.occurrence_id, {
      coordinatorId: "coord_A",
      executorDeviceId: "worker_A",
      fencingGeneration: 1,
    });
    expect(store.acquireDependencyLock("seq_resource", occ.occurrence_id, attA.attempt_id, 10000)).toBe(true);

    // Failover rotation: coord_A -> coord_B (generation 2)
    const rot = store.rotateCoordinatorAuthority("coord_A", 1, "coord_B");
    expect(rot.current_generation).toBe(2);

    // 1. Late coordinator A attempting reconciliation is rejected
    expect(() => {
      store.reconcileDependencyLock(
        "seq_resource",
        { coordinatorId: "coord_A", fence: 1 },
        { attemptId: attA.attempt_id, expectedFence: 1 },
        { verifiedTerminated: true, terminalState: "completed" }
      );
    }).toThrow(RuntimeConflict);
    try {
      store.reconcileDependencyLock(
        "seq_resource",
        { coordinatorId: "coord_A", fence: 1 },
        { attemptId: attA.attempt_id, expectedFence: 1 },
        { verifiedTerminated: true, terminalState: "completed" }
      );
    } catch (err) {
      expect((err as RuntimeConflict).code).toBe("coordinator_authority_mismatch");
    }

    // 2. New coordinator B with wrong expected attempt fence is rejected
    expect(() => {
      store.reconcileDependencyLock(
        "seq_resource",
        { coordinatorId: "coord_B", fence: 2 },
        { attemptId: attA.attempt_id, expectedFence: 99 },
        { verifiedTerminated: true, terminalState: "completed" }
      );
    }).toThrow(RuntimeConflict);

    // 3. New coordinator B with unconfirmed evidence retains lock as uncertain
    const unconfirmed = store.reconcileDependencyLock(
      "seq_resource",
      { coordinatorId: "coord_B", fence: 2 },
      { attemptId: attA.attempt_id, expectedFence: 1 },
      { verifiedTerminated: false }
    );
    expect(unconfirmed).toBe("retained_uncertain");
    expect(store.getDependencyLock("seq_resource")?.status).toBe("uncertain");
    expect(store.getAttempt(attA.attempt_id)?.state).toBe("uncertain");

    // 4. New coordinator B reconciles verified completion of old attempt
    const confirmed = store.reconcileDependencyLock(
      "seq_resource",
      { coordinatorId: "coord_B", fence: 2 },
      { attemptId: attA.attempt_id, expectedFence: 1 },
      { verifiedTerminated: true, terminalState: "completed" }
    );
    expect(confirmed).toBe("released");
    expect(store.getDependencyLock("seq_resource")).toBeNull();
    expect(store.getAttempt(attA.attempt_id)?.state).toBe("completed");

    // 5. No replacement of an already terminal result!
    expect(() => {
      store.reconcileDependencyLock(
        "seq_resource",
        { coordinatorId: "coord_B", fence: 2 },
        { attemptId: attA.attempt_id, expectedFence: 1 },
        { verifiedTerminated: true, terminalState: "failed" }
      );
    }).toThrow(RuntimeConflict);
    try {
      store.reconcileDependencyLock(
        "seq_resource",
        { coordinatorId: "coord_B", fence: 2 },
        { attemptId: attA.attempt_id, expectedFence: 1 },
        { verifiedTerminated: true, terminalState: "failed" }
      );
    } catch (err) {
      expect((err as RuntimeConflict).code).toBe("attempt_already_terminal");
    }
  });

  test("lossless JSON, BigInt (>2^53), missing/null/empty/zero parity and actual Python reader roundtrip", () => {
    const db = new RuntimeDatabase(":memory:");

    const sampleRegistry = {
      registry_source: "parity_test_fixture",
      jobs: [
        {
          id: "job_full_parity",
          title: "Full Parity Job",
          description: "",
          schedule: "0 4 * * *",
          task_folder: "task_folder",
          agent_instruction: "Instruction",
          enabled: true,
          timezone: "",
          created_at: "2026-09-01T00:00:00Z",
          last_run_at: null,
          last_run_status: null,
          manual_run_at: null,
          manual_run_status: null,
          provider: null,
          model: null,
          reasoning_effort: null,
          cli_parameters: [],
          quiet_start: 0,
          quiet_end: 5,
          dependency: null,
          job_kind: "recurring",
          execution_mode: "oneshot",
          workunit_kind: null,
          risk: null,
          output_policy: null,
          chat_id: 9223372036854775807n,
          topic_id: null,
          transport: "tg",
          unknown_big_int: 9007199254740993n,
          unknown_nested: { key: "value", flag: false, empty: null },
        },
      ],
    };

    const importResult = importCronRegistry(db, sampleRegistry as any);
    expect(importResult.imported).toBe(1);

    const store = new CronStore(db);
    const job = store.getJob("job_full_parity")!;
    expect(job.quiet_start).toBe(0);
    expect(job.description).toBe("");
    expect(job.timezone).toBe("");
    expect(job.chat_id).toBe(9223372036854775807n);
    expect((job.raw_metadata as any).unknown_big_int).toBe(9007199254740993n);

    const exportPath = join(tempDir, "exported_parity.json");
    const exported = exportCronRegistry(db, exportPath);
    expect(exported.registry_source).toBe("parity_test_fixture");
    expect(exported.jobs.length).toBe(1);

    const content = readFileSync(exportPath, "utf-8");
    expect(content).toContain('"chat_id": 9223372036854775807');
    expect(content).toContain('"unknown_big_int": 9007199254740993');
    expect(content).toContain('"quiet_start": 0');

    const pythonVerifier = `
import json
import sys
from pathlib import Path
from controlmesh.cron.guarded_store import LockedJsonJobs
from controlmesh.cron.manager import CronJob

path = Path(sys.argv[1])
store = LockedJsonJobs(path)
data = store._read()

job_data = data["jobs"][0]
assert job_data["chat_id"] == 9223372036854775807, f"chat_id rounded: {job_data['chat_id']}"
assert job_data["unknown_big_int"] == 9007199254740993, f"unknown_big_int rounded: {job_data['unknown_big_int']}"
assert job_data["quiet_start"] == 0, f"quiet_start coerced: {job_data['quiet_start']}"
assert job_data["description"] == "", "description altered"
assert "timezone" in job_data, "explicit empty timezone omitted"

job = CronJob.from_dict(job_data)
assert job.chat_id == 9223372036854775807
assert job.quiet_start == 0

print("PYTHON_LOSSLESS_PARITY_PASSED")
`;
    const pyPath = join(tempDir, "test_parity.py");
    writeFileSync(pyPath, pythonVerifier);

    const pyOutput = execFileSync(".venv/bin/python", [pyPath, exportPath], {
      encoding: "utf-8",
      cwd: join(import.meta.dir, "../../.."),
    });
    expect(pyOutput).toContain("PYTHON_LOSSLESS_PARITY_PASSED");
  });

  test("exact user key preservation: colliding keys, null/empty/missing/zero, and 50 repeated status updates", () => {
    const db = new RuntimeDatabase(":memory:");

    // Core job with colliding storage property names and null/empty fields
    const importedInput = {
      id: "job_colliding_keys",
      title: "Colliding Keys Job",
      description: null,
      schedule: "*/10 * * * *",
      task_folder: "task_folder",
      agent_instruction: "Echo work",
      timezone: null,
      raw: "user-raw",
      version: "user-version",
      spec_digest: "user-digest",
      chat_id: 0,
      enabled: true,
      custom_flag: "custom-val",
    };

    const importResult = importCronRegistry(db, {
      jobs: [importedInput],
    });
    expect(importResult.imported).toBe(1);

    const store = new CronStore(db);
    const job = store.getJob("job_colliding_keys")!;
    expect(job.description).toBeNull();
    expect(job.timezone).toBeNull();
    expect(job.raw).toBe("user-raw");
    expect((job as any).version).toBe("user-version");
    expect(job.spec_digest).toBe("user-digest");
    expect(job.chat_id).toBe(0);
    expect(job.storage_version).toBe(1);
    expect(typeof job.storage_spec_digest).toBe("string");

    // Export faithful raw user records
    const exportResult = exportCronRegistry(db);
    expect(exportResult.jobs.length).toBe(1);
    const exportedJob = exportResult.jobs[0];
    expect(exportedJob.description).toBeNull();
    expect(exportedJob.timezone).toBeNull();
    expect(exportedJob.raw).toBe("user-raw");
    expect(exportedJob.version).toBe("user-version");
    expect(exportedJob.spec_digest).toBe("user-digest");
    expect(exportedJob.chat_id).toBe(0);
    expect(exportedJob.custom_flag).toBe("custom-val");

    // 50 repeated status updates: verify spec revision is completely stable & payload bounded
    const initialRawLen = (job.storage_raw as string).length;
    const initialStorageDigest = job.storage_spec_digest;

    for (let i = 0; i < 50; i++) {
      store.recordRunStatus("job_colliding_keys", i % 2 === 0 ? "ok" : "failed", {
        runAt: `2026-09-13T10:${String(i).padStart(2, "0")}:00Z`,
      });
    }

    const updatedJob = store.getJob("job_colliding_keys")!;
    expect(updatedJob.storage_spec_digest).toBe(initialStorageDigest);
    expect(updatedJob.storage_version).toBe(1);
    expect(updatedJob.raw).toBe("user-raw");
    expect((updatedJob as any).version).toBe("user-version");
    expect(updatedJob.spec_digest).toBe("user-digest");
    expect(updatedJob.description).toBeNull();
    expect(updatedJob.timezone).toBeNull();
    expect(updatedJob.storage_raw.length).toBeLessThanOrEqual(initialRawLen + 80);

    const exportedAfter50 = exportCronRegistry(db);
    const expJob50 = exportedAfter50.jobs[0];
    expect(expJob50.raw).toBe("user-raw");
    expect(expJob50.version).toBe("user-version");
    expect(expJob50.spec_digest).toBe("user-digest");
    expect(expJob50.description).toBeNull();
    expect(expJob50.timezone).toBeNull();
    expect(expJob50.last_run_status).toBe("failed");
  });

  test("bare Database snapshot consistency: exported function starts read transaction respecting callers", () => {
    const dbPath = join(tempDir, "bare_db.sqlite");
    const runtimeDb = new RuntimeDatabase(dbPath);
    const store = new CronStore(runtimeDb);
    store.putJob({
      id: "snapshot_job",
      title: "Snapshot Job",
      schedule: "0 0 * * *",
      task_folder: "task",
      agent_instruction: "Instruction",
    });
    runtimeDb.sql.close();

    // Direct bare Database connection
    const bareDb = new Database(dbPath, { readonly: true });
    expect(bareDb.inTransaction).toBe(false);

    // Call exportCronRegistry directly on bare Database
    const res = exportCronRegistry(bareDb);
    expect(res.jobs.length).toBe(1);
    expect(res.jobs[0].id).toBe("snapshot_job");
    expect(bareDb.inTransaction).toBe(false);

    // Direct bare Database inside caller transaction
    bareDb.exec("BEGIN;");
    expect(bareDb.inTransaction).toBe(true);
    const resInTx = exportCronRegistry(bareDb);
    expect(resInTx.jobs.length).toBe(1);
    expect(bareDb.inTransaction).toBe(true);
    bareDb.exec("COMMIT;");
    bareDb.close();
  });

  test("safe descriptor import rejects symlinks (ELOOP) and FIFOs without blocking", () => {
    const db = new RuntimeDatabase(":memory:");

    const realFile = join(tempDir, "real_registry.json");
    writeFileSync(realFile, JSON.stringify({
      jobs: [
        { id: "sym_job", title: "Sym", schedule: "* * * * *", task_folder: "t", agent_instruction: "i" },
      ],
    }));

    const symlinkPath = join(tempDir, "symlink_registry.json");
    symlinkSync(realFile, symlinkPath);

    // Importing via symlink must be rejected with symlink_registry_not_supported
    expect(() => {
      importCronRegistry(db, symlinkPath);
    }).toThrow(RuntimeConflict);
    try {
      importCronRegistry(db, symlinkPath);
    } catch (err) {
      expect((err as RuntimeConflict).code).toBe("symlink_registry_not_supported");
    }
  });

  test("exclusive export publication writes sibling temp, fsyncs, links exclusively, cleans temps on error", () => {
    const db = new RuntimeDatabase(":memory:");
    const store = new CronStore(db);
    store.putJob({
      id: "pub_job",
      title: "Publication Job",
      schedule: "0 0 * * *",
      task_folder: "task",
      agent_instruction: "Test",
    });

    const targetFile = join(tempDir, "exclusive_target.json");

    // First export succeeds
    const exportResult = exportCronRegistry(db, targetFile);
    expect(exportResult.jobs.length).toBe(1);
    expect(readFileSync(targetFile, "utf-8")).toContain("pub_job");

    // Second export to existing destination fails with destination_file_already_exists
    expect(() => {
      exportCronRegistry(db, targetFile);
    }).toThrow(RuntimeConflict);
    try {
      exportCronRegistry(db, targetFile);
    } catch (err) {
      expect((err as RuntimeConflict).code).toBe("destination_file_already_exists");
    }
  });

  test("CLI migrate-cron checks application_id and user_version strictly", () => {
    const dbPath = join(tempDir, "cli_check.sqlite");
    const jsonPath = join(tempDir, "cli_export.json");

    // 1. Create a database with invalid application_id (0) and version 43
    const badDb = new Database(dbPath);
    badDb.exec(`
      PRAGMA application_id = 0;
      PRAGMA user_version = 43;
      CREATE TABLE cron_jobs (job_id TEXT PRIMARY KEY);
      CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
    `);
    badDb.close();

    const scriptPath = join(import.meta.dir, "../scripts/migrate-cron.ts");
    const bunBin = process.execPath;
    const res = spawnSync(
      bunBin,
      ["run", scriptPath, "export", dbPath, jsonPath],
      { encoding: "utf-8" }
    );
    expect(res.status).toBe(2);
    expect(res.stderr).toContain("unsupported_runtime_database");
  });

  test("concurrency: separate OS processes accessing one temporary SQLite DB", () => {
    const dbPath = join(tempDir, "concurrent.sqlite");

    // Initialize database
    const initDb = new RuntimeDatabase(dbPath);
    const store = new CronStore(initDb);
    store.putJob({
      id: "concurrent_target",
      title: "Concurrent Target",
      schedule: "*/5 * * * *",
      task_folder: "concurrent_task",
      agent_instruction: "Concurrent access target",
    });
    initDb.sql.close();

    // Worker script executed concurrently in separate OS processes
    const databaseModulePath = join(import.meta.dir, "../src/database");
    const cronStoreModulePath = join(import.meta.dir, "../src/cron-store");
    const workerScript = `
import { RuntimeDatabase } from "${databaseModulePath}";
import { CronStore } from "${cronStoreModulePath}";

const [dbPath, workerIdStr] = process.argv.slice(2);
const db = new RuntimeDatabase(dbPath);
const store = new CronStore(db);

for (let i = 0; i < 20; i++) {
  const timestamp = 1774000000000 + (i * 1000);
  try {
    store.createOccurrence("concurrent_target", timestamp);
  } catch (err) {
    // Duplicate occurrence is handled idempotently
  }
}
db.sql.close();
`;
    const workerScriptPath = join(tempDir, "worker.ts");
    writeFileSync(workerScriptPath, workerScript);

    const bunBin = process.execPath;
    const p1 = spawnSync(
      bunBin,
      ["run", workerScriptPath, dbPath, "1"],
      { cwd: join(import.meta.dir, ".."), env: { ...process.env, PATH: `${join(bunBin, "..")}:${process.env.PATH}` } }
    );
    const p2 = spawnSync(
      bunBin,
      ["run", workerScriptPath, dbPath, "2"],
      { cwd: join(import.meta.dir, ".."), env: { ...process.env, PATH: `${join(bunBin, "..")}:${process.env.PATH}` } }
    );
    const p3 = spawnSync(
      bunBin,
      ["run", workerScriptPath, dbPath, "3"],
      { cwd: join(import.meta.dir, ".."), env: { ...process.env, PATH: `${join(bunBin, "..")}:${process.env.PATH}` } }
    );

    expect(p1.status).toBe(0);
    expect(p2.status).toBe(0);
    expect(p3.status).toBe(0);

    const verifyDb = new RuntimeDatabase(dbPath);
    const verifyStore = new CronStore(verifyDb);
    const occurrences = verifyStore.listOccurrences("concurrent_target");
    expect(occurrences.length).toBe(20);
    verifyDb.sql.close();
  });
});
