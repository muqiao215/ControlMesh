/**
 * Cron Registry, Stable Occurrence Engine, and Fenced Attempt Store
 *
 * Provides typed persistence for ControlMesh cron jobs in SQLite (Migration 43).
 *
 * CORRECTNESS GUARANTEES (REVIEW 3 REPAIRED):
 * 1. Single-Coordinator Fencing: Exactly one authoritative coordinator per database.
 *    getCoordinatorEpoch is strictly read-only and fails if unregistered.
 *    Explicit bootstrap mutation (registerCoordinator). Transitions and rotations require
 *    the expected currently issued epoch.
 * 2. Failover Recovery Reconciliation: Current controller authority is separated from
 *    the expected old attempt identity/fence. Reconciling unverified outcome retains ownership;
 *    verified completion releases the lock without rerunning or replacing terminal results.
 * 3. Stable Occurrence Identity: Decoupled from coordinator incarnations/fencing.
 *    Immutable definition changes at the same timestamp explicitly reject.
 * 4. Terminal & Uncertain Replay Prevention: Occurrences and attempts cannot transition
 *    out of terminal states ('completed', 'failed'). New attempts cannot be started on
 *    terminal or uncertain occurrences.
 * 5. Lossless Representation: Exact user/imported JSON is preserved separately from
 *    normalized execution fields. Legitimate user keys (including colliding names like 'raw',
 *    'version', 'spec_digest') are never stripped. Null, empty string, 0, and missing are
 *    faithfully distinguished. BigInt (> 2^53) is preserved.
 * 6. Internal Storage Separation: Status updates patch stored user input directly,
 *    preventing internal-field recursion and ensuring bounded payload growth across repeated updates.
 */

import { createHash } from "node:crypto";
import type { RuntimeDatabase } from "./database";
import { identifier, object, requireThat, RuntimeConflict } from "./value";

export const MAX_REGISTRY_BYTES = 16 * 1024 * 1024; // 16MB

// ----------------------------------------------------------------------------
// Lossless JSON Codec (BigInt Preservation & Depth Checking)
// ----------------------------------------------------------------------------

export function parseLosslessJson(text: string): unknown {
  requireThat(typeof text === "string", "invalid_json_text");
  requireThat(Buffer.byteLength(text) <= MAX_REGISTRY_BYTES, "registry_too_large");
  const parse = JSON.parse as (
    text: string,
    reviver: (key: string, value: unknown, context?: { source?: string }) => unknown
  ) => unknown;
  return parse(text, (_key, value, context) => {
    if (typeof value === "number" && Number.isInteger(value) && !Number.isSafeInteger(value)) {
      requireThat(
        typeof context?.source === "string" && /^-?\d+$/.test(context.source) && context.source.length <= 4096,
        "unsafe_json_integer"
      );
      return BigInt(context.source);
    }
    return value;
  });
}

export function losslessJsonStringify(value: unknown, indent?: number, depth = 0): string {
  requireThat(depth <= 64, "json_depth_exceeded");
  if (typeof value === "bigint") {
    const raw = value.toString();
    requireThat(raw.length <= 4096, "integer_too_large");
    return raw;
  }
  if (value === null || typeof value === "string" || typeof value === "boolean") {
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    requireThat(Number.isFinite(value), "invalid_json_value");
    if (Number.isInteger(value) && !Number.isSafeInteger(value)) {
      throw new RuntimeConflict("unsafe_json_integer");
    }
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    const items = value.map(item => losslessJsonStringify(item, indent, depth + 1));
    if (indent && indent > 0) {
      const space = " ".repeat(indent * (depth + 1));
      const closeSpace = " ".repeat(indent * depth);
      return `[\n${items.map(it => `${space}${it}`).join(",\n")}\n${closeSpace}]`;
    }
    return `[${items.join(",")}]`;
  }
  if (object(value)) {
    const keys = Object.keys(value).sort();
    const pairs = keys.map(k => {
      const formattedVal = losslessJsonStringify(value[k], indent, depth + 1);
      return indent && indent > 0
        ? `${JSON.stringify(k)}: ${formattedVal}`
        : `${JSON.stringify(k)}:${formattedVal}`;
    });
    if (indent && indent > 0) {
      const space = " ".repeat(indent * (depth + 1));
      const closeSpace = " ".repeat(indent * depth);
      return `{\n${pairs.map(p => `${space}${p}`).join(",\n")}\n${closeSpace}}`;
    }
    return `{${pairs.join(",")}}`;
  }
  throw new RuntimeConflict("invalid_json_value");
}

function digestLossless(value: unknown): string {
  return createHash("sha256").update(losslessJsonStringify(value)).digest("hex");
}

// ----------------------------------------------------------------------------
// Type Definitions
// ----------------------------------------------------------------------------

export interface CronJobInput {
  id: string;
  title: string;
  schedule: string;
  task_folder: string;
  agent_instruction: string;
  description?: string | null;
  enabled?: boolean;
  timezone?: string | null;
  created_at?: string | null;
  last_run_at?: string | null;
  last_run_status?: string | null;
  manual_run_at?: string | null;
  manual_run_status?: string | null;
  provider?: string | null;
  model?: string | null;
  reasoning_effort?: string | null;
  cli_parameters?: readonly string[];
  quiet_start?: number | null;
  quiet_end?: number | null;
  dependency?: string | null;
  job_kind?: string;
  execution_mode?: string;
  workunit_kind?: string | null;
  risk?: string | null;
  output_policy?: string | null;
  chat_id?: number | bigint | string;
  topic_id?: number | bigint | string | null;
  transport?: string;
  controller_grant?: string | null;
  [unknownKey: string]: unknown;
}

export interface CronJobRecord {
  id: string;
  title: string;
  description: string;
  schedule: string;
  task_folder: string;
  agent_instruction: string;
  enabled: boolean;
  timezone: string;
  created_at: string;
  last_run_at: string | null;
  last_run_status: string | null;
  manual_run_at: string | null;
  manual_run_status: string | null;
  provider: string | null;
  model: string | null;
  reasoning_effort: string | null;
  cli_parameters: readonly string[];
  quiet_start: number | null;
  quiet_end: number | null;
  dependency: string | null;
  job_kind: string;
  execution_mode: string;
  workunit_kind: string | null;
  risk: string | null;
  output_policy: string | null;
  chat_id: number | bigint;
  topic_id: number | bigint | null;
  transport: string;
  controller_grant: string | null;

