import { Database } from "bun:sqlite";
import { closeSync, lstatSync, openSync } from "node:fs";
import { isAbsolute } from "node:path";
import { requireThat } from "./value";

const APPLICATION_ID = 0x434d5254;

/** Local coordinator database. Never place this file on a shared network mount. */
export class RuntimeDatabase {
  readonly sql: Database;
  private observedTime = 0;

  constructor(path: string, private readonly clock: () => number = Date.now) {
    requireThat(path === ":memory:" || isAbsolute(path), "database_path_must_be_explicit");
    if (path !== ":memory:") {
      try {
        closeSync(openSync(path, "wx", 0o600));
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
        requireThat(lstatSync(path).isFile(), "database_must_be_regular_file");
      }
    }
    this.sql = new Database(path, { strict: true });
    try {
      this.sql.exec("PRAGMA busy_timeout = 5000; PRAGMA foreign_keys = ON;");
      this.transaction(() => {
        const version = (this.sql.query("PRAGMA user_version").get() as { user_version: number }).user_version;
        const app = (this.sql.query("PRAGMA application_id").get() as { application_id: number }).application_id;
        requireThat(version >= 0 && version <= 24, "unsupported_database_version");
        requireThat(app === 0 || app === APPLICATION_ID, "foreign_database");
        if (version === 0) {
          const tables = this.sql.query("SELECT name FROM sqlite_master WHERE type='table'").all();
          requireThat(tables.length === 0, "unversioned_database_not_empty");
          this.sql.exec(`
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO meta VALUES ('clock', '0');
            CREATE TABLE tasks (
              task_id TEXT PRIMARY KEY, principal TEXT NOT NULL, revision INTEGER NOT NULL,
              fence INTEGER NOT NULL DEFAULT 0, active_episode TEXT, status TEXT NOT NULL,
              needs_reconciliation INTEGER NOT NULL DEFAULT 0, raw TEXT NOT NULL
            );
            CREATE TABLE episodes (
              episode_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),
              device_id TEXT NOT NULL, fence INTEGER NOT NULL, state TEXT NOT NULL,
              lease_until INTEGER NOT NULL, result TEXT,
              UNIQUE(task_id, fence)
            );
            CREATE TABLE events (
              seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL REFERENCES tasks(task_id),
              kind TEXT NOT NULL, revision INTEGER NOT NULL, fence INTEGER NOT NULL,
              principal TEXT NOT NULL, origin TEXT NOT NULL, at INTEGER NOT NULL, payload TEXT NOT NULL
            );
            CREATE TABLE receipts (
              principal TEXT NOT NULL, request_id TEXT NOT NULL, digest TEXT NOT NULL,
              response TEXT NOT NULL, PRIMARY KEY(principal, request_id)
            );
            CREATE TABLE effects (
              effect_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),
              episode_id TEXT NOT NULL REFERENCES episodes(episode_id), fence INTEGER NOT NULL,
              digest TEXT NOT NULL, state TEXT NOT NULL, result TEXT
            );
            CREATE TABLE migrations (
              source_id TEXT PRIMARY KEY, digest TEXT NOT NULL, snapshot TEXT NOT NULL, task_count INTEGER NOT NULL
            );
            CREATE TABLE messages (
              message_id TEXT PRIMARY KEY, recipient_task TEXT NOT NULL REFERENCES tasks(task_id),
              sender_task TEXT REFERENCES tasks(task_id), sender_principal TEXT NOT NULL,
              sequence INTEGER NOT NULL, correlation_id TEXT NOT NULL, causation_id TEXT,
              origin TEXT NOT NULL, kind TEXT NOT NULL, remaining_hops INTEGER NOT NULL,
              created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL, payload TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'pending', receipt_episode TEXT, receipt_fence INTEGER,
              consumed_evidence TEXT, UNIQUE(recipient_task, sequence)
            );
            CREATE INDEX events_task_seq ON events(task_id, seq);
            CREATE INDEX messages_recipient ON messages(recipient_task, sequence);
            CREATE INDEX messages_correlation ON messages(correlation_id);
            PRAGMA application_id = ${APPLICATION_ID};
            PRAGMA user_version = 1;
          `);
        } else {
          requireThat(app === APPLICATION_ID, "foreign_database");
        }
        if (version < 2) {
          this.sql.exec(`
            CREATE TABLE provider_checks (
              cache_key TEXT PRIMARY KEY, generation INTEGER NOT NULL, state TEXT NOT NULL,
              reason TEXT NOT NULL, attempts INTEGER NOT NULL, valid_until INTEGER NOT NULL,
              retry_after INTEGER, lease_until INTEGER NOT NULL, probe_token TEXT, report TEXT
            );
            PRAGMA user_version = 2;
          `);
        }
        if (version < 3) {
          this.sql.exec(`
            CREATE TABLE device_assignments (
              task_id TEXT PRIMARY KEY REFERENCES tasks(task_id), principal TEXT NOT NULL,
              authority_digest TEXT NOT NULL, specification TEXT NOT NULL
            );
            PRAGMA user_version = 3;
          `);
        }
        if (version < 4) {
          this.sql.exec(`
            CREATE TABLE device_revocations (
              device_id TEXT PRIMARY KEY, principal TEXT NOT NULL, revoked_at INTEGER NOT NULL
            );
            PRAGMA user_version = 4;
          `);
        }
        if (version < 5) {
          this.sql.exec(`
            CREATE TABLE execution_manifests (
              effect_id TEXT PRIMARY KEY REFERENCES effects(effect_id),
              digest TEXT NOT NULL, payload TEXT NOT NULL
            );
            CREATE TABLE effect_observations (
              effect_id TEXT PRIMARY KEY REFERENCES effects(effect_id),
              digest TEXT NOT NULL, payload TEXT NOT NULL
            );
            PRAGMA user_version = 5;
          `);
        }
        if (version < 6) {
          this.sql.exec(`
            CREATE TABLE device_execution_records (
              effect_id TEXT PRIMARY KEY, device_id TEXT NOT NULL, task_id TEXT NOT NULL,
              episode_id TEXT NOT NULL, fence INTEGER NOT NULL, assignment_digest TEXT NOT NULL,
              workspace_id TEXT NOT NULL, phase TEXT NOT NULL, job TEXT NOT NULL,
              manifest_digest TEXT NOT NULL, manifest TEXT NOT NULL,
              observation_digest TEXT, observation TEXT, result_digest TEXT, result TEXT,
              UNIQUE(device_id, episode_id)
            );
            PRAGMA user_version = 6;
          `);
        }
        if (version < 7) {
          this.sql.exec(`
            CREATE TABLE device_reconciliations (
              challenge_id TEXT PRIMARY KEY, principal TEXT NOT NULL, device_id TEXT NOT NULL,
              registration_digest TEXT NOT NULL, task_id TEXT NOT NULL REFERENCES tasks(task_id),
              challenge_digest TEXT NOT NULL, challenge TEXT NOT NULL,
              report_digest TEXT, response TEXT
            );
            PRAGMA user_version = 7;
          `);
        }
        if (version < 8) {
          this.sql.exec(`
            CREATE TABLE local_runs (
              run_id TEXT PRIMARY KEY, principal TEXT NOT NULL, device_id TEXT NOT NULL,
              origin TEXT NOT NULL, task_id TEXT NOT NULL REFERENCES tasks(task_id),
              expected_revision INTEGER NOT NULL, binding_digest TEXT NOT NULL,
              state TEXT NOT NULL CHECK(state IN ('queued','running','completed','blocked','cancelled','interrupted')),
              created_at INTEGER NOT NULL, owner TEXT, lease TEXT, outcome TEXT
            );
            CREATE UNIQUE INDEX local_runs_active_task ON local_runs(task_id) WHERE state IN ('queued','running');
            CREATE INDEX local_runs_queue ON local_runs(principal,device_id,state,created_at,run_id);
            PRAGMA user_version = 8;
          `);
        }
        if (version < 9) {
          this.sql.exec(`
            CREATE TABLE native_mailbox_deliveries (
              message_id TEXT PRIMARY KEY REFERENCES messages(message_id),
              effect_id TEXT NOT NULL REFERENCES effects(effect_id),
              message_digest TEXT NOT NULL, delivery_digest TEXT NOT NULL
            );
            CREATE INDEX native_mailbox_effect ON native_mailbox_deliveries(effect_id);
            PRAGMA user_version = 9;
          `);
        }
        if (version < 10) {
          this.sql.exec(`
            CREATE TABLE native_agent_calls (
              seq INTEGER PRIMARY KEY AUTOINCREMENT,
              call_id TEXT NOT NULL UNIQUE, effect_id TEXT NOT NULL REFERENCES effects(effect_id),
              request_id TEXT NOT NULL, tool TEXT NOT NULL, input TEXT NOT NULL,
              scope_digest TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('pending','done')),
              response TEXT, UNIQUE(effect_id,request_id)
            );
            CREATE TABLE native_agent_deliveries (
              message_id TEXT PRIMARY KEY REFERENCES messages(message_id),
              call_id TEXT NOT NULL REFERENCES native_agent_calls(call_id),
              message_digest TEXT NOT NULL
            );
            PRAGMA user_version = 10;
          `);
        }
        if (version < 11) {
          this.sql.exec(`
            CREATE TABLE delivery_routes (
              task_id TEXT PRIMARY KEY REFERENCES tasks(task_id), principal TEXT NOT NULL,
              adapter_id TEXT NOT NULL, adapter_digest TEXT NOT NULL, binding TEXT NOT NULL,
              digest TEXT NOT NULL, first_event INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE delivery_outbox (
              delivery_id TEXT PRIMARY KEY, event_seq INTEGER NOT NULL UNIQUE REFERENCES events(seq),
              task_id TEXT NOT NULL REFERENCES delivery_routes(task_id), principal TEXT NOT NULL,
              route_digest TEXT NOT NULL, envelope TEXT NOT NULL, envelope_digest TEXT NOT NULL,
              state TEXT NOT NULL CHECK(state IN ('pending','dispatching','sent','unknown','blocked')),
              attempt_id TEXT, attempt_started INTEGER, attempt_until INTEGER, observation TEXT, receipt TEXT, reason TEXT,
              created_at INTEGER NOT NULL
            );
            CREATE INDEX delivery_pending ON delivery_outbox(principal,state,event_seq);
            CREATE TABLE transport_receipts (
              adapter_digest TEXT NOT NULL, remote_message_id TEXT NOT NULL,
              delivery_id TEXT NOT NULL UNIQUE REFERENCES delivery_outbox(delivery_id),
              PRIMARY KEY(adapter_digest,remote_message_id)
            );
            PRAGMA user_version = 11;
          `);
        }
        if (version < 12) {
          this.sql.exec(`
            CREATE TABLE feishu_inbox (
              id TEXT PRIMARY KEY, app_id TEXT NOT NULL, principal TEXT NOT NULL,
              event_id TEXT NOT NULL, message_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
              payload TEXT NOT NULL, payload_digest TEXT NOT NULL,
              state TEXT NOT NULL CHECK(state IN ('pending','applied','blocked')),
              task_id TEXT, reason TEXT, received_at INTEGER NOT NULL,
              UNIQUE(app_id,event_id), UNIQUE(app_id,message_id)
            );
            CREATE INDEX feishu_inbox_pending ON feishu_inbox(principal,app_id,state,received_at);
            CREATE TABLE feishu_event_aliases (
              app_id TEXT NOT NULL, event_id TEXT NOT NULL,
              receipt_id TEXT NOT NULL REFERENCES feishu_inbox(id), PRIMARY KEY(app_id,event_id)
            );
            CREATE TABLE feishu_conversations (
              id TEXT PRIMARY KEY, app_id TEXT NOT NULL, principal TEXT NOT NULL,
              task_id TEXT NOT NULL UNIQUE REFERENCES tasks(task_id),
              first_event TEXT NOT NULL REFERENCES feishu_inbox(id)
            );
            PRAGMA user_version = 12;
          `);
        }
        if (version < 13) {
          this.sql.exec(`
            CREATE TABLE command_reservations (
              principal TEXT NOT NULL, request_id TEXT NOT NULL, digest TEXT NOT NULL,
              PRIMARY KEY(principal,request_id)
            );
            PRAGMA user_version = 13;
          `);
        }
        if (version < 14) {
          this.sql.exec(`
            CREATE TABLE device_native_adoptions (
              adoption_id TEXT PRIMARY KEY, principal TEXT NOT NULL, device_id TEXT NOT NULL,
              task_id TEXT NOT NULL, workspace_id TEXT NOT NULL, capability TEXT NOT NULL,
              profile_digest TEXT NOT NULL, reference TEXT NOT NULL, context_digest TEXT NOT NULL
            );
            PRAGMA user_version = 14;
          `);
        }
        if (version < 15) {
          this.sql.exec(`
            CREATE TABLE device_assignment_generations (
              task_id TEXT PRIMARY KEY REFERENCES device_assignments(task_id), generation TEXT NOT NULL
            );
            CREATE TABLE device_scheduler_leases (
              principal TEXT NOT NULL, device_id TEXT NOT NULL, token TEXT NOT NULL,
              generation INTEGER NOT NULL, boot_id TEXT NOT NULL, deadline_ms INTEGER NOT NULL,
              PRIMARY KEY(principal,device_id)
            );
            CREATE TABLE device_scheduled_work (
              work_id TEXT PRIMARY KEY, principal TEXT NOT NULL, device_id TEXT NOT NULL,
              task_id TEXT NOT NULL, assignment_digest TEXT NOT NULL, execution_digest TEXT NOT NULL,
              state TEXT NOT NULL CHECK(state IN ('queued','running','waiting','blocked','unknown','completed','cancelled','superseded')),
              attempt INTEGER NOT NULL DEFAULT 0, expected_revision INTEGER NOT NULL,
              run_id TEXT, outcome TEXT, retry_after INTEGER, created_at INTEGER NOT NULL,
              UNIQUE(principal,device_id,task_id,assignment_digest,execution_digest)
            );
            CREATE INDEX device_scheduled_pending ON device_scheduled_work(principal,device_id,state,created_at);
            PRAGMA user_version = 15;
          `);
        }
        if (version < 16) {
          this.sql.exec(`
            CREATE TABLE team_phases (
              team_id TEXT PRIMARY KEY, principal TEXT NOT NULL, revision INTEGER NOT NULL,
              state TEXT NOT NULL
            );
            PRAGMA user_version = 16;
          `);
        }
        if (version < 17) {
          this.sql.exec(`
            CREATE TABLE team_topologies (
              task_id TEXT PRIMARY KEY REFERENCES tasks(task_id), revision INTEGER NOT NULL,
              state TEXT NOT NULL
            );
            PRAGMA user_version = 17;
          `);
        }
        if (version < 18) {
          this.sql.exec(`
            CREATE TABLE topology_tasks (
              child_id TEXT PRIMARY KEY REFERENCES tasks(task_id),
              parent_id TEXT NOT NULL REFERENCES team_topologies(task_id),
              topology TEXT NOT NULL, substage TEXT NOT NULL, worker_role TEXT NOT NULL,
              checkpoint_id TEXT NOT NULL, run_id TEXT NOT NULL, accepted TEXT,
              UNIQUE(parent_id, checkpoint_id, worker_role)
            );
            PRAGMA user_version = 18;
          `);
        }
        if (version < 19) {
          this.sql.exec(`
            ALTER TABLE topology_tasks ADD COLUMN generation INTEGER NOT NULL DEFAULT 1;
            CREATE TABLE topology_task_history (
              child_id TEXT NOT NULL REFERENCES tasks(task_id), generation INTEGER NOT NULL,
              assignment TEXT NOT NULL, PRIMARY KEY(child_id,generation)
            );
            PRAGMA user_version = 19;
          `);
        }
        if (version < 20) {
          this.sql.exec(`
            CREATE TABLE topology_controls (
              task_id TEXT PRIMARY KEY REFERENCES team_topologies(task_id), config TEXT NOT NULL
            );
            PRAGMA user_version = 20;
          `);
        }
        if (version < 21) {
          this.sql.exec(`
            CREATE TABLE topology_completions (
              task_id TEXT PRIMARY KEY REFERENCES team_topologies(task_id), parent_revision INTEGER NOT NULL,
              topology_revision INTEGER NOT NULL, checkpoint_id TEXT NOT NULL, state_digest TEXT NOT NULL,
              inputs_digest TEXT NOT NULL, result TEXT NOT NULL
            );
            PRAGMA user_version = 21;
          `);
        }
        if (version < 22) {
          this.sql.exec(`
            ALTER TABLE topology_tasks ADD COLUMN execution_id TEXT NOT NULL DEFAULT '';
            UPDATE topology_tasks SET execution_id=(SELECT json_extract(state,'$.execution_id') FROM team_topologies WHERE task_id=parent_id);
            CREATE TABLE topology_runs (
              task_id TEXT NOT NULL REFERENCES team_topologies(task_id), execution_id TEXT NOT NULL,
              topology_revision INTEGER NOT NULL, snapshot TEXT NOT NULL, digest TEXT NOT NULL,
              PRIMARY KEY(task_id,execution_id), UNIQUE(task_id,topology_revision)
            );
            PRAGMA user_version = 22;
          `);
        }
        if (version < 23) {
          this.sql.exec(`
            ALTER TABLE topology_tasks ADD COLUMN kind TEXT NOT NULL DEFAULT 'native' CHECK(kind IN ('native','aggregate'));
            PRAGMA user_version = 23;
          `);
        }
        if (version < 24) {
          this.sql.exec(`
            CREATE TABLE topology_schedules (
              root_id TEXT PRIMARY KEY REFERENCES tasks(task_id), principal TEXT NOT NULL,
              device_id TEXT NOT NULL, origin TEXT NOT NULL, plan TEXT NOT NULL, plan_digest TEXT NOT NULL,
              revision INTEGER NOT NULL, mode TEXT NOT NULL, reason TEXT,
              lease_owner TEXT, lease_until INTEGER NOT NULL DEFAULT 0, lease_fence INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE topology_schedule_members (
              task_id TEXT PRIMARY KEY REFERENCES tasks(task_id), root_id TEXT NOT NULL REFERENCES topology_schedules(root_id)
            );
            PRAGMA user_version = 24;
          `);
        }
      });
      this.sql.exec("PRAGMA journal_mode = WAL; PRAGMA synchronous = FULL;");
    } catch (error) {
      this.sql.close();
      throw error;
    }
  }

  transaction<T>(operation: () => T): T {
    try {
      return this.sql.transaction(operation).immediate();
    } catch (error) {
      // A rejected stale command may still have observed time. Do not forget that
      // observation on rollback and accidentally revive its lease after a clock jump.
      if (this.observedTime > 0 && !this.sql.inTransaction) {
        this.sql.query("UPDATE meta SET value=CAST(MAX(CAST(value AS INTEGER),?) AS TEXT) WHERE key='clock'").run(this.observedTime);
      }
      throw error;
    }
  }

  // Only coordinator time determines expiry; a backward wall-clock jump cannot revive a lease.
  now(): number {
    const proposed = this.clock();
    requireThat(Number.isSafeInteger(proposed) && proposed >= 0, "invalid_coordinator_clock");
    const prior = Number((this.sql.query("SELECT value FROM meta WHERE key='clock'").get() as { value: string }).value);
    const now = Math.max(prior, proposed, this.observedTime);
    this.observedTime = now;
    this.sql.query("UPDATE meta SET value=? WHERE key='clock'").run(String(now));
    return now;
  }

  close(): void { this.sql.close(); }
}
