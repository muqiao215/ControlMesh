import { nativeTaskOutcome } from "./native-task-failure";
import { uploadDeviceArtifacts } from "./device-artifact-upload";
import { randomUUID } from "node:crypto";
import { lstatSync, realpathSync } from "node:fs";
import { isAbsolute } from "node:path";
import { assertProtocolSchema, type DeviceEvidenceRef, type DeviceReconciliationChallenge, type DeviceReconciliationReport } from "@controlmesh/protocol";
import type { DeviceJob } from "./device-coordinator";
import { DeviceClient, type DeviceLeaseAuthority } from "./device-client";
import { DeviceExecutionJournal } from "./device-journal";
import { canonical, digest, identifier, object, requireThat, RuntimeConflict } from "./value";
import { ExecutionPolicyDenied } from "./execution-policy";
import { ToolGrantDenied } from "./execution-grants";
import { ProcessSupervisor, type ProcessSpec, type ProcessOutcome } from "./process-supervisor";
import { decodeNativeMailbox, nativeInput, type NativeMailboxBatch } from "./providers/native-mailbox-input";
import { ProviderPreparationWait } from "./providers/preflight-service";

export interface DeviceRunAdmission { signal: AbortSignal; assertCurrent(): void }
export interface DeviceRunOutcome { status: "done" | "failed" | "unknown" | "unavailable"; reason?: string; retry_after?: number | null; result?: Record<string, unknown> }

export interface DeviceAdapterContext {
  job: DeviceJob;
  workspace: string;
  authority: DeviceLeaseAuthority;
  assertCurrent: () => void;
  effect_id: string;
  preparePublication: () => Promise<void>;
  mailboxInput: () => Promise<NativeMailboxBatch | undefined>;
  nativeCall: (tool: string, input: Record<string, unknown>, signal: AbortSignal) => Promise<Record<string, unknown>>;
  runProcess: (spec: Omit<ProcessSpec, "cwd">) => Promise<ProcessOutcome>;
  dispatch: (manifest: Record<string, unknown>, intent: Record<string, unknown>) => Promise<DeviceEvidenceRef>;
  observe: (observation: Record<string, unknown>) => Promise<DeviceEvidenceRef>;
  retainVerifiedResult: (result: Record<string, unknown>) => DeviceEvidenceRef;
}
export interface DeviceAdapter {
  /** A prepared adapter must durably dispatch and observe through the supplied context before returning. */
  dispatch_mode?: "prepared";
  readiness?(): Record<string, unknown>;
  retryReadiness?(requestId: string, expectedGeneration: number): Record<string, unknown>;
  /** Must verify its native result; returning only an exit code is not semantic acceptance. */
  execute(context: DeviceAdapterContext): Promise<{ observation: Record<string, unknown>; result: Record<string, unknown> }>;
  reconcile?(challenge: DeviceReconciliationChallenge, workspace: string, assertCurrent: () => void,
    report: (value: DeviceReconciliationReport) => Promise<unknown>, preparePublication?: () => Promise<void>): Promise<unknown>;
}
export interface DeviceWorkerOptions {
  workspaces: Readonly<Record<string, string>>;
  adapters: Readonly<Record<string, DeviceAdapter | DeviceAdapterFactory>>;
  journal?: DeviceExecutionJournal;
  signal?: AbortSignal;
}
/** A factory is registered locally; task text and transport input cannot choose executable code. */
export type DeviceAdapterFactory = (job: DeviceJob, workspace: string) => DeviceAdapter;

/** No shell strings or paths from the coordinator select executable code. Both maps are local configuration. */
export class DeviceWorker {
  private readonly workspaces = new Map<string, { path: string; dev: number; ino: number }>();
  private readonly adapters: DeviceWorkerOptions["adapters"];
  private readonly journal?: DeviceExecutionJournal;
  private readonly signal?: AbortSignal;