  // Storage bookkeeping
  storage_version: number;
  storage_spec_digest: string;
  storage_raw: string;
  storage_archived: boolean;
  archived: boolean;
  archived_at: number | null;

  // Exact user record (preserving user keys, nulls, and unknown fields)
  raw_metadata: Record<string, unknown>;

  // Backwards compatibility properties
  version: number | string;
  spec_digest: string;
  raw: string;
  [unknownKey: string]: unknown;
}

export type CronOccurrenceState =
  | "scheduled"
  | "enqueued"
  | "running"
  | "cancelling"
  | "completed"
  | "failed"
  | "skipped_quiet"
  | "skipped_duplicate"
  | "circuit_broken"
  | "blocked_unknown";

export interface CronOccurrenceRecord {
  occurrence_id: string;
  job_id: string;
  schedule_revision: number;
  scheduled_at: number;
  definition_digest: string;
  state: CronOccurrenceState;
  created_at: number;
}

export type CronAttemptState =
  | "initiated"
  | "running"
  | "cancelling"
  | "completed"
  | "failed"
  | "uncertain";

export interface CronExecutionAttemptRecord {
  attempt_id: string;
  occurrence_id: string;
  attempt_number: number;
  fencing_generation: number;
  coordinator_id: string;
  executor_device_id: string;
  state: CronAttemptState;
  task_id: string | null;
  started_at: number;
  finished_at: number | null;
  result_status: string | null;
  result_summary: string | null;
  error_details: string | null;
}

export interface CronDependencyLockRecord {
  dependency: string;
  active_occurrence_id: string;
  active_attempt_id: string;
  acquired_at: number;
  lease_deadline: number;
  status: "locked" | "uncertain";
}

export interface CoordinatorEpochRecord {
  coordinator_id: string;
  current_generation: number;
  fence_token: string;
  updated_at: number;
}

/** Compute the canonical execution definition digest for a cron job. */
export function computeJobSpecDigest(job: Record<string, unknown>): string {
  const {
    last_run_at: _lra,
    last_run_status: _lrs,
    manual_run_at: _mra,
    manual_run_status: _mrs,
    created_at: _ca,
    enabled: _en,
    ...spec
  } = job;
  return digestLossless(spec);
}

// ----------------------------------------------------------------------------
// CronStore Class
// ----------------------------------------------------------------------------

export class CronStore {
  constructor(readonly db: RuntimeDatabase) {}

  // --------------------------------------------------------------------------
  // Job Registry CRUD
  // --------------------------------------------------------------------------

  listJobs(options?: { includeArchived?: boolean }): readonly CronJobRecord[] {
    const where = options?.includeArchived ? "" : "WHERE archived = 0";
    const rows = this.db.sql.query(`SELECT * FROM cron_jobs ${where} ORDER BY job_id ASC`).all() as any[];
    return rows.map(r => this.hydrateJob(r));
  }

  getJob(id: string, options?: { includeArchived?: boolean }): CronJobRecord | null {
    identifier(id);
    const where = options?.includeArchived ? "WHERE job_id = ?" : "WHERE job_id = ? AND archived = 0";
    const row = this.db.sql.query(`SELECT * FROM cron_jobs ${where}`).get(id) as any | null;
    return row ? this.hydrateJob(row) : null;
  }

