import { assertTopologyNativeInput } from "./topology-native-input";
import { topologyNativeClaim } from "./topology-execution";
import { verifyDeviceCompletion } from "./task-completion";
import { assertDeviceWorkspaceGrant, verifyDeviceWorkspaceProof } from "./providers/device-workspace-proof";
import { createHash, timingSafeEqual } from "node:crypto";
import { assertProtocolSchema, ProtocolValidationError, type DeviceCommand, type DeviceLeaseWindow, type DeviceReconciliationReport } from "@controlmesh/protocol";
import { command, requireScope } from "./commands";
import { RuntimeKernel, type Lease, type Principal, type TaskSnapshot } from "./kernel";
import { AgentMailbox, type SendMessage } from "./mailbox";
import { DeviceReconciliation } from "./device-reconciliation";
import { canonical, digest, identifier, object, requireThat, RuntimeConflict } from "./value";
import { setTimeout as delay } from "node:timers/promises";
import { decodeNativeAgentScope, NativeAgentJournal } from "./providers/native-agent-journal";
import { NativeMailboxDelivery } from "./providers/native-mailbox";
import { nativeInput } from "./providers/native-mailbox-input";

const nativeProvider = (provider: unknown) => provider === "opencode" || provider === "claude";

export interface DeviceRegistration {
  device_id: string;
  principal_id: string;
  token_sha256: string;
  capabilities: readonly string[];
  workspace_ids: readonly string[];
}
export interface DeviceAssignment {
  workspace_id: string;
  capability: string;
  device_ids: readonly string[];
  /** Issued by local trusted ingress; never interpreted as a command line by the transport. */
  input: Record<string, unknown>;
  peer_tasks?: readonly string[];
  parent_task?: string | null;
}
export interface DeviceJob {
  task_id: string;
  revision: number;
  status: string;
  workspace_id: string;
  capability: string;
  input: Record<string, unknown>;
  assignment_digest: string;
  execution?: Record<string, unknown>;
  execution_digest?: string;
  needs_reconciliation?: boolean;
  active_episode?: boolean;
  peer_tasks?: readonly string[];
  parent_task?: string | null;
}
interface AssignmentRow { task_id: string; principal: string; authority_digest: string; specification: string }
const workerScopes = ["task:read", "task:execute", "message:send", "message:read", "message:ack"];
const MAX_BODY = 262_144;