  constructor(private readonly client: DeviceClient, options: DeviceWorkerOptions) {
    this.adapters = { ...options.adapters };
    this.journal = options.journal;
    this.signal = options.signal;
    requireThat(!this.journal || this.journal.deviceId === client.deviceId, "device_journal_identity_mismatch");
    for (const [id, path] of Object.entries(options.workspaces)) {
      identifier(id);
      requireThat(isAbsolute(path) && realpathSync(path) === path, "workspace_must_be_canonical");
      const stat = lstatSync(path);
      requireThat(stat.isDirectory(), "invalid_worker_workspace");
      this.workspaces.set(id, { path, dev: stat.dev, ino: stat.ino });
    }
  }

  private adapter(job: DeviceJob, workspace: string): DeviceAdapter | undefined {
    const selected = Object.hasOwn(this.adapters, job.capability) ? this.adapters[job.capability] : undefined;
    return typeof selected === "function" ? selected(structuredClone(job), workspace) : selected;
  }

  /** Private operator inspection/reset; never launches a native process or changes task state. */
  async readiness(taskId: string, retry?: { request_id: string; expected_generation: number }): Promise<Record<string, unknown>> {
    requireThat(!this.signal?.aborted, "device_worker_stopped");
    const job = await this.client.inspect(taskId), workspace = this.workspaces.get(job.workspace_id);
    requireThat(workspace && realpathSync(workspace.path) === workspace.path, "local_capability_unavailable");
    const stat = lstatSync(workspace.path); requireThat(stat.dev === workspace.dev && stat.ino === workspace.ino, "worker_workspace_changed");
    const adapter = this.adapter(job, workspace.path); requireThat(adapter?.readiness, "provider_readiness_unavailable");
    if (retry) { requireThat(adapter.retryReadiness, "provider_retry_unavailable"); return adapter.retryReadiness(retry.request_id, retry.expected_generation); }
    return adapter.readiness();
  }