  putJob(input: CronJobInput, options?: { replace?: boolean }): CronJobRecord {
    requireThat(object(input), "invalid_cron_job");
    identifier(input.id);
    requireThat(typeof input.title === "string" && input.title.trim().length > 0, "invalid_job_title");
    requireThat(typeof input.schedule === "string" && input.schedule.trim().length > 0, "invalid_job_schedule");
    requireThat(typeof input.task_folder === "string" && input.task_folder.trim().length > 0, "invalid_task_folder");
    requireThat(typeof input.agent_instruction === "string" && input.agent_instruction.trim().length > 0, "invalid_agent_instruction");

    return this.db.transaction(() => {
      // Look up existing job (including archived to detect recreation/restoration)
      const existing = this.getJob(input.id, { includeArchived: true });

      const userCleanInput = { ...input };

      // When replace is requested or no prior record exists, do not merge onto prior user metadata
      const mergedUserMetadata: Record<string, unknown> = (options?.replace || !existing)
        ? { ...userCleanInput }
        : {
            ...existing.raw_metadata,
            ...userCleanInput,
          };

      // Extract normalized values for SQLite columns
      const id = input.id;
      const title = input.title;
      const description = typeof mergedUserMetadata.description === "string"
        ? mergedUserMetadata.description
        : "";
      const schedule = input.schedule;
      const taskFolder = input.task_folder;
      const agentInstruction = input.agent_instruction;
      const enabled = mergedUserMetadata.enabled !== undefined
        ? Boolean(mergedUserMetadata.enabled)
        : true;
      const timezone = typeof mergedUserMetadata.timezone === "string"
        ? mergedUserMetadata.timezone
        : "";
      const createdAt = typeof mergedUserMetadata.created_at === "string" && mergedUserMetadata.created_at.length > 0
        ? mergedUserMetadata.created_at
        : new Date(this.db.now()).toISOString();

      const lastRunAt = mergedUserMetadata.last_run_at != null ? String(mergedUserMetadata.last_run_at) : null;
      const lastRunStatus = mergedUserMetadata.last_run_status != null ? String(mergedUserMetadata.last_run_status) : null;
      const manualRunAt = mergedUserMetadata.manual_run_at != null ? String(mergedUserMetadata.manual_run_at) : null;
      const manualRunStatus = mergedUserMetadata.manual_run_status != null ? String(mergedUserMetadata.manual_run_status) : null;

      const provider = mergedUserMetadata.provider != null ? String(mergedUserMetadata.provider) : null;
      const model = mergedUserMetadata.model != null ? String(mergedUserMetadata.model) : null;
      const reasoningEffort = mergedUserMetadata.reasoning_effort != null ? String(mergedUserMetadata.reasoning_effort) : null;
      const cliParameters = Array.isArray(mergedUserMetadata.cli_parameters)
        ? mergedUserMetadata.cli_parameters.map(String)
        : [];

      let quietStart: number | null = null;
      if (mergedUserMetadata.quiet_start != null) {
        const qs = Number(mergedUserMetadata.quiet_start);
        requireThat(Number.isInteger(qs) && qs >= 0 && qs <= 23, "invalid_quiet_start");
        quietStart = qs;
      }

      let quietEnd: number | null = null;
      if (mergedUserMetadata.quiet_end != null) {
        const qe = Number(mergedUserMetadata.quiet_end);
        requireThat(Number.isInteger(qe) && qe >= 0 && qe <= 23, "invalid_quiet_end");
        quietEnd = qe;
      }

      const dependency = mergedUserMetadata.dependency != null ? String(mergedUserMetadata.dependency) : null;
      const jobKind = typeof mergedUserMetadata.job_kind === "string"
        ? mergedUserMetadata.job_kind
        : "recurring";
      const executionMode = typeof mergedUserMetadata.execution_mode === "string"
        ? mergedUserMetadata.execution_mode
        : "oneshot";
      const workunitKind = mergedUserMetadata.workunit_kind != null ? String(mergedUserMetadata.workunit_kind) : null;
      const risk = mergedUserMetadata.risk != null ? String(mergedUserMetadata.risk) : null;
      const outputPolicy = mergedUserMetadata.output_policy != null ? String(mergedUserMetadata.output_policy) : null;

      let chatId: number | bigint = 0;
      if (mergedUserMetadata.chat_id !== undefined) {
        if (typeof mergedUserMetadata.chat_id === "bigint" || typeof mergedUserMetadata.chat_id === "number") {
          chatId = mergedUserMetadata.chat_id;
        } else if (typeof mergedUserMetadata.chat_id === "string" && /^-?\d+$/.test(mergedUserMetadata.chat_id)) {
          const parsed = BigInt(mergedUserMetadata.chat_id);
          chatId = (parsed >= BigInt(Number.MIN_SAFE_INTEGER) && parsed <= BigInt(Number.MAX_SAFE_INTEGER))
            ? Number(parsed)
            : parsed;
        } else {
          throw new RuntimeConflict("invalid_chat_id");
        }
      }

      let topicId: number | bigint | null = null;
      if (mergedUserMetadata.topic_id !== undefined && mergedUserMetadata.topic_id !== null) {
        if (typeof mergedUserMetadata.topic_id === "bigint" || typeof mergedUserMetadata.topic_id === "number") {
          topicId = mergedUserMetadata.topic_id;
        } else if (typeof mergedUserMetadata.topic_id === "string" && /^-?\d+$/.test(mergedUserMetadata.topic_id)) {
          const parsed = BigInt(mergedUserMetadata.topic_id);
          topicId = (parsed >= BigInt(Number.MIN_SAFE_INTEGER) && parsed <= BigInt(Number.MAX_SAFE_INTEGER))
            ? Number(parsed)
            : parsed;
        } else {
          throw new RuntimeConflict("invalid_topic_id");
        }
      }

      const transport = typeof mergedUserMetadata.transport === "string"
        ? mergedUserMetadata.transport
        : "tg";
      const controllerGrant = mergedUserMetadata.controller_grant != null ? String(mergedUserMetadata.controller_grant) : null;

      const specDigest = computeJobSpecDigest(mergedUserMetadata);

      let version = 1;
      if (existing) {
        if (existing.storage_archived) {
          // Explicit recreation/restoration of an archived job MUST use a new definition revision
          version = existing.storage_version + 1;
        } else {
          version = existing.storage_spec_digest === specDigest ? existing.storage_version : existing.storage_version + 1;
        }
      }

      // Serialize user metadata losslessly (preserving user keys without injection)
      const rawJson = losslessJsonStringify(mergedUserMetadata);

      this.db.sql.query(`
        INSERT INTO cron_jobs (
          job_id, title, description, schedule, task_folder, agent_instruction,
          enabled, timezone, created_at, last_run_at, last_run_status, manual_run_at, manual_run_status,
          provider, model, reasoning_effort, cli_parameters, quiet_start, quiet_end,
          dependency, job_kind, execution_mode, workunit_kind, risk, output_policy,
          chat_id, topic_id, transport, spec_digest, controller_grant, version, raw,
          archived, archived_at
        ) VALUES (
          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL
        )
        ON CONFLICT(job_id) DO UPDATE SET
          title = excluded.title,
          description = excluded.description,
          schedule = excluded.schedule,
          task_folder = excluded.task_folder,
          agent_instruction = excluded.agent_instruction,
          enabled = excluded.enabled,
          timezone = excluded.timezone,
          created_at = excluded.created_at,
          last_run_at = excluded.last_run_at,
          last_run_status = excluded.last_run_status,
          manual_run_at = excluded.manual_run_at,
          manual_run_status = excluded.manual_run_status,
          provider = excluded.provider,
          model = excluded.model,
          reasoning_effort = excluded.reasoning_effort,
          cli_parameters = excluded.cli_parameters,
          quiet_start = excluded.quiet_start,
          quiet_end = excluded.quiet_end,
          dependency = excluded.dependency,
          job_kind = excluded.job_kind,
          execution_mode = excluded.execution_mode,
          workunit_kind = excluded.workunit_kind,
          risk = excluded.risk,
          output_policy = excluded.output_policy,
          chat_id = excluded.chat_id,
          topic_id = excluded.topic_id,
          transport = excluded.transport,
          spec_digest = excluded.spec_digest,
          controller_grant = excluded.controller_grant,
          version = excluded.version,
          raw = excluded.raw,
          archived = 0,
          archived_at = NULL
      `).run(
        id,
        title,
        description,
        schedule,
        taskFolder,
        agentInstruction,
        enabled ? 1 : 0,
        timezone,
        createdAt,
        lastRunAt,
        lastRunStatus,
        manualRunAt,
        manualRunStatus,
        provider,
        model,
        reasoningEffort,
        JSON.stringify(cliParameters),
        quietStart,
        quietEnd,
        dependency,
        jobKind,
        executionMode,
        workunitKind,
        risk,
        outputPolicy,
        typeof chatId === "bigint" ? chatId.toString() : chatId,
        topicId !== null ? (typeof topicId === "bigint" ? topicId.toString() : topicId) : null,
        transport,
        specDigest,
        controllerGrant,
        version,
        rawJson
      );

      return this.getJob(input.id)!;
    });
  }

