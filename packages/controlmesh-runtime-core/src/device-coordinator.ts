import { createHash, timingSafeEqual } from "node:crypto";
import { assertProtocolSchema, ProtocolValidationError, type DeviceCommand, type DeviceLeaseWindow } from "@controlmesh/protocol";
import { command, requireScope } from "./commands";
import { RuntimeKernel, type Lease, type Principal, type TaskSnapshot } from "./kernel";
import { AgentMailbox, type SendMessage } from "./mailbox";
import { canonical, digest, identifier, object, requireThat, RuntimeConflict } from "./value";

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
}
export interface DeviceJob {
  task_id: string;
  revision: number;
  status: string;
  workspace_id: string;
  capability: string;
  input: Record<string, unknown>;
  assignment_digest: string;
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

  constructor(readonly kernel: RuntimeKernel, registrations: readonly DeviceRegistration[]) {
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
    for (const id of specification.device_ids) {
      const device = this.devices.get(id);
      requireThat(device && device.principal_id === actor.id && !this.revoked(id), "device_not_authorized");
      requireThat(device.capabilities.includes(specification.capability) && device.workspace_ids.includes(specification.workspace_id), "device_capability_unavailable");
    }
    // Native databases and credentials stay on their issuing device; no implicit cross-device transcript replay.
    const native = snapshot.task.native_session;
    requireThat(!native || (object(native) && specification.device_ids.every(id => id === native.device_id)), "native_session_device_bound");
    command(this.kernel.db, actor, requestId, "device.assign", { taskId, revision, specification }, () => {
      const current = this.kernel.inspect(actor, taskId);
      requireThat(current.revision === revision && current.task.status === "waiting" && !current.active_episode && !current.needs_reconciliation, "task_not_assignable");
      this.kernel.db.sql.query("INSERT INTO device_assignments VALUES (?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET principal=excluded.principal,authority_digest=excluded.authority_digest,specification=excluded.specification")
        .run(taskId, actor.id, taskAuthority(current), canonical(specification));
      this.kernel.db.sql.query("INSERT INTO events (task_id,kind,revision,fence,principal,origin,at,payload) VALUES (?,'device.assigned',?,?,?,?,?,?)")
        .run(taskId, current.revision, current.fence, actor.id, actor.origin, this.kernel.db.now(), canonical({ assignment_digest: digest(specification) }));
      return { assigned: true };
    });
  }

  private actor(device: DeviceRegistration): Principal {
    return { id: device.principal_id, device_id: device.device_id, origin: "agent_message", scopes: workerScopes };
  }

  private assignment(device: DeviceRegistration, taskId: string): DeviceJob {
    requireThat(!this.revoked(device.device_id), "device_revoked");
    identifier(taskId);
    const row = this.kernel.db.sql.query("SELECT * FROM device_assignments WHERE task_id=? AND principal=?").get(taskId, device.principal_id) as AssignmentRow | null;
    requireThat(row, "assignment_unavailable");
    const specification = JSON.parse(row.specification) as DeviceAssignment;
    requireThat(specification.device_ids.includes(device.device_id), "assignment_unavailable");
    requireThat(device.capabilities.includes(specification.capability) && device.workspace_ids.includes(specification.workspace_id), "device_capability_unavailable");
    const task = this.kernel.inspect(this.actor(device), taskId);
    requireThat(taskAuthority(task) === row.authority_digest, "assignment_authority_changed");
    return { task_id: taskId, revision: task.revision, status: task.task.status, workspace_id: specification.workspace_id,
      capability: specification.capability, input: specification.input, assignment_digest: digest(specification) };
  }

  private authenticate(request: Request): DeviceRegistration {
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

  private execute(device: DeviceRegistration, input: DeviceCommand): unknown {
    requireThat(!this.revoked(device.device_id), "unauthorized");
    const actor = this.actor(device);
    const args = input.arguments;
    const request = input.request_id;
    // JSON Schema validates the discriminated arguments before these casts.
    if (input.operation === "queue") {
      const rows = this.kernel.db.sql.query("SELECT a.task_id FROM device_assignments a JOIN tasks t ON a.task_id=t.task_id WHERE a.principal=? AND t.status='waiting' AND t.needs_reconciliation=0 ORDER BY a.task_id LIMIT 1024").all(actor.id) as { task_id: string }[];
      const jobs: DeviceJob[] = [];
      for (const row of rows) {
        try { jobs.push(this.assignment(device, row.task_id)); } catch (error) { if (!(error instanceof RuntimeConflict)) throw error; }
        if (jobs.length === 32) break;
      }
      return jobs;
    }
    if (input.operation === "inspect" || input.operation === "claim") {
      const job = this.assignment(device, args.task_id as string);
      if (input.operation === "inspect") return job;
      requireThat(args.assignment_digest === job.assignment_digest, "assignment_revision_conflict");
      return this.window(actor, this.kernel.claim(actor, request, job.task_id, args.revision as number, args.ttl_ms as number));
    }
    const lease = args.lease as Lease;
    this.assignment(device, lease.task_id);
    if (input.operation === "complete") {
      // Commit verification receipt and task outcome together. Exact lost-response replay is safe;
      // conflicting/late new results still pass the kernel's fence and lease checks.
      return this.kernel.db.transaction(() => {
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
        case "dispatch": return this.kernel.dispatchEffect(actor, request, lease, args.effect_id as string, args.intent);
        case "observe": return this.kernel.recordEffectObservation(actor, request, lease, args.effect_id as string, args.observation);
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
      const data = this.kernel.db.transaction(() => this.execute(device!, input));
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
    return Bun.serve({ hostname: "127.0.0.1", port, maxRequestBodySize: MAX_BODY, idleTimeout: 5, fetch: request => this.handle(request) });
  }
}