  /** Explicit request ID only: no unknown-task scan, new lease, provider probe or automatic execution. */
  async reconcile(challengeId: string): Promise<unknown> {
    requireThat(!this.signal?.aborted, "device_worker_stopped");
    const receipt = (value: unknown) => {
      requireThat(object(value) && value.challenge_id === challengeId && (value.status === "done" || value.status === "failed") && Number.isSafeInteger(value.revision), "invalid_reconciliation_response");
      assertProtocolSchema<DeviceEvidenceRef>("device-evidence-ref.schema.json", value.evidence);
      requireThat(value.evidence.device_id === this.client.deviceId && value.evidence.task_id === value.task_id && this.journal, "reconciliation_device_mismatch");
      const retained = this.journal.inspect(value.evidence);
      requireThat(retained.result && value.status === nativeTaskOutcome(JSON.parse(retained.result)), "invalid_reconciliation_response");
      this.journal.acknowledgeReconciliation(value.evidence);
      return value;
    };
    const sent = this.client.clock();
    const value = await this.client.command("reconciliation", { challenge_id: challengeId });
    requireThat(object(value), "invalid_reconciliation_response");
    if (value.state === "accepted") {
      return receipt(value.receipt);
    }
    requireThat(value.state === "pending" && Number.isSafeInteger(value.remaining_ms) && Number(value.remaining_ms) > 0 && Number(value.remaining_ms) <= 30_000, "invalid_reconciliation_response");
    assertProtocolSchema<DeviceReconciliationChallenge>("device-reconciliation-challenge.schema.json", value.challenge);
    const challenge = value.challenge, issued = digest(challenge);
    requireThat(challenge.challenge_id === challengeId && challenge.manifest.device_id === this.client.deviceId, "reconciliation_device_mismatch");
    const workspace = this.workspaces.get(challenge.workspace_id);
    requireThat(workspace && this.journal, "local_reconciliation_unavailable");
    const saved = this.journal.inspect(challenge.manifest), job = JSON.parse(saved.job) as DeviceJob;
    requireThat(job.workspace_id === challenge.workspace_id && job.capability === challenge.capability
      && job.execution_digest === challenge.execution_digest, "reconciliation_authority_changed");
    const deadline = sent + Number(value.remaining_ms) - 50;
    let last = sent;
    const current = () => {
      requireThat(!this.signal?.aborted, "device_worker_stopped");
      const now = this.client.clock();
      requireThat(Number.isFinite(now) && now >= last && now < deadline, "reconciliation_expired"); last = now;
      const stat = lstatSync(workspace.path);
      requireThat(stat.isDirectory() && !stat.isSymbolicLink() && realpathSync(workspace.path) === workspace.path && stat.dev === workspace.dev && stat.ino === workspace.ino, "worker_workspace_changed");
      requireThat(digest(challenge) === issued, "reconciliation_challenge_changed");
    };
    current();
    const adapter = this.adapter(job, workspace.path);
    requireThat(adapter?.reconcile, "local_reconciliation_unavailable");
    current();
    return adapter.reconcile(challenge, workspace.path, current, async report => {
      current();
      if (job.artifact_transfer && nativeTaskOutcome(report.result as unknown as Record<string, unknown>) === "done") {
        await uploadDeviceArtifacts(job, workspace.path, challenge.manifest.effect_id, report.result.completion, current,
          (chunk, id) => this.client.command("artifact_reconcile_put", { challenge_id: challengeId, ...chunk }, id, this.signal));
      }
      current();
      const result = await this.client.command("reconcile", { report }, `device-reconcile-${challengeId}`);
      requireThat(object(result) && result.task_id === challenge.manifest.task_id && digest(result.evidence) === digest(report.result.evidence), "invalid_reconciliation_response");
      return receipt(result);
    }, async () => {
      current();
      const refreshed = await this.client.command("reconciliation", { challenge_id: challengeId });
      current();
      requireThat(object(refreshed) && refreshed.state === "pending" && digest(refreshed.challenge) === issued
        && Number.isSafeInteger(refreshed.remaining_ms) && Number(refreshed.remaining_ms) > 0, "reconciliation_authority_changed");
    });
  }