  archiveJob(id: string): boolean {
    identifier(id);
    return this.db.transaction(() => {
      const row = this.db.sql.query(
        "SELECT archived FROM cron_jobs WHERE job_id = ?"
      ).get(id) as { archived: number } | null;
      if (!row || row.archived === 1) return false;
      const now = this.db.now();
      this.db.sql.query(
        "UPDATE cron_jobs SET archived = 1, archived_at = ? WHERE job_id = ?"
      ).run(now, id);
      return true;
    });
  }

  removeJob(id: string): boolean {
    return this.archiveJob(id);
  }

  restoreJob(id: string): CronJobRecord {
    identifier(id);
    return this.db.transaction(() => {
      const row = this.db.sql.query(
        "SELECT * FROM cron_jobs WHERE job_id = ?"
      ).get(id) as any | null;
      requireThat(row, "cron_job_not_found");
      requireThat(row.archived === 1, "cron_job_already_active");

      const nextVersion = Number(row.version) + 1;
      this.db.sql.query(`
        UPDATE cron_jobs SET
          archived = 0,
          archived_at = NULL,
          version = ?
        WHERE job_id = ?
      `).run(nextVersion, id);

      return this.getJob(id)!;
    });
  }

  setEnabled(id: string, enabled: boolean): boolean {
    identifier(id);
    return this.db.transaction(() => {
      const row = this.db.sql.query("SELECT * FROM cron_jobs WHERE job_id = ? AND archived = 0").get(id) as any | null;
      if (!row) return false;
      const currentEnabled = Boolean(row.enabled);
      if (currentEnabled === enabled) return false;

      // Patch stored user input directly; do not invoke putJob({...hydratedRecord})
      const userObj = parseLosslessJson(row.raw) as Record<string, unknown>;
      userObj.enabled = enabled;

      this.db.sql.query(
        "UPDATE cron_jobs SET enabled = ?, raw = ? WHERE job_id = ?"
      ).run(enabled ? 1 : 0, losslessJsonStringify(userObj), id);
      return true;
    });
  }

  setAllEnabled(enabled: boolean): number {
    return this.db.transaction(() => {
      const jobs = this.listJobs();
      let changed = 0;
      for (const job of jobs) {
        if (this.setEnabled(job.id, enabled)) {
          changed++;
        }
      }
      return changed;
    });
  }

  recordRunStatus(id: string, status: string, options?: { manual?: boolean; runAt?: string }): void {
    identifier(id);
    this.db.transaction(() => {
      const row = this.db.sql.query("SELECT * FROM cron_jobs WHERE job_id = ? AND archived = 0").get(id) as any | null;
      requireThat(row, "cron_job_not_found");

      // Patch stored user input directly; do not invoke putJob({...hydratedRecord})
      const userObj = parseLosslessJson(row.raw) as Record<string, unknown>;
      const timestamp = options?.runAt ?? new Date(this.db.now()).toISOString();

      if (options?.manual) {
        userObj.manual_run_status = status;
        userObj.manual_run_at = timestamp;
        this.db.sql.query(
          "UPDATE cron_jobs SET manual_run_status = ?, manual_run_at = ?, raw = ? WHERE job_id = ?"
        ).run(status, timestamp, losslessJsonStringify(userObj), id);
      } else {
        userObj.last_run_status = status;
        userObj.last_run_at = timestamp;
        this.db.sql.query(
          "UPDATE cron_jobs SET last_run_status = ?, last_run_at = ?, raw = ? WHERE job_id = ?"
        ).run(status, timestamp, losslessJsonStringify(userObj), id);
      }
    });
  }

  private hydrateJob(row: any): CronJobRecord {
    let parsedRaw: Record<string, unknown>;
    try {
      parsedRaw = parseLosslessJson(row.raw) as Record<string, unknown>;
      requireThat(object(parsedRaw), "corrupt_raw");
    } catch {
      throw new RuntimeConflict("corrupt_stored_metadata");
    }

    let chatId: number | bigint = 0;
    if (parsedRaw.chat_id !== undefined && (typeof parsedRaw.chat_id === "bigint" || typeof parsedRaw.chat_id === "number")) {
      chatId = parsedRaw.chat_id;
    } else if (typeof row.chat_id === "string" && /^-?\d+$/.test(row.chat_id)) {
      const b = BigInt(row.chat_id);
      chatId = (b >= BigInt(Number.MIN_SAFE_INTEGER) && b <= BigInt(Number.MAX_SAFE_INTEGER)) ? Number(b) : b;
    } else {
      chatId = Number(row.chat_id ?? 0);
    }

    let topicId: number | bigint | null = null;
    if (parsedRaw.topic_id !== undefined && (typeof parsedRaw.topic_id === "bigint" || typeof parsedRaw.topic_id === "number" || parsedRaw.topic_id === null)) {
      topicId = parsedRaw.topic_id;
    } else if (row.topic_id !== null && row.topic_id !== undefined) {
      if (typeof row.topic_id === "string" && /^-?\d+$/.test(row.topic_id)) {
        const b = BigInt(row.topic_id);
        topicId = (b >= BigInt(Number.MIN_SAFE_INTEGER) && b <= BigInt(Number.MAX_SAFE_INTEGER)) ? Number(b) : b;
      } else {
        topicId = Number(row.topic_id);
      }
    }

    const record: any = {
      id: row.job_id,
      title: row.title,
      description: row.description,
      schedule: row.schedule,
      task_folder: row.task_folder,
      agent_instruction: row.agent_instruction,
      enabled: Boolean(row.enabled),
      timezone: row.timezone ?? "",
      created_at: row.created_at,
      last_run_at: row.last_run_at,
      last_run_status: row.last_run_status,
      manual_run_at: row.manual_run_at,
      manual_run_status: row.manual_run_status,
      provider: row.provider,
      model: row.model,
      reasoning_effort: row.reasoning_effort,
      cli_parameters: JSON.parse(row.cli_parameters || "[]"),
      quiet_start: row.quiet_start !== null && row.quiet_start !== undefined ? Number(row.quiet_start) : null,
      quiet_end: row.quiet_end !== null && row.quiet_end !== undefined ? Number(row.quiet_end) : null,
      dependency: row.dependency,
      job_kind: row.job_kind,
      execution_mode: row.execution_mode,
      workunit_kind: row.workunit_kind,
      risk: row.risk,
      output_policy: row.output_policy,
      chat_id: chatId,
      topic_id: topicId,
      transport: row.transport,
      controller_grant: row.controller_grant,

      // Default compatibility properties if not present in parsedRaw
      version: Number(row.version),
      spec_digest: row.spec_digest,
      raw: row.raw,
      archived: Boolean(row.archived),
      archived_at: row.archived_at !== null && row.archived_at !== undefined ? Number(row.archived_at) : null,

      // Exact user properties win over defaults
      ...parsedRaw,
    };

    // Storage-specific bookkeeping attached as non-enumerable properties
    Object.defineProperties(record, {
      storage_version: { value: Number(row.version), enumerable: false, writable: false },
      storage_spec_digest: { value: row.spec_digest, enumerable: false, writable: false },
      storage_raw: { value: row.raw, enumerable: false, writable: false },
      storage_archived: { value: Boolean(row.archived), enumerable: false, writable: false },
      raw_metadata: { value: parsedRaw, enumerable: false, writable: false },
    });

    return record as CronJobRecord;
  }