function taskAuthority(snapshot: TaskSnapshot): string {
  const { status: _status, completed_at: _completed, ...authority } = snapshot.task;
  return digest(authority);
}
function json(value: unknown, status = 200): Response {
  return Response.json(value, { status, headers: { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" } });
}

/** A separate private worker port. The public product facade remains read-only. */
export class DeviceCoordinator {
  private readonly devices: Map<string, DeviceRegistration>;
  private readonly pending = new Map<string, number>();
  private readonly rates = new Map<string, { since: number; count: number }>();
  private readonly mailbox: AgentMailbox;
  private readonly nativeDelivery: NativeMailboxDelivery;
  private readonly nativeCalls = new Map<string, { digest: string; promise: Promise<Record<string, unknown>> }>();
  readonly reconciliation: DeviceReconciliation;

  constructor(readonly kernel: RuntimeKernel, registrations: readonly DeviceRegistration[], private readonly assertCurrent: () => void = () => {}) {
    requireThat(registrations.length > 0 && registrations.length <= 128, "invalid_device_catalog");
    this.devices = new Map();
    const hashes = new Set<string>();
    for (const source of registrations) {
      const device = structuredClone(source);
      identifier(device.device_id); identifier(device.principal_id);
      requireThat(/^[a-f0-9]{64}$/.test(device.token_sha256) && !hashes.has(device.token_sha256), "invalid_device_credential");
      requireThat(!this.devices.has(device.device_id), "duplicate_device");
      for (const list of [device.capabilities, device.workspace_ids]) {
        requireThat(list.length > 0 && list.length <= 128 && new Set(list).size === list.length, "invalid_device_catalog");
        list.forEach(identifier);
      }
      hashes.add(device.token_sha256);
      this.devices.set(device.device_id, device);
    }
    this.mailbox = new AgentMailbox(kernel);
    this.nativeDelivery = new NativeMailboxDelivery(kernel);
    this.reconciliation = new DeviceReconciliation(kernel, (id, principal) => {
      const device = this.devices.get(id);
      requireThat(device && device.principal_id === principal && !this.revoked(id), "device_not_authorized");
      return device;
    }, (device, taskId) => this.assignment(device, taskId));
  }

  /** Trusted operator control; no remote device can enable itself or change its grants. */
  revoke(actor: Principal, deviceId: string): void {
    requireScope(actor, "device:revoke");
    requireThat(actor.origin === "human_request" || actor.origin === "internal", "revocation_requires_trusted_ingress");
    identifier(deviceId);
    requireThat(this.devices.get(deviceId)?.principal_id === actor.id, "device_not_authorized");
    this.kernel.db.transaction(() => {
      this.kernel.db.sql.query("INSERT INTO device_revocations VALUES (?,?,?) ON CONFLICT(device_id) DO NOTHING").run(deviceId, actor.id, this.kernel.db.now());
    });
  }

  private revoked(deviceId: string): boolean {
    return Boolean(this.kernel.db.sql.query("SELECT 1 FROM device_revocations WHERE device_id=?").get(deviceId));
  }

  assign(actor: Principal, requestId: string, taskId: string, revision: number, specification: DeviceAssignment): void {
    requireScope(actor, "device:assign");
    requireThat(actor.origin === "human_request" || actor.origin === "internal", "assignment_requires_trusted_ingress");
    const snapshot = this.kernel.inspect(actor, taskId);
    identifier(specification.workspace_id); identifier(specification.capability);
    requireThat(object(specification.input) && Buffer.byteLength(canonical(specification.input)) <= 32_768, "invalid_device_input");
    requireThat(specification.device_ids.length > 0 && specification.device_ids.length <= 128 && new Set(specification.device_ids).size === specification.device_ids.length, "invalid_assignment_devices");
    requireThat((specification.peer_tasks?.length ?? 0) <= 128, "invalid_assignment_peers");
    specification.peer_tasks?.forEach(identifier);
    requireThat(new Set(specification.peer_tasks ?? []).size === (specification.peer_tasks?.length ?? 0)
      && !specification.peer_tasks?.includes(taskId), "invalid_assignment_peers");
    if (specification.parent_task !== undefined && specification.parent_task !== null) {
      identifier(specification.parent_task);
      requireThat(specification.peer_tasks?.includes(specification.parent_task), "native_parent_not_authorized");
    }
    for (const id of specification.device_ids) {
      const device = this.devices.get(id);
      requireThat(device && device.principal_id === actor.id && !this.revoked(id), "device_not_authorized");
      requireThat(device.capabilities.includes(specification.capability) && device.workspace_ids.includes(specification.workspace_id), "device_capability_unavailable");
    }
    // Native databases and credentials stay on their issuing device; no implicit cross-device transcript replay.
    const native = snapshot.task.native_session;
    requireThat(!native || (object(native) && specification.device_ids.every(id => id === native.device_id)), "native_session_device_bound");
    if (native) assertProtocolSchema(object(native) && native.schema_version === "controlmesh.device_native_adoption.v1"
      ? "device-native-adoption.schema.json" : "device-native-session.schema.json", native);
    command(this.kernel.db, actor, requestId, "device.assign", { taskId, revision, specification }, () => {
      const current = this.kernel.inspect(actor, taskId);
      requireThat(current.revision === revision && current.task.status === "waiting" && !current.active_episode && !current.needs_reconciliation, "task_not_assignable");
      this.kernel.db.sql.query("INSERT INTO device_assignments VALUES (?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET principal=excluded.principal,authority_digest=excluded.authority_digest,specification=excluded.specification")
        .run(taskId, actor.id, taskAuthority(current), canonical(specification));
      this.kernel.db.sql.query("INSERT INTO device_assignment_generations VALUES (?,?) ON CONFLICT(task_id) DO UPDATE SET generation=excluded.generation")
        .run(taskId, digest([actor.id, requestId]));
      this.kernel.db.sql.query("INSERT INTO events (task_id,kind,revision,fence,principal,origin,at,payload) VALUES (?,'device.assigned',?,?,?,?,?,?)")
        .run(taskId, current.revision, current.fence, actor.id, this.kernel.eventOrigin(actor), this.kernel.db.now(), canonical({ assignment_digest: this.assignmentDigest(taskId, specification) }));
      return { assigned: true };
    });
  }

  private actor(device: DeviceRegistration): Principal {
    return { id: device.principal_id, device_id: device.device_id, origin: "agent_message", scopes: workerScopes };
  }

  private assignmentDigest(taskId: string, specification: DeviceAssignment): string {
    const row = this.kernel.db.sql.query("SELECT generation FROM device_assignment_generations WHERE task_id=?").get(taskId) as { generation: string } | null;
    return row ? digest({ specification, generation: row.generation }) : digest(specification);
  }

  inspectIssued(actor: Principal, taskId: string, deviceId?: string) {
    this.assertCurrent(); requireScope(actor, "device:assign"); this.kernel.inspect(actor, taskId);
    const row = this.kernel.db.sql.query("SELECT specification FROM device_assignments WHERE task_id=? AND principal=?").get(taskId, actor.id) as { specification: string } | null;
    requireThat(row, "assignment_unavailable"); const specification = JSON.parse(row.specification) as DeviceAssignment;
    const device = deviceId === undefined ? specification.device_ids.map(id => this.devices.get(id)).find(item => item && !this.revoked(item.device_id)) : this.devices.get(deviceId);
    requireThat(device && device.principal_id === actor.id && specification.device_ids.includes(device.device_id), "device_not_authorized");
    const job = this.assignment(device, taskId, true);
    return { specification, assignment_digest: job.assignment_digest, execution_digest: job.execution_digest! };
  }

  private assignment(device: DeviceRegistration, taskId: string, allowReleasedTopology = false): DeviceJob {
    this.assertCurrent();
    requireThat(!this.revoked(device.device_id), "device_revoked");
    identifier(taskId);
    const row = this.kernel.db.sql.query("SELECT * FROM device_assignments WHERE task_id=? AND principal=?").get(taskId, device.principal_id) as AssignmentRow | null;
    requireThat(row, "assignment_unavailable");
    const specification = JSON.parse(row.specification) as DeviceAssignment;
    requireThat(specification.device_ids.includes(device.device_id), "assignment_unavailable");
    requireThat(device.capabilities.includes(specification.capability) && device.workspace_ids.includes(specification.workspace_id), "device_capability_unavailable");
    const task = this.kernel.inspect(this.actor(device), taskId);
    requireThat(taskAuthority(task) === row.authority_digest, "assignment_authority_changed");
    if (!allowReleasedTopology && task.task.status === "waiting") {
      const run = this.kernel.db.sql.query("SELECT r.lease FROM topology_tasks t JOIN topology_device_runs r ON r.run_id=t.run_id WHERE t.child_id=? AND t.execution_source='device'").get(taskId) as { lease: string | null } | null;
      requireThat(!run?.lease, "device_topology_retry_required");
    }
    // Execution authority is projected from the stored task, never the assignment's input body.
    const execution = Object.fromEntries(["provider", "model", "prompt", "execution_context", "tool_grant", "native_session", "completion_requirements"]
      .filter(key => Object.hasOwn(task.task, key)).map(key => [key, task.task[key]]));
    return { task_id: taskId, revision: task.revision, status: task.task.status, workspace_id: specification.workspace_id,
      capability: specification.capability, input: specification.input, assignment_digest: this.assignmentDigest(taskId, specification), execution, execution_digest: digest(execution),
      needs_reconciliation: task.needs_reconciliation, active_episode: task.active_episode !== null,
      peer_tasks: specification.peer_tasks ?? [], parent_task: specification.parent_task ?? null };
  }

  private authenticate(request: Request): DeviceRegistration {
    this.assertCurrent();
    const header = request.headers.get("Authorization") ?? "";
    requireThat(/^Bearer [A-Za-z0-9_-]{43,128}$/.test(header), "unauthorized");
    const hash = createHash("sha256").update(header.slice(7)).digest();
    let found: DeviceRegistration | undefined;
    for (const device of this.devices.values()) {
      if (timingSafeEqual(hash, Buffer.from(device.token_sha256, "hex"))) found = device;
    }
    requireThat(found && !this.revoked(found.device_id), "unauthorized");
    return found;
  }

  private window(actor: Principal, lease: Lease): DeviceLeaseWindow {
    // Stored claim/renew receipts are observations, not fresh execution authority.
    return this.kernel.withLease(actor, lease, () => {
      const remaining = Math.min(30_000, lease.lease_until - this.kernel.db.now());
      requireThat(remaining > 0, "lease_expired");
      return { schema_version: "controlmesh.device_lease_window.v1", lease, remaining_ms: remaining };
    });
  }

  private nativeManifest(lease: Lease, effectId: string): Record<string, unknown> {
    const row = this.kernel.db.sql.query("SELECT m.payload,m.digest FROM execution_manifests m JOIN effects e ON e.effect_id=m.effect_id WHERE e.effect_id=? AND e.task_id=? AND e.episode_id=? AND e.fence=?")
      .get(effectId, lease.task_id, lease.episode_id, lease.fence) as { payload: string; digest: string } | null;
    requireThat(row, "device_native_manifest_required");
    const ref: unknown = JSON.parse(row.payload);
    assertProtocolSchema("device-evidence-ref.schema.json", ref);
    requireThat(object(ref) && digest(ref) === row.digest, "device_manifest_corrupted");
    return ref;
  }

  private evidenceMatches(manifest: Record<string, unknown>, value: unknown): asserts value is Record<string, unknown> {
    assertProtocolSchema("device-evidence-ref.schema.json", value);
    requireThat(object(value), "invalid_device_evidence");
    const { observation_digest: _observation, result_digest: _result, ...base } = value;
    requireThat(digest(base) === digest(manifest), "device_evidence_reference_mismatch");
  }

  private execute(device: DeviceRegistration, input: DeviceCommand): unknown {
    requireThat(!this.revoked(device.device_id), "unauthorized");
    const actor = this.actor(device);
    const args = input.arguments;
    const request = input.request_id;
    if (input.operation === "reconciliation") return this.reconciliation.inspect(device, args.challenge_id as string);
    if (input.operation === "reconcile") return this.reconciliation.report(device, request, args.report as DeviceReconciliationReport);
    // JSON Schema validates the discriminated arguments before these casts.
    if (input.operation === "queue" || input.operation === "queue_page") {
      const after = input.operation === "queue_page" ? args.after : null;
      const rows = this.kernel.db.sql.query("SELECT a.task_id FROM device_assignments a JOIN tasks t ON a.task_id=t.task_id WHERE a.principal=? AND t.status='waiting' AND t.needs_reconciliation=0 AND a.task_id>? ORDER BY a.task_id LIMIT 1024").all(actor.id, typeof after === "string" ? after : "") as { task_id: string }[];
      const jobs: DeviceJob[] = [];
      let scanned = 0;
      for (const row of rows) {
        scanned++;
        try { const job = this.assignment(device, row.task_id); assertTopologyNativeInput(this.kernel, row.task_id); topologyNativeClaim(this.kernel, actor, row.task_id); jobs.push(job); } catch (error) { if (!(error instanceof RuntimeConflict)) throw error; }
        if (jobs.length === 32) break;
      }
      return input.operation === "queue" ? jobs : { items: jobs,
        next_cursor: scanned && (scanned < rows.length || rows.length === 1024) ? rows[scanned - 1].task_id : null };
    }
    if (input.operation === "inspect" || input.operation === "claim") {
      const job = this.assignment(device, args.task_id as string);
      if (input.operation === "inspect") return job;
      requireThat(args.assignment_digest === job.assignment_digest, "assignment_revision_conflict");
      return this.window(actor, this.kernel.claim(actor, request, job.task_id, args.revision as number, args.ttl_ms as number));
    }
    const lease = args.lease as Lease;
    const job = this.assignment(device, lease.task_id);
    if (input.operation === "release") {
      const result = this.kernel.releaseUnstarted(actor, request, lease, args.reason as string | undefined);
      return { task_id: result.task.task_id, status: result.task.status, revision: result.revision };
    }
    if (input.operation === "complete") {
      // Commit verification receipt and task outcome together. Exact lost-response replay is safe;
      // conflicting/late new results still pass the kernel's fence and lease checks.
      return this.kernel.db.transaction(() => {
        if (nativeProvider(job.execution?.provider)) {
          const manifest = this.nativeManifest(lease, args.effect_id as string);
          assertProtocolSchema("device-native-result.schema.json", args.result);
          const result = args.result as Record<string, unknown>;
          verifyDeviceWorkspaceProof(manifest.workspace_write, result.workspace_write);
          verifyDeviceCompletion(job.execution?.completion_requirements, result.completion);
          this.evidenceMatches(manifest, result.evidence);
          requireThat(result.evidence.result_digest && result.evidence.observation_digest && digest(result.text) === result.output_digest, "device_result_evidence_missing");
          const original = this.kernel.db.sql.query("SELECT payload FROM effect_observations WHERE effect_id=?").get(args.effect_id as string) as { payload: string } | null;
          requireThat(original, "effect_observation_required");
          const observation = JSON.parse(original.payload);
          requireThat(observation.terminal === true && observation.evidence?.observation_digest === result.evidence.observation_digest, "device_result_observation_mismatch");
          const handle = result.native_session as Record<string, unknown>;
          requireThat(handle.device_id === device.device_id && digest(handle.evidence) === digest(result.evidence), "device_native_handle_mismatch");
          const effect = this.kernel.db.sql.query("SELECT state FROM effects WHERE effect_id=?").get(args.effect_id as string) as { state: string };
          requireThat(Boolean(manifest.mailbox_delivery) === Boolean(result.mailbox_delivery), "native_mailbox_proof_required");
          if (manifest.mailbox_delivery) {
            const delivery = this.nativeDelivery.verifyDevice(actor, lease.task_id, manifest.mailbox_delivery, result.mailbox_delivery);
            if (effect.state !== "confirmed") this.nativeDelivery.consume(actor, lease, args.effect_id as string, delivery.batch, delivery.verified);
          }
          requireThat(Boolean(manifest.communication) === Boolean(result.communication), "native_agent_proof_required");
          if (manifest.communication) {
            const scope = decodeNativeAgentScope(manifest.communication), journal = new NativeAgentJournal(this.kernel);
            // Exact completion replay is checked by the existing kernel command receipts below.
            if (effect.state === "confirmed") journal.verifyDevice(args.effect_id as string, scope, result.communication);
            else journal.consumeDevice(actor, lease, args.effect_id as string, scope, result.communication);
          }
        }
        const observed = this.kernel.db.sql.query("SELECT result FROM effects WHERE effect_id=? AND episode_id=? AND fence=?")
          .get(args.effect_id as string, lease.episode_id, lease.fence) as { result: string | null } | null;
        requireThat(observed && observed.result !== null, "effect_observation_required");
        this.kernel.confirmEffect(actor, `${request}:effect`, lease, args.effect_id as string, args.result);
        const result = this.kernel.finish(actor, request, lease, "done", args.result as Record<string, unknown>);
        return { task_id: result.task.task_id, status: result.task.status, revision: result.revision };
      });
    }
    return this.kernel.withLease(actor, lease, () => {
      switch (input.operation) {
        case "start": this.kernel.start(actor, request, lease); return this.window(actor, lease);
        case "renew": return this.window(actor, this.kernel.renew(actor, request, lease, args.ttl_ms as number));
        case "native_input": {
          requireThat(nativeProvider(job.execution?.provider) && typeof job.execution?.prompt === "string"
            && job.execution.prompt.length > 0 && Buffer.byteLength(job.execution.prompt) <= 32768, "native_device_input_unavailable");
          return this.nativeDelivery.prepare(actor, lease, job.execution.prompt) ?? null;
        }
        case "dispatch": {
          const manifest = args.manifest as Record<string, unknown> | undefined;
          requireThat(!nativeProvider(job.execution?.provider) || manifest, "device_native_manifest_required");
          if (manifest) requireThat(manifest.device_id === device.device_id && manifest.task_id === job.task_id
            && manifest.episode_id === lease.episode_id && manifest.fence === lease.fence && manifest.effect_id === args.effect_id
            && manifest.assignment_digest === job.assignment_digest && !manifest.observation_digest && !manifest.result_digest, "device_manifest_binding_mismatch");
          assertDeviceWorkspaceGrant(manifest?.workspace_write, job.execution?.tool_grant);
          if (manifest?.communication) {
            const scope = decodeNativeAgentScope(manifest.communication);
            requireThat(scope.task_id === job.task_id && scope.episode_id === lease.episode_id && scope.fence === lease.fence
              && digest(scope.peer_tasks) === digest(job.peer_tasks ?? []) && scope.parent_task === (job.parent_task ?? null), "native_agent_assignment_changed");
          }
          const delivery = manifest?.mailbox_delivery ? this.nativeDelivery.resolveBinding(actor, lease.task_id, manifest.mailbox_delivery) : undefined;
          if (nativeProvider(job.execution?.provider)) this.nativeDelivery.assertRequiredInput(actor, lease, delivery);
          if (delivery) {
            requireThat(nativeProvider(job.execution?.provider) && typeof job.execution?.prompt === "string", "native_device_input_unavailable");
            nativeInput(job.execution.prompt, delivery);
          }
          // Prepared native adapters start and dispatch together after their device-local manifest is durable.
          const episode = this.kernel.db.sql.query("SELECT state FROM episodes WHERE episode_id=?").get(lease.episode_id) as { state: string };
          if (episode.state === "leased") this.kernel.start(actor, `${request}:start`, lease);
          const permit = this.kernel.dispatchEffect(actor, request, lease, args.effect_id as string, args.intent, manifest);
          if (permit.dispatch_permitted && delivery) this.nativeDelivery.reserve(actor, lease, args.effect_id as string, delivery);
          return permit;
        }
        case "observe": {
          if (nativeProvider(job.execution?.provider)) {
            const manifest = this.nativeManifest(lease, args.effect_id as string);
            assertProtocolSchema("device-observation.schema.json", args.observation);
            const observation = args.observation as Record<string, unknown>;
            this.evidenceMatches(manifest, observation.evidence);
            requireThat(observation.evidence.observation_digest && !observation.evidence.result_digest, "device_observation_evidence_missing");
          }
          return this.kernel.recordEffectObservation(actor, request, lease, args.effect_id as string, args.observation);
        }
        case "unknown": {
          const result = this.kernel.markUnknown(actor, request, lease, args.reason as string);
          return { task_id: result.task.task_id, status: result.task.status, revision: result.revision };
        }
        case "messages": return this.mailbox.pending(actor, lease);
        case "send":
          // Cross-device peers are explicit. Execution access to the recipient is neither needed nor granted.
          const source = this.kernel.db.sql.query("SELECT specification FROM device_assignments WHERE task_id=?").get(lease.task_id) as { specification: string };
          requireThat((JSON.parse(source.specification) as DeviceAssignment).peer_tasks?.includes(args.recipient_task as string), "peer_not_authorized");
          return this.mailbox.send(actor, request, { recipient_task: args.recipient_task as string, sender_lease: lease,
            kind: args.kind as SendMessage["kind"], payload: args.payload as Record<string, unknown>, causation_id: args.causation_id as string | null, ttl_ms: args.ttl_ms as number });
        case "ack": return this.mailbox.acknowledge(actor, request, lease, args.message_id as string, args.phase as "received" | "consumed", args.evidence as string | null);
      }
    });
  }

  /** Long receive waits hold no SQLite transaction. Calls remain tied to the original dispatch. */
  private async nativeCall(device: DeviceRegistration, input: DeviceCommand, signal: AbortSignal): Promise<Record<string, unknown>> {
    const args = input.arguments, lease = args.lease as Lease, effect = args.effect_id as string;
    const tool = args.tool as string, value = args.input as Record<string, unknown>;
    const actor = this.actor(device), journal = new NativeAgentJournal(this.kernel);
    const scope = decodeNativeAgentScope(this.nativeManifest(lease, effect).communication);
    const current = () => {
      signal.throwIfAborted();
      const job = this.assignment(device, lease.task_id);
      requireThat(digest(job.peer_tasks ?? []) === digest(scope.peer_tasks) && (job.parent_task ?? null) === scope.parent_task, "native_agent_assignment_changed");
      journal.assertExecution(actor, lease, effect, scope);
    };
    current(); identifier(value.request_id);
    const key = digest([device.device_id, effect, value.request_id]), hash = digest({ tool, value }), previous = this.nativeCalls.get(key);
    if (previous) {
      requireThat(hash === previous.digest, "idempotency_conflict");
      const response = await previous.promise; current(); return response;
    }
    const begun = journal.begin(actor, lease, effect, scope, tool, value);
    if (begun.response) { current(); return begun.response; }
    const execute = async () => {
      const wait = tool === "controlmesh_receive" && Number.isSafeInteger(value.wait_ms) && Number(value.wait_ms) <= 10000 ? Number(value.wait_ms) : 0;
      const deadline = performance.now() + Math.max(0, wait);
      while (performance.now() < deadline && !journal.available(actor, lease)) {
        current(); await delay(Math.min(100, Math.max(1, deadline - performance.now())), undefined, { signal });
      }
      current(); return journal.finish(actor, lease, effect, scope, begun.call_id);
    };
    const promise = execute(); this.nativeCalls.set(key, { digest: hash, promise });
    try { const response = await promise; current(); return response; }
    finally { this.nativeCalls.delete(key); }
  }

  async handle(request: Request): Promise<Response> {
    let device: DeviceRegistration | undefined;
    let counted = false;
    let requestId: string | null = null;
    try {
      requireThat(new URL(request.url).pathname === "/worker/v1/command" && !new URL(request.url).search, "route_unavailable");
      requireThat(request.method === "POST" && !request.headers.has("Origin") && !request.headers.has("Sec-Fetch-Site"), "machine_transport_required");
      device = this.authenticate(request);
      const active = this.pending.get(device.device_id) ?? 0;
      requireThat(active < 8, "device_backpressure");
      const now = performance.now();
      let rate = this.rates.get(device.device_id);
      if (!rate || now - rate.since >= 1000) { rate = { since: now, count: 0 }; this.rates.set(device.device_id, rate); }
      requireThat(++rate.count <= 64, "device_backpressure");
      this.pending.set(device.device_id, active + 1); counted = true;
      requireThat(request.headers.get("Content-Type")?.split(";", 1)[0] === "application/json" && !request.headers.has("Content-Encoding"), "json_body_required");
      const length = request.headers.get("Content-Length");
      requireThat(length === null || (/^\d+$/.test(length) && Number(length) <= MAX_BODY), "body_too_large");
      requireThat(request.body, "invalid_command");
      const reader = request.body.getReader();
      const chunks: Uint8Array[] = [];
      let bytes = 0;
      let expired = false;
      const timer = setTimeout(() => { expired = true; void reader.cancel().catch(() => {}); }, 3000);
      try {
        while (true) {
          const next = await reader.read();
          requireThat(!expired, "body_deadline");
          if (next.done) break;
          bytes += next.value.length;
          requireThat(bytes <= MAX_BODY, "body_too_large");
          chunks.push(next.value);
        }
      } finally { clearTimeout(timer); void reader.cancel().catch(() => {}); }
      const input: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(Buffer.concat(chunks)));
      assertProtocolSchema<DeviceCommand>("device-command.schema.json", input);
      // Complete uses a namespaced second receipt; bound it before executing either operation.
      requireThat(input.request_id.length <= 180, "invalid_identifier");
      canonical(input);
      requestId = input.request_id;
      this.authenticate(request); // Credentials may have been revoked while reading a slow body.
      const data = input.operation === "native_call" ? await this.nativeCall(device, input, request.signal)
        : this.kernel.db.transaction(() => this.execute(device!, input));
      return json({ schema_version: "controlmesh.device_response.v1", request_id: requestId, ok: true, data });
    } catch (error) {
      const code = error instanceof RuntimeConflict ? error.code : error instanceof ProtocolValidationError || error instanceof SyntaxError || error instanceof TypeError ? "invalid_command" : "internal_error";
      const status = code === "unauthorized" ? 401 : code === "device_backpressure" ? 429 : code === "internal_error" ? 500 : 409;
      return json({ schema_version: "controlmesh.device_response.v1", request_id: requestId, ok: false, error: code }, status);
    } finally {
      if (counted && device) this.pending.set(device.device_id, (this.pending.get(device.device_id) ?? 1) - 1);
    }
  }

  /** Explicit start only; loopback transport is carried to other devices by a pinned SSH tunnel. */
  listen(port = 0): Bun.Server<undefined> {
    return Bun.serve({ hostname: "127.0.0.1", port, maxRequestBodySize: MAX_BODY, idleTimeout: 15, fetch: request => this.handle(request) });
  }
}