  async run(taskId: string, ttlMs = 10_000, expected?: { revision: number; assignment_digest: string }, admission?: DeviceRunAdmission): Promise<DeviceRunOutcome> {
    const signal = this.signal && admission ? AbortSignal.any([this.signal, admission.signal]) : admission?.signal ?? this.signal;
    requireThat(!signal?.aborted, "device_worker_stopped");
    const job = await this.client.inspect(taskId), issuedJob = digest(job);
    requireThat(!expected || (job.revision === expected.revision && job.assignment_digest === expected.assignment_digest), "device_assignment_changed");
    const workspace = this.workspaces.get(job.workspace_id);
    requireThat(workspace, "local_capability_unavailable");
    const assertWorkspace = () => {
      requireThat(!signal?.aborted, "device_worker_stopped");
      const checked: unknown = admission?.assertCurrent();
      if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
      const stat = lstatSync(workspace.path);
      requireThat(stat.isDirectory() && !stat.isSymbolicLink() && realpathSync(workspace.path) === workspace.path && stat.dev === workspace.dev && stat.ino === workspace.ino, "worker_workspace_changed");
      requireThat(digest(job) === issuedJob, "device_job_changed");
    };
    assertWorkspace();
    const adapter = this.adapter(job, workspace.path);
    requireThat(adapter && typeof adapter.execute === "function", "local_capability_unavailable");
    const preparedMode = adapter.dispatch_mode === "prepared", journal = this.journal;
    requireThat(!preparedMode || journal, "durable_device_journal_required");
    assertWorkspace();
    const authority = await this.client.claim(taskId, job.revision, job.assignment_digest, ttlMs);
    const abort = () => authority.stop();
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) abort();
    const assertCurrent = () => { authority.assertCurrent(); assertWorkspace(); };
    const effect = randomUUID();
    let attempted = false, dispatched = false, prepared = false, verified = false;
    let observedDigest: string | undefined;
    let renewal: Promise<void> | undefined;
    let closed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const arm = () => {
      if (closed) return;
      timer = setTimeout(() => {
        renewal = authority.renew().catch(() => { closed = true; authority.stop(); }).finally(() => { renewal = undefined; arm(); });
      }, Math.max(100, Math.floor(ttlMs / 4)));
    };
    const dispatch = async (intent: Record<string, unknown>, manifest?: DeviceEvidenceRef) => {
      assertCurrent();
      requireThat(!attempted, "device_dispatch_already_attempted");
      if (manifest) journal!.dispatching(effect);
      attempted = true;
      const permit = await this.client.command("dispatch", { lease: authority.lease, effect_id: effect, intent, ...(manifest ? { manifest } : {}) }, `device-${effect}-dispatch`);
      requireThat(object(permit) && permit.effect_id === effect && permit.dispatch_permitted === true, "effect_dispatch_not_permitted");
      if (manifest) journal!.dispatched(effect);
      dispatched = true;
      assertCurrent();
    };
    try {
      if (!preparedMode) { attempted = true; await authority.start(); attempted = false; }
      arm();
      assertCurrent();
      if (!preparedMode) await dispatch({ capability: job.capability, workspace_id: job.workspace_id, input_digest: digest(job.input) });
      const output = await adapter.execute({ job, workspace: workspace.path, authority, assertCurrent, effect_id: effect,
        preparePublication: async () => {
          assertCurrent(); requireThat(preparedMode && dispatched && observedDigest && !verified && !closed, "device_publication_unavailable");
          // Serialize the explicit publication refresh with the normal heartbeat.
          if (timer) clearTimeout(timer);
          await renewal;
          if (timer) clearTimeout(timer);
          assertCurrent();
          await authority.renew();
          assertCurrent(); arm();
        },
        mailboxInput: async () => {
          assertCurrent(); requireThat(preparedMode && !prepared && !attempted, "device_native_input_unavailable");
          const response = await this.client.command("native_input", { lease: authority.lease });
          assertCurrent();
          if (response === null) return undefined;
          const batch = decodeNativeMailbox(response);
          requireThat(batch.task_id === job.task_id && typeof job.execution?.prompt === "string", "native_mailbox_task_mismatch");
          nativeInput(job.execution.prompt, batch);
          return batch;
        },
        nativeCall: async (tool, input, signal) => {
          assertCurrent(); requireThat(preparedMode && dispatched && !verified, "device_native_channel_unavailable");
          const response = await this.client.command("native_call", { lease: authority.lease, effect_id: effect, tool, input },
            `device-call-${digest([effect, input.request_id])}`, AbortSignal.any([signal, authority.signal]));
          assertCurrent();
          requireThat(object(response) && typeof response.ok === "boolean" && response.call_id === digest([effect, input.request_id])
            && Buffer.byteLength(canonical(response)) <= 16384, "invalid_native_agent_response");
          return response;
        },
        runProcess: spec => new ProcessSupervisor().run({ ...spec, cwd: workspace.path }, { assertCurrent, remainingMs: authority.remainingMs, signal: authority.signal }),
        dispatch: async (manifest, intent) => {
          requireThat(preparedMode && !prepared && !attempted, "device_preparation_not_available");
          assertCurrent();
          const ref = journal!.prepare(job, authority.lease, effect, manifest); prepared = true;
          await dispatch(intent, ref);
          return ref;
        },
        observe: async observation => {
          requireThat(preparedMode && dispatched && observedDigest === undefined, "device_observation_not_available");
          // Retain the actual observation even if authority or connectivity was lost during native execution.
          const ref = journal!.observe(effect, observation); observedDigest = digest(observation);
          assertCurrent();
          await this.client.command("observe", { lease: authority.lease, effect_id: effect,
            observation: { schema_version: "controlmesh.device_observation.v1", evidence: ref, terminal: observation.terminal === true } }, `device-${effect}-observe`);
          return ref;
        },
        retainVerifiedResult: result => {
          requireThat(preparedMode && dispatched && observedDigest && !verified, "device_verification_not_available");
          assertCurrent();
          const ref = journal!.verify(effect, result); verified = true;
          return ref;
        },
      });
      assertCurrent();
      requireThat(dispatched, "device_dispatch_missing");
      if (preparedMode) requireThat(verified && observedDigest === digest(output.observation), "device_result_not_verified");
      else await this.client.command("observe", { lease: authority.lease, effect_id: effect, observation: output.observation });
      requireThat(Buffer.byteLength(canonical(output.result)) <= 128 * 1024, "device_result_too_large");
      if (job.artifact_transfer && nativeTaskOutcome(output.result) === "done") {
        requireThat(preparedMode && verified, "device_artifact_native_verification_required");
        await uploadDeviceArtifacts(job, workspace.path, effect, output.result.completion, assertCurrent,
          (chunk, id) => this.client.command("artifact_put", { lease: authority.lease, effect_id: effect, ...chunk }, id, signal));
      }
      // Drain renewal before terminal commit; a successful completion must not race a late renewal error.
      closed = true;
      if (timer) clearTimeout(timer);
      await renewal;
      assertCurrent();
      const completion = await this.client.command("complete", { lease: authority.lease, effect_id: effect, result: output.result }, `device-${effect}-complete`);
      requireThat(object(completion) && completion.task_id === taskId && completion.status === nativeTaskOutcome(output.result), "completion_unproven");
      if (prepared) journal!.completed(effect);
      return { status: nativeTaskOutcome(output.result), ...(output.result.task_failure ? { reason: "workspace_tool_required_read_missing" } : {}), result: output.result };
    } catch (error) {
      const reason = error instanceof ProviderPreparationWait ? error.decision.reason : error instanceof RuntimeConflict ? error.code : error instanceof ExecutionPolicyDenied ? error.decision.reason_code
        : error instanceof ToolGrantDenied ? error.reason_code : "device_preparation_unavailable";
      if (prepared) { try { journal!.unknown(effect); } catch { /* preserve the original durable record if storage is unavailable */ } }
      if (preparedMode && attempted && !dispatched) {
        // The coordinator atomically checks no dispatch occurred and advances the fence.
        // A delayed dispatch request then fails; an already started episode cannot release.
        try {
          const released = await this.client.command("release", { lease: authority.lease, reason });
          requireThat(object(released) && released.task_id === taskId && released.status === "waiting", "device_release_unproven");
          if (prepared) journal!.released(effect);
          return { status: "unavailable", reason };
        } catch { /* unresolved transport/started effect still requires outcome reconciliation below */ }
      }
      if (attempted) {
        // A lost dispatch or completion response is uncertain. Never repeat a native operation here.
        try { await this.client.command("unknown", { lease: authority.lease, reason: dispatched ? "worker_outcome_unproven" : "worker_admission_unproven" }); } catch { /* coordinator expiry recovery retains uncertainty */ }
      } else {
        try {
          const release = await this.client.command("release", { lease: authority.lease, reason });
          if (error instanceof ProviderPreparationWait && object(release) && release.task_id === taskId && release.status === "waiting") {
            return { status: "unavailable", reason, retry_after: error.decision.retry_after };
          }
        } catch { /* unstarted expiry recovery is safe if the response is lost */ }
      }
      return attempted ? { status: "unknown" } : { status: "unavailable", reason };
    } finally {
      closed = true;
      if (timer) clearTimeout(timer);
      authority.stop();
      signal?.removeEventListener("abort", abort);
      await renewal;
    }
  }
}