  // --------------------------------------------------------------------------
  // Stable Scheduled Occurrence Engine
  // --------------------------------------------------------------------------

  createOccurrence(jobId: string, scheduledAt: number): CronOccurrenceRecord {
    identifier(jobId);
    requireThat(Number.isSafeInteger(scheduledAt) && scheduledAt > 0, "invalid_scheduled_timestamp");

    const job = this.getJob(jobId);
    requireThat(job, "cron_job_not_found");

    return this.registerOccurrence({
      jobId,
      scheduledAt,
      scheduleRevision: job.storage_version,
      definitionDigest: job.storage_spec_digest,
    });
  }

  registerOccurrence(input: {
    jobId: string;
    scheduledAt: number;
    scheduleRevision: number;
    definitionDigest: string;
  }): CronOccurrenceRecord {
    identifier(input.jobId);
    requireThat(Number.isSafeInteger(input.scheduledAt) && input.scheduledAt > 0, "invalid_scheduled_timestamp");
    requireThat(Number.isSafeInteger(input.scheduleRevision) && input.scheduleRevision > 0, "invalid_schedule_revision");
    requireThat(typeof input.definitionDigest === "string" && input.definitionDigest.length === 64, "invalid_definition_digest");

    return this.db.transaction(() => {
      const existing = this.db.sql.query(
        "SELECT * FROM cron_occurrences WHERE job_id = ? AND scheduled_at = ?"
      ).get(input.jobId, input.scheduledAt) as any | null;

      if (existing) {
        if (
          existing.schedule_revision !== input.scheduleRevision ||
          existing.definition_digest !== input.definitionDigest
        ) {
          throw new RuntimeConflict("occurrence_definition_conflict");
        }
        return this.hydrateOccurrence(existing);
      }

      // Stable occurrence ID formula: decoupled from fencing tokens or leader epochs
      const occurrenceId = digestLossless([
        "cron_occurrence",
        input.jobId,
        input.scheduleRevision,
        input.scheduledAt,
      ]);

      const now = this.db.now();
      this.db.sql.query(`
        INSERT INTO cron_occurrences (
          occurrence_id, job_id, schedule_revision, scheduled_at, definition_digest, state, created_at
        ) VALUES (?, ?, ?, ?, ?, 'scheduled', ?)
      `).run(occurrenceId, input.jobId, input.scheduleRevision, input.scheduledAt, input.definitionDigest, now);

      const created = this.db.sql.query(
        "SELECT * FROM cron_occurrences WHERE occurrence_id = ?"
      ).get(occurrenceId) as any;

      return this.hydrateOccurrence(created);
    });
  }

  getOccurrence(occurrenceId: string): CronOccurrenceRecord | null {
    const row = this.db.sql.query("SELECT * FROM cron_occurrences WHERE occurrence_id = ?").get(occurrenceId) as any | null;
    return row ? this.hydrateOccurrence(row) : null;
  }

  getOccurrenceBySlot(jobId: string, scheduledAt: number): CronOccurrenceRecord | null {
    identifier(jobId);
    const row = this.db.sql.query("SELECT * FROM cron_occurrences WHERE job_id = ? AND scheduled_at = ?").get(jobId, scheduledAt) as any | null;
    return row ? this.hydrateOccurrence(row) : null;
  }

  listOccurrences(jobId?: string): readonly CronOccurrenceRecord[] {
    if (jobId) {
      identifier(jobId);
      const rows = this.db.sql.query(
        "SELECT * FROM cron_occurrences WHERE job_id = ? ORDER BY scheduled_at ASC"
      ).all(jobId) as any[];
      return rows.map(r => this.hydrateOccurrence(r));
    }
    const rows = this.db.sql.query(
      "SELECT * FROM cron_occurrences ORDER BY scheduled_at ASC"
    ).all() as any[];
    return rows.map(r => this.hydrateOccurrence(r));
  }

  private updateOccurrenceStateInternal(occurrenceId: string, nextState: CronOccurrenceState): void {
    const occurrence = this.getOccurrence(occurrenceId);
    requireThat(occurrence, "occurrence_not_found");
    if (occurrence.state === "completed" || occurrence.state === "failed") {
      if (nextState !== occurrence.state) {
        throw new RuntimeConflict("occurrence_already_terminal");
      }
      return;
    }
    this.db.sql.query("UPDATE cron_occurrences SET state = ? WHERE occurrence_id = ?").run(nextState, occurrenceId);
  }

  private hydrateOccurrence(row: any): CronOccurrenceRecord {
    return {
      occurrence_id: row.occurrence_id,
      job_id: row.job_id,
      schedule_revision: Number(row.schedule_revision),
      scheduled_at: Number(row.scheduled_at),
      definition_digest: row.definition_digest,
      state: row.state as CronOccurrenceState,
      created_at: Number(row.created_at),
    };
  }

  // --------------------------------------------------------------------------
  // Fenced Execution Attempts
  // --------------------------------------------------------------------------

