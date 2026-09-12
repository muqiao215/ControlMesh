import { assertProtocolSchema, type DeviceNativeResult } from "@controlmesh/protocol";
import { topologyExecution } from "./topology-execution";
import { readAggregateResult } from "./topology-aggregate";
import { teamWorkerSubstage } from "./team-task-result";
import { isAbsolute, join } from "node:path";
import type { Principal, RuntimeKernel } from "./kernel";
import type { TopologySnapshot } from "./runtime-topology";
import { requireScope } from "./commands";
import { decodeTopologyState } from "./team-topology";
import { decodeTaskCompletion, deviceCompletionProof, verifyDeviceCompletion, type TaskCompletion } from "./task-completion";
import { directoryIdentity, snapshotReads } from "./providers/native-manifest";
import type { SpecMeshPort, SpecMeshObservation } from "./specmesh-port";
import { canonical, digest, identifier, object, requireThat, RuntimeConflict } from "./value";

export interface TopologyArtifactConfiguration {
  /** Canonical destination: files must already exist here; this verifier never transfers them. */
  workspace: string;
  allowed_files: readonly string[];
  /** Explicit remote provenance allowed for this destination: device ID -> logical workspace ID. */
  device_sources?: Readonly<Record<string, string>>;
}
interface Witness {
  child_id: string; generation: number; episode_id: string; effect_id: string; path: string; mode: "read" | "write"; sha256: string;
  source?: { kind: "device"; device_id: string; workspace_id: string; assignment_digest: string; manifest_digest: string };
}
export interface TopologyArtifactEvidence {
  schema_version: "controlmesh.topology_artifacts.v1"; requirements_digest: string; workspace_binding: string;
  files: { path: string; mode: "read" | "write"; sha256: string; witness: Witness }[];
  specmesh: { operation: "check"; binding_digest: string; snapshot_digest: string; result_digest: string; source_sha256: string } | null;
}
export interface TopologyCompletionPermit { readonly evidence: TopologyArtifactEvidence }
const permits = new WeakMap<object, { kernel: RuntimeKernel; actor: string; task_id: string; parent_revision: number; topology_revision: number; evidence_digest: string; current(): void }>();
const identity = (actor: Principal) => digest({ id: actor.id, device_id: actor.device_id ?? null, origin: actor.origin });
interface Prepared {
  task_id: string; parent_revision: number; topology_revision: number; parent_digest: string;
  state: ReturnType<typeof decodeTopologyState>; witness_digest: string; files: ReturnType<typeof snapshotReads>;
  evidence: TopologyArtifactEvidence; observation?: SpecMeshObservation;
}
/** Trusted local read-only verification profile. It does not issue an Agent file grant or run a model. */
export class TopologyArtifactGate {
  private readonly workspace: ReturnType<typeof directoryIdentity>;
  private readonly allowed: readonly string[];
  private readonly devices: Readonly<Record<string, string>>;
  private readonly prepared = new Map<string, Prepared>();
  readonly binding_digest: string;
  constructor(readonly kernel: RuntimeKernel, config: TopologyArtifactConfiguration, private readonly authorize: () => void, private readonly specmesh?: SpecMeshPort) {
    requireThat(isAbsolute(config.workspace), "topology_artifact_workspace_required");
    this.workspace = directoryIdentity(config.workspace);
    requireThat(this.workspace.path === config.workspace && config.allowed_files.length > 0 && config.allowed_files.length <= 80
      && new Set(config.allowed_files).size === config.allowed_files.length, "invalid_topology_artifact_profile");
    for (const path of config.allowed_files) decodeTaskCompletion({ schema_version: "controlmesh.task_completion.v1", files: [{ path, mode: "read" }] });
    this.allowed = [...config.allowed_files];
    requireThat(config.device_sources === undefined || (object(config.device_sources) && Object.keys(config.device_sources).length > 0
      && Object.keys(config.device_sources).length <= 128), "invalid_topology_artifact_sources");
    for (const [device, workspace] of Object.entries(config.device_sources ?? {})) { identifier(device); identifier(workspace); }
    this.devices = Object.freeze({ ...config.device_sources });
    this.binding_digest = digest({ workspace: this.workspace, allowed: this.allowed, specmesh: specmesh?.binding_digest ?? null,
      ...(config.device_sources ? { device_sources: this.devices } : {}) });
    this.current();
  }
  private current(): void {
    const checked: unknown = this.authorize();
    if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    requireThat(canonical(directoryIdentity(this.workspace.path)) === canonical(this.workspace), "topology_artifact_workspace_changed");
    this.specmesh?.assertWorkspace(this.workspace.path);
  }
  private parent(actor: Principal, taskId: string, revision: number) {
    this.current(); requireScope(actor, "team:write"); requireScope(actor, "task:execute");
    const snapshot = this.kernel.inspect(actor, taskId);
    requireThat(snapshot.revision === revision && Number.isSafeInteger(revision) && snapshot.task.status === "waiting" && !snapshot.active_episode && !snapshot.needs_reconciliation, "topology_artifact_parent_changed");
    requireThat((this.kernel.db.sql.query("SELECT principal FROM tasks WHERE task_id=?").get(taskId) as { principal: string }).principal === actor.id, "topology_artifact_owner_mismatch");
    requireThat(typeof snapshot.task.repo_root === "string" && canonical(directoryIdentity(snapshot.task.repo_root)) === canonical(this.workspace), "topology_artifact_parent_workspace_mismatch");
    const contract = decodeTaskCompletion(snapshot.task.completion_requirements);
    requireThat(contract && contract.files.every(file => this.allowed.includes(file.path)), "topology_artifact_path_not_registered");
    return { snapshot, contract };
  }
  private topology(taskId: string, revision: number) {
    const row = this.kernel.db.sql.query("SELECT revision,state FROM team_topologies WHERE task_id=?").get(taskId) as { revision: number; state: string } | null;
    requireThat(row && row.revision === revision && Number.isSafeInteger(revision), "topology_artifact_state_changed");
    return decodeTopologyState(JSON.parse(row.state));
  }
  private witnesses(actor: Principal, taskId: string, ancestors: ReadonlySet<string> = new Set()): { values: Witness[]; digest: string } {
    requireThat(ancestors.size < 32 && !ancestors.has(taskId), "topology_cycle_or_depth_limit");
    const lineage = new Set(ancestors); lineage.add(taskId);
    const state = this.kernel.db.sql.query("SELECT state FROM team_topologies WHERE task_id=?").get(taskId) as { state: string };
    const executionId = decodeTopologyState(JSON.parse(state.state)).execution_id;
    const assignments = this.kernel.db.sql.query("SELECT child_id,generation,checkpoint_id,topology,substage,worker_role,run_id,kind,execution_source FROM topology_tasks WHERE parent_id=? AND execution_id=? ORDER BY child_id").all(taskId, executionId) as {
      child_id: string; generation: number; checkpoint_id: string; topology: string; substage: string; worker_role: string; run_id: string; kind: string; execution_source: string;
    }[];
    const values: Witness[] = [], stamps: unknown[] = [];
    for (const assignment of assignments) {
      const child = this.kernel.inspect(actor, assignment.child_id);
      if (assignment.kind === "aggregate") {
        const topology = this.kernel.db.sql.query("SELECT revision FROM team_topologies WHERE task_id=?").get(assignment.child_id) as { revision: number } | null;
        requireThat(topology, "aggregate_topology_missing");
        const accepted = readAggregateResult(this.kernel, actor, { source: "topology", task_id: assignment.child_id, revision: child.revision,
          execution_id: assignment.run_id, topology_revision: topology.revision, topology: assignment.topology,
          substage: teamWorkerSubstage(assignment.topology, assignment.substage), worker_role: assignment.worker_role }, lineage);
        const nested = this.witnesses(actor, assignment.child_id, lineage);
        stamps.push({ assignment, child, accepted, witness_digest: nested.digest }); values.push(...nested.values); continue;
      }
      const run = topologyExecution(this.kernel, actor, assignment.child_id, assignment.run_id);
      requireThat(run.task_id === assignment.child_id && run.state === "completed" && run.lease, "topology_artifact_child_unresolved");
      const lease = run.lease;
      const effects = this.kernel.db.sql.query("SELECT e.effect_id FROM effects e JOIN episodes p ON p.episode_id=e.episode_id WHERE e.task_id=? AND e.episode_id=? AND e.fence=? AND e.state='confirmed' AND e.result=p.result")
        .all(assignment.child_id, lease.episode_id, lease.fence) as { effect_id: string }[];
      requireThat(effects.length === 1, "topology_artifact_effect_ambiguous");
      const accepted = this.kernel.inspectCompletedEffect(actor, assignment.child_id, child.revision, lease.episode_id, effects[0]!.effect_id);
      stamps.push({ assignment, child, run, result_digest: digest(accepted.result) });
      const contract = decodeTaskCompletion(child.task.completion_requirements);
      if (!contract) continue;
      requireThat(["claude", "opencode"].includes(String(child.task.provider)) && typeof child.task.repo_root === "string"
        && canonical(directoryIdentity(child.task.repo_root)) === canonical(this.workspace), "topology_artifact_child_workspace_mismatch");
      let hashes: string[], source: Witness["source"];
      if (assignment.execution_source === "device") {
        const value = accepted.result;
        assertProtocolSchema<DeviceNativeResult>("device-native-result.schema.json", value);
        requireThat(value.task_failure === undefined, "topology_artifact_child_failed");
        verifyDeviceCompletion(contract, value.completion);
        const row = this.kernel.db.sql.query("SELECT assignment_digest,specification FROM topology_device_runs WHERE run_id=?")
          .get(assignment.run_id) as { assignment_digest: string; specification: string };
        const workspace = JSON.parse(row.specification).workspace_id, evidence = value.evidence;
        requireThat(Object.hasOwn(this.devices, lease.device_id) && this.devices[lease.device_id] === workspace,
          "topology_artifact_device_source_not_registered");
        const manifest = this.kernel.db.sql.query("SELECT payload FROM execution_manifests WHERE effect_id=?").get(effects[0]!.effect_id) as { payload: string };
        const { observation_digest, result_digest, ...base } = evidence;
        requireThat(evidence.device_id === lease.device_id && evidence.task_id === assignment.child_id && evidence.episode_id === lease.episode_id
          && evidence.fence === lease.fence && evidence.effect_id === effects[0]!.effect_id && evidence.assignment_digest === row.assignment_digest
          && observation_digest && result_digest && manifest && digest(base) === digest(JSON.parse(manifest.payload))
          && value.native_session.device_id === lease.device_id && digest(value.native_session.evidence) === digest(evidence), "topology_artifact_device_evidence_changed");
        hashes = value.completion!.sha256;
        source = { kind: "device", device_id: lease.device_id, workspace_id: workspace, assignment_digest: evidence.assignment_digest,
          manifest_digest: evidence.manifest_digest };
      } else {
        requireThat(accepted.result.schema_version !== "controlmesh.device_native_result.v1", "topology_artifact_child_workspace_mismatch");
        hashes = deviceCompletionProof(contract, accepted.result.completion)!.sha256;
      }
      for (const [index, file] of contract.files.entries()) values.push({ child_id: assignment.child_id, generation: assignment.generation,
        episode_id: lease.episode_id, effect_id: effects[0]!.effect_id, path: file.path, mode: file.mode, sha256: hashes[index]!, ...(source ? { source } : {}) });
    }
    requireThat(assignments.length > 0, "topology_artifact_witnesses_missing");
    return { values, digest: digest(stamps) };
  }
  private capture(contract: TaskCompletion) {
    const paths = contract.files.map(file => join(this.workspace.path, file.path));
    try {
      const snapshots = snapshotReads(this.workspace.path, paths);
      // The file reader sorts canonical paths. Preserve contract order and refuse resolved aliases.
      return paths.map(path => {
        const file = snapshots.find(file => file.path === path);
        requireThat(file, "topology_artifact_path_changed"); return file;
      });
    } catch (error) {
      if (["ENOENT", "ENOTDIR"].includes((error as NodeJS.ErrnoException).code ?? "")) throw new RuntimeConflict("topology_artifact_file_unavailable");
      throw error;
    }
  }
  async prepare(actor: Principal, taskId: string, parentRevision: number, topologyRevision: number) {
    const { snapshot, contract } = this.parent(actor, taskId, parentRevision), state = this.topology(taskId, topologyRevision), parentDigest = digest(snapshot);
    requireThat(state.task_id === taskId && state.interruption.status === "idle" && state.checkpoints.at(-1)!.phase_status === "in_progress", "topology_artifact_prepare_stage");
    const witnesses = this.witnesses(actor, taskId), files = this.capture(contract);
    const selected = contract.files.map((file, index) => {
      const sha256 = files[index]!.sha256;
      requireThat(file.sha256 === undefined || file.sha256 === sha256, "topology_artifact_content_mismatch");
      const witness = witnesses.values.find(value => value.path === file.path && value.mode === file.mode && value.sha256 === sha256);
      requireThat(witness, "topology_artifact_native_evidence_missing"); return { ...file, sha256, witness };
    });
    const unchanged = () => {
      requireThat(digest(this.parent(actor, taskId, parentRevision).snapshot) === parentDigest
        && canonical(this.topology(taskId, topologyRevision)) === canonical(state) && this.witnesses(actor, taskId).digest === witnesses.digest
        && canonical(this.capture(contract)) === canonical(files), "topology_artifact_preparation_changed");
    };
    let observation: SpecMeshObservation | undefined;
    const source = snapshot.task.specmesh_completion_source;
    if (source !== undefined) {
      requireThat(this.specmesh && object(source) && source.authority === "asserted_candidate" && typeof source.path === "string"
        && typeof source.sha256 === "string" && /^[a-f0-9]{64}$/.test(source.sha256), "topology_specmesh_profile_required");
      observation = await this.specmesh.inspect("check", { assertCurrent: unchanged });
      const candidate = observation.result.artifact_requirements;
      requireThat(observation.result.status === "pass" && candidate && candidate.path === source.path && candidate.sha256 === source.sha256
        && digest(decodeTaskCompletion({ schema_version: "controlmesh.task_completion.v1", files: candidate.requirements.files })) === digest(contract), "topology_specmesh_requirements_changed");
    }
    unchanged(); observation?.assertCurrent();
    const evidence: TopologyArtifactEvidence = { schema_version: "controlmesh.topology_artifacts.v1", requirements_digest: digest(contract), workspace_binding: this.binding_digest,
      files: selected, specmesh: observation ? { operation: "check", binding_digest: this.specmesh!.binding_digest, snapshot_digest: observation.snapshot_digest,
        result_digest: digest(observation.result), source_sha256: (source as { sha256: string }).sha256 } : null };
    this.prepared.delete(taskId); this.prepared.set(taskId, { task_id: taskId, parent_revision: parentRevision, topology_revision: topologyRevision, parent_digest: parentDigest,
      state, witness_digest: witnesses.digest, files, evidence: structuredClone(evidence), observation });
    if (this.prepared.size > 128) this.prepared.delete(this.prepared.keys().next().value!);
    return { task_id: taskId, parent_revision: parentRevision, topology_revision: topologyRevision, evidence: structuredClone(evidence) };
  }
  /** Called only after the queue transaction has accepted the terminal decision. Never deserialized from a request. */
  issue(actor: Principal, parentRevision: number, snapshot: TopologySnapshot): TopologyCompletionPermit | undefined {
    const parent = this.kernel.inspect(actor, snapshot.task_id);
    if (parent.task.completion_requirements === undefined && parent.task.specmesh_completion_source === undefined) return undefined;
    const prepared = this.prepared.get(snapshot.task_id);
    requireThat(prepared && prepared.parent_revision === parentRevision && prepared.topology_revision + 1 === snapshot.revision, "topology_completion_prepare_required");
    const check = () => {
      const { snapshot: parent, contract } = this.parent(actor, snapshot.task_id, parentRevision);
      const state = this.topology(snapshot.task_id, snapshot.revision);
      requireThat(digest(parent) === prepared.parent_digest && canonical(state) === canonical(snapshot.state)
        && canonical(state.checkpoints.slice(0, prepared.state.checkpoints.length)) === canonical(prepared.state.checkpoints)
        && this.witnesses(actor, snapshot.task_id).digest === prepared.witness_digest && canonical(this.capture(contract)) === canonical(prepared.files), "topology_artifact_preparation_changed");
      prepared.observation?.assertCurrent();
    };
    check();
    const permit = Object.freeze({ evidence: structuredClone(prepared.evidence) });
    permits.set(permit, { kernel: this.kernel, actor: identity(actor), task_id: snapshot.task_id, parent_revision: parentRevision,
      topology_revision: snapshot.revision, evidence_digest: digest(permit.evidence), current: check });
    return permit;
  }
}
/** A stored JSON claim cannot replace the live profile/file/SpecMesh verification capability. */
export function assertTopologyCompletionPermit(value: unknown, kernel: RuntimeKernel, actor: Principal, taskId: string, parentRevision: number, revision: number, evidence: unknown): void {
  const permit = object(value) ? permits.get(value) : undefined;
  requireThat(permit && permit.kernel === kernel && permit.actor === identity(actor) && permit.task_id === taskId && permit.parent_revision === parentRevision
    && permit.topology_revision === revision && permit.evidence_digest === digest(evidence) && digest((value as TopologyCompletionPermit).evidence) === permit.evidence_digest, "topology_completion_gate_required");
  permit.current();
}