  createAttempt(occurrenceId: string, options: {
    coordinatorId: string;
    executorDeviceId: string;
    fencingGeneration: number;
    taskId?: string;
  }): CronExecutionAttemptRecord {
    identifier(options.coordinatorId);
    identifier(options.executorDeviceId);
    requireThat(Number.isSafeInteger(options.fencingGeneration) && options.fencingGeneration > 0, "invalid_fencing_generation");

    return this.db.transaction(() => {
      const occurrence = this.getOccurrence(occurrenceId);
      requireThat(occurrence, "occurrence_not_found");

      // Admission uses current normalized storage, not caller-supplied metadata
      // or the historical occurrence alone. Updates/reconciliation of existing
      // attempts remain available after a job is disabled or archived.
      const definition = this.db.sql.query(
        "SELECT archived, enabled, version, spec_digest FROM cron_jobs WHERE job_id = ?"
      ).get(occurrence.job_id) as { archived: number; enabled: number; version: number; spec_digest: string } | null;
      requireThat(definition && definition.archived === 0 && definition.enabled === 1, "cron_definition_not_active");
      requireThat(definition.version === occurrence.schedule_revision && definition.spec_digest === occurrence.definition_digest,
        "cron_occurrence_definition_changed");

      // 1. Block attempts on terminal occurrences (completed, failed, cancelled, skipped)
      if (
        occurrence.state === "completed" ||
        occurrence.state === "failed" ||
        occurrence.state === "skipped_quiet" ||
        occurrence.state === "skipped_duplicate" ||
        occurrence.state === "circuit_broken"
      ) {
        throw new RuntimeConflict("occurrence_already_terminal");
      }

      // 2. Single-coordinator authority check:
      // Must match currently registered coordinator and exact currently issued generation
      const epoch = this.getCoordinatorEpoch(options.coordinatorId);
      requireThat(options.fencingGeneration === epoch.current_generation, "stale_coordinator_fence");

      // 3. Duplicate suppression must block active AND uncertain attempts!
      const activeOrUncertainAttempts = this.db.sql.query(
        "SELECT attempt_id FROM cron_execution_attempts WHERE occurrence_id = ? AND state IN ('initiated', 'running', 'cancelling', 'uncertain')"
      ).all(occurrenceId) as { attempt_id: string }[];
      requireThat(activeOrUncertainAttempts.length === 0, "active_or_uncertain_attempt_exists");

      const attemptNumberRow = this.db.sql.query(
        "SELECT COALESCE(MAX(attempt_number), 0) + 1 AS next_attempt FROM cron_execution_attempts WHERE occurrence_id = ?"
      ).get(occurrenceId) as { next_attempt: number };
      const attemptNumber = attemptNumberRow.next_attempt;

      const attemptId = digestLossless([
        "cron_attempt",
        occurrenceId,
        attemptNumber,
        options.fencingGeneration,
      ]);

      const now = this.db.now();
      this.db.sql.query(`
        INSERT INTO cron_execution_attempts (
          attempt_id, occurrence_id, attempt_number, fencing_generation, coordinator_id,
          executor_device_id, state, task_id, started_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'initiated', ?, ?)
      `).run(
        attemptId,
        occurrenceId,
        attemptNumber,
        options.fencingGeneration,
        options.coordinatorId,
        options.executorDeviceId,
        options.taskId ?? null,
        now,
      );

      // An initiated attempt is admitted, not proof that a worker has started.
      this.updateOccurrenceStateInternal(occurrenceId, "enqueued");

      const created = this.db.sql.query(
        "SELECT * FROM cron_execution_attempts WHERE attempt_id = ?"
      ).get(attemptId) as any;
      return this.hydrateAttempt(created);
    });
  }

  getAttempt(attemptId: string): CronExecutionAttemptRecord | null {
    const row = this.db.sql.query("SELECT * FROM cron_execution_attempts WHERE attempt_id = ?").get(attemptId) as any | null;
    return row ? this.hydrateAttempt(row) : null;
  }

  listAttempts(occurrenceId: string): readonly CronExecutionAttemptRecord[] {
    const rows = this.db.sql.query(
      "SELECT * FROM cron_execution_attempts WHERE occurrence_id = ? ORDER BY attempt_number ASC"
    ).all(occurrenceId) as any[];
    return rows.map(r => this.hydrateAttempt(r));
  }

  updateAttemptState(attemptId: string, authority: {
    coordinatorId: string;
    fence: number;
  }, updates: {
    state?: CronAttemptState;
    taskId?: string | null;
    resultStatus?: string | null;
    resultSummary?: string | null;
    errorDetails?: string | null;
    finishedAt?: number;
  }): CronExecutionAttemptRecord {
    identifier(authority.coordinatorId);
    requireThat(Number.isSafeInteger(authority.fence) && authority.fence > 0, "invalid_fencing_generation");

    return this.db.transaction(() => {
      const attempt = this.getAttempt(attemptId);
      requireThat(attempt, "attempt_not_found");

      // Verify coordinator epoch and attempt fence
      const epoch = this.getCoordinatorEpoch(authority.coordinatorId);
      requireThat(authority.fence === epoch.current_generation, "stale_coordinator_fence");
      requireThat(attempt.fencing_generation === authority.fence, "stale_attempt_fence");

      // Reject mutating an already terminal attempt
      if (attempt.state === "completed" || attempt.state === "failed") {
        throw new RuntimeConflict("attempt_already_terminal");
      }

      const nextState = updates.state ?? attempt.state;
      const now = this.db.now();
      const finishedAt = updates.finishedAt ?? (
        (nextState === "completed" || nextState === "failed") ? now : attempt.finished_at
      );

      this.db.sql.query(`
        UPDATE cron_execution_attempts SET
          state = ?,
          task_id = COALESCE(?, task_id),
          result_status = COALESCE(?, result_status),
          result_summary = COALESCE(?, result_summary),
          error_details = COALESCE(?, error_details),
          finished_at = ?
        WHERE attempt_id = ?
      `).run(
        nextState,
        updates.taskId ?? null,
        updates.resultStatus ?? null,
        updates.resultSummary ?? null,
        updates.errorDetails ?? null,
        finishedAt,
        attemptId,
      );

      // Worker startup/cancellation and terminal evidence drive occurrence state.
      if (nextState === "running" || nextState === "cancelling") {
        this.updateOccurrenceStateInternal(attempt.occurrence_id, nextState);
      } else if (nextState === "completed") {
        this.updateOccurrenceStateInternal(attempt.occurrence_id, "completed");
      } else if (nextState === "failed") {
        this.updateOccurrenceStateInternal(attempt.occurrence_id, "failed");
      } else if (nextState === "uncertain") {
        this.updateOccurrenceStateInternal(attempt.occurrence_id, "blocked_unknown");
      }

      return this.getAttempt(attemptId)!;
    });
  }

  markAttemptUncertain(attemptId: string, authority: {
    coordinatorId: string;
    fence: number;
  }): CronExecutionAttemptRecord {
    identifier(authority.coordinatorId);
    requireThat(Number.isSafeInteger(authority.fence) && authority.fence > 0, "invalid_fencing_generation");

    return this.db.transaction(() => {
      const attempt = this.getAttempt(attemptId);
      requireThat(attempt, "attempt_not_found");

      const epoch = this.getCoordinatorEpoch(authority.coordinatorId);
      requireThat(authority.fence === epoch.current_generation, "stale_coordinator_fence");
      requireThat(attempt.fencing_generation === authority.fence, "stale_attempt_fence");

      if (attempt.state === "completed" || attempt.state === "failed") {
        throw new RuntimeConflict("attempt_already_terminal");
      }

      this.db.sql.query("UPDATE cron_execution_attempts SET state = 'uncertain' WHERE attempt_id = ?").run(attemptId);
      this.updateOccurrenceStateInternal(attempt.occurrence_id, "blocked_unknown");

      // Dependency locks held by this attempt become uncertain
      this.db.sql.query("UPDATE cron_dependency_locks SET status = 'uncertain' WHERE active_attempt_id = ?").run(attemptId);

      return this.getAttempt(attemptId)!;
    });
  }

  private hydrateAttempt(row: any): CronExecutionAttemptRecord {
    return {
      attempt_id: row.attempt_id,
      occurrence_id: row.occurrence_id,
      attempt_number: Number(row.attempt_number),
      fencing_generation: Number(row.fencing_generation),
      coordinator_id: row.coordinator_id,
      executor_device_id: row.executor_device_id,
      state: row.state as CronAttemptState,
      task_id: row.task_id,
      started_at: Number(row.started_at),
      finished_at: row.finished_at !== null ? Number(row.finished_at) : null,
      result_status: row.result_status,
      result_summary: row.result_summary,
      error_details: row.error_details,
    };
  }

  // --------------------------------------------------------------------------
  // Sequential Dependency Queue
  // --------------------------------------------------------------------------

  acquireDependencyLock(dependency: string, occurrenceId: string, attemptId: string, leaseTtlMs: number): boolean {
    requireThat(typeof dependency === "string" && dependency.trim().length > 0, "invalid_dependency_key");
    requireThat(Number.isSafeInteger(leaseTtlMs) && leaseTtlMs > 0, "invalid_lease_ttl");

    return this.db.transaction(() => {
      const attempt = this.getAttempt(attemptId);
      requireThat(attempt && attempt.occurrence_id === occurrenceId, "invalid_attempt_for_occurrence");
      requireThat(attempt.state === "initiated" || attempt.state === "running", "attempt_not_active");

      const existingLock = this.getDependencyLock(dependency);
      if (existingLock) {
        if (existingLock.active_attempt_id === attemptId) {
          if (existingLock.status === "uncertain") {
            return false;
          }
          const now = this.db.now();
          this.db.sql.query(
            "UPDATE cron_dependency_locks SET lease_deadline = ? WHERE dependency = ?"
          ).run(now + leaseTtlMs, dependency);
          return true;
        }
        return false;
      }

      const now = this.db.now();
      this.db.sql.query(`
        INSERT INTO cron_dependency_locks (
          dependency, active_occurrence_id, active_attempt_id, acquired_at, lease_deadline, status
        ) VALUES (?, ?, ?, ?, ?, 'locked')
      `).run(dependency, occurrenceId, attemptId, now, now + leaseTtlMs);

      return true;
    });
  }

  getDependencyLock(dependency: string): CronDependencyLockRecord | null {
    const row = this.db.sql.query(
      "SELECT * FROM cron_dependency_locks WHERE dependency = ?"
    ).get(dependency) as any | null;
    if (!row) return null;
    return {
      dependency: row.dependency,
      active_occurrence_id: row.active_occurrence_id,
      active_attempt_id: row.active_attempt_id,
      acquired_at: Number(row.acquired_at),
      lease_deadline: Number(row.lease_deadline),
      status: row.status as "locked" | "uncertain",
    };
  }

  releaseDependencyLock(dependency: string, authority: {
    attemptId: string;
    coordinatorId: string;
    fence: number;
  }): void {
    identifier(authority.coordinatorId);
    requireThat(Number.isSafeInteger(authority.fence) && authority.fence > 0, "invalid_fencing_generation");

    this.db.transaction(() => {
      const lock = this.getDependencyLock(dependency);
      if (!lock) return;

      requireThat(lock.active_attempt_id === authority.attemptId, "lock_owner_mismatch");

      const epoch = this.getCoordinatorEpoch(authority.coordinatorId);
      requireThat(authority.fence === epoch.current_generation, "stale_coordinator_fence");

      const attempt = this.getAttempt(authority.attemptId);
      requireThat(attempt, "attempt_not_found");
      requireThat(attempt.fencing_generation === authority.fence, "stale_attempt_fence");

      if (lock.status === "uncertain") {
        throw new RuntimeConflict("dependency_lock_uncertain");
      }

      if (attempt.state !== "completed" && attempt.state !== "failed") {
        throw new RuntimeConflict("cannot_release_lock_unconfirmed_attempt");
      }

      this.db.sql.query("DELETE FROM cron_dependency_locks WHERE dependency = ?").run(dependency);
    });
  }

  /**
   * Reconciles a dependency lock across failovers or after process termination.
   * Separates current controller authority from the expected old attempt identity and fence.
   */
  reconcileDependencyLock(
    dependency: string,
    authority: {
      coordinatorId: string;
      fence: number;
    },
    targetAttempt: {
      attemptId: string;
      expectedFence: number;
    },
    outcome: {
      verifiedTerminated: boolean;
      terminalState?: "completed" | "failed";
      errorDetails?: string;
    }
  ): "released" | "retained_uncertain" {
    identifier(authority.coordinatorId);
    requireThat(Number.isSafeInteger(authority.fence) && authority.fence > 0, "invalid_fencing_generation");
    requireThat(Number.isSafeInteger(targetAttempt.expectedFence) && targetAttempt.expectedFence > 0, "invalid_attempt_fence");

    return this.db.transaction(() => {
      // 1. Current controller authority check
      const currentEpoch = this.getCoordinatorEpoch(authority.coordinatorId);
      requireThat(authority.fence === currentEpoch.current_generation, "stale_coordinator_fence");

      // 2. Target attempt check (matches old attempt's issued generation)
      const attempt = this.getAttempt(targetAttempt.attemptId);
      requireThat(attempt, "attempt_not_found");
      requireThat(attempt.fencing_generation === targetAttempt.expectedFence, "stale_attempt_fence");

      // 3. Do not replace an already terminal attempt result
      if (attempt.state === "completed" || attempt.state === "failed") {
        throw new RuntimeConflict("attempt_already_terminal");
      }

      const lock = this.getDependencyLock(dependency);
      if (!lock) return "released";

      requireThat(lock.active_attempt_id === targetAttempt.attemptId, "lock_owner_mismatch");

      if (outcome.verifiedTerminated) {
        const terminalState = outcome.terminalState ?? "failed";
        const now = this.db.now();
        this.db.sql.query(`
          UPDATE cron_execution_attempts SET
            state = ?,
            finished_at = ?,
            error_details = COALESCE(?, error_details)
          WHERE attempt_id = ?
        `).run(terminalState, now, outcome.errorDetails ?? null, attempt.attempt_id);

        this.updateOccurrenceStateInternal(attempt.occurrence_id, terminalState);
        this.db.sql.query("DELETE FROM cron_dependency_locks WHERE dependency = ?").run(dependency);
        return "released";
      }

      // Termination could not be confirmed: unknown evidence retains the lock!
      this.db.sql.query("UPDATE cron_dependency_locks SET status = 'uncertain' WHERE dependency = ?").run(dependency);
      this.db.sql.query("UPDATE cron_execution_attempts SET state = 'uncertain' WHERE attempt_id = ?").run(attempt.attempt_id);
      this.updateOccurrenceStateInternal(attempt.occurrence_id, "blocked_unknown");
      return "retained_uncertain";
    });
  }

  // --------------------------------------------------------------------------
  // Coordinator Authority, Bootstrap & Generation Fencing
  // --------------------------------------------------------------------------

  /** Strictly read-only query of current coordinator authority. Fails if unregistered. */
  getCoordinatorEpoch(coordinatorId?: string): CoordinatorEpochRecord {
    const row = this.db.sql.query(
      "SELECT * FROM cron_coordinator_epochs LIMIT 1"
    ).get() as any | null;

    if (!row) {
      throw new RuntimeConflict("coordinator_not_registered");
    }

    if (coordinatorId !== undefined) {
      identifier(coordinatorId);
      requireThat(row.coordinator_id === coordinatorId, "coordinator_authority_mismatch");
    }

    return {
      coordinator_id: row.coordinator_id,
      current_generation: Number(row.current_generation),
      fence_token: row.fence_token,
      updated_at: Number(row.updated_at),
    };
  }

  /** Explicit registration/bootstrap mutation. Fails if already registered. */
  registerCoordinator(coordinatorId: string): CoordinatorEpochRecord {
    identifier(coordinatorId);
    return this.db.transaction(() => {
      const existing = this.db.sql.query(
        "SELECT * FROM cron_coordinator_epochs LIMIT 1"
      ).get();
      requireThat(!existing, "coordinator_already_registered");

      const now = this.db.now();
      const fenceToken = digestLossless(["coordinator_fence", coordinatorId, 1, now]);
      this.db.sql.query(`
        INSERT INTO cron_coordinator_epochs (coordinator_id, current_generation, fence_token, updated_at)
        VALUES (?, 1, ?, ?)
      `).run(coordinatorId, fenceToken, now);

      return {
        coordinator_id: coordinatorId,
        current_generation: 1,
        fence_token: fenceToken,
        updated_at: now,
      };
    });
  }

  incrementCoordinatorEpoch(coordinatorId: string, expectedGeneration: number): CoordinatorEpochRecord {
    identifier(coordinatorId);
    requireThat(Number.isSafeInteger(expectedGeneration) && expectedGeneration > 0, "invalid_expected_generation");

    return this.db.transaction(() => {
      const current = this.getCoordinatorEpoch(coordinatorId);
      requireThat(current.current_generation === expectedGeneration, "stale_coordinator_epoch");

      const nextGeneration = current.current_generation + 1;
      const now = this.db.now();
      const nextFenceToken = digestLossless(["coordinator_fence", coordinatorId, nextGeneration, now]);

      this.db.sql.query(`
        UPDATE cron_coordinator_epochs SET
          current_generation = ?,
          fence_token = ?,
          updated_at = ?
        WHERE coordinator_id = ?
      `).run(nextGeneration, nextFenceToken, now, coordinatorId);

      return {
        coordinator_id: coordinatorId,
        current_generation: nextGeneration,
        fence_token: nextFenceToken,
        updated_at: now,
      };
    });
  }

  rotateCoordinatorAuthority(
    currentCoordinatorId: string,
    expectedGeneration: number,
    newCoordinatorId: string
  ): CoordinatorEpochRecord {
    identifier(currentCoordinatorId);
    identifier(newCoordinatorId);
    requireThat(Number.isSafeInteger(expectedGeneration) && expectedGeneration > 0, "invalid_expected_generation");

    return this.db.transaction(() => {
      const current = this.getCoordinatorEpoch(currentCoordinatorId);
      requireThat(current.current_generation === expectedGeneration, "stale_coordinator_epoch");

      const nextGeneration = current.current_generation + 1;
      const now = this.db.now();
      const nextFenceToken = digestLossless(["coordinator_fence", newCoordinatorId, nextGeneration, now]);

      this.db.sql.query(`
        UPDATE cron_coordinator_epochs SET
          coordinator_id = ?,
          current_generation = ?,
          fence_token = ?,
          updated_at = ?
        WHERE coordinator_id = ?
      `).run(newCoordinatorId, nextGeneration, nextFenceToken, now, currentCoordinatorId);

      return {
        coordinator_id: newCoordinatorId,
        current_generation: nextGeneration,
        fence_token: nextFenceToken,
        updated_at: now,
      };
    });
  }
}
