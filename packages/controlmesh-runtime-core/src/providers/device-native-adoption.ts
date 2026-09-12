import { assertProtocolSchema, type DeviceNativeAdoption } from "@controlmesh/protocol";
import type { RuntimeDatabase } from "../database";
import type { Principal } from "../kernel";
import type { DeviceJob } from "../device-coordinator";
import { requireScope } from "../commands";
import { canonical, digest, identifier, object, requireThat } from "../value";
import { directoryIdentity } from "./native-manifest";
import type { NativeSessionRef } from "./native-session";

export interface AdoptionSelection { task_id: string; workspace_id: string; capability: string; session_id: string }
export interface AdoptionProfile { directory: string; model: string; digest: string }
export interface NativeAdoptionHistory<P extends "opencode" | "claude"> {
  search(query: string, project: string | null, current: () => void): Promise<{ session_id: string; directory: string; title: string }[]>;
  inspect(sessionId: string, current: () => void): Promise<NativeSessionRef<P>>;
  refresh?(project: string, current: () => void): Promise<Record<string, unknown>>;
}
interface AdoptionRow {
  adoption_id: string; principal: string; device_id: string; task_id: string; workspace_id: string;
  capability: string; profile_digest: string; reference: string; context_digest: string;
}

/** Local context registry. Neither a candidate nor its opaque handle grants execution rights. */
export class DeviceNativeAdoptions<P extends "opencode" | "claude" = "opencode"> {
  private stopping = false;
  private readonly pending = new Set<Promise<unknown>>();
  constructor(private readonly db: RuntimeDatabase, private readonly actor: Principal,
    private readonly store: { deviceId: string; baseline(reference: NativeSessionRef<P>): unknown },
    private readonly history: NativeAdoptionHistory<P>,
    private readonly workspace: (workspaceId: string) => string,
    private readonly profile: (workspaceId: string, capability: string, taskId: string) => AdoptionProfile,
    private readonly assertCurrent: () => void) {
    requireThat(actor.device_id === store.deviceId, "native_adoption_device_mismatch");
  }
  private current(): void {
    requireThat(!this.stopping, "native_history_stopped"); const checked: unknown = this.assertCurrent();
    if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
  }
  private async bounded<T>(work: () => Promise<T>): Promise<T> {
    this.current(); requireThat(this.pending.size < 4, "native_history_backpressure");
    const pending = Promise.resolve().then(work).finally(() => this.pending.delete(pending));
    this.pending.add(pending); return pending;
  }
  async stop(): Promise<void> { this.stopping = true; await Promise.allSettled(this.pending); }
  async search(workspaceId: string, query: string): Promise<Record<string, unknown>> {
    requireScope(this.actor, "history:read"); identifier(workspaceId);
    requireThat(typeof query === "string" && Buffer.byteLength(query) <= 256, "invalid_history_query");
    return this.bounded(async () => {
      const directory = this.workspace(workspaceId), identity = digest(directoryIdentity(directory));
      const current = () => { this.current(); requireThat(digest(directoryIdentity(this.workspace(workspaceId))) === identity, "native_history_workspace_changed"); };
      const candidates = await this.history.search(query, directory, current); current();
      return { authorization: "context_only", workspace_id: workspaceId,
        ...(this.history.refresh ? { freshness: "unknown", refresh_policy: "explicit" } : {}),
        items: candidates.filter(item => item.directory === directory).map(({ session_id, title }) => ({ session_id, title })) };
    });
  }
  async refresh(workspaceId: string): Promise<Record<string, unknown>> {
    requireScope(this.actor, "history:read"); identifier(workspaceId);
    requireThat(this.history.refresh, "native_history_refresh_unsupported");
    return this.bounded(async () => {
      const directory = this.workspace(workspaceId), identity = digest(directoryIdentity(directory));
      const current = () => { this.current(); requireThat(digest(directoryIdentity(this.workspace(workspaceId))) === identity, "native_history_workspace_changed"); };
      const result = await this.history.refresh!(directory, current); current();
      return { authorization: "context_only", workspace_id: workspaceId, ...result };
    });
  }
  async prepare(requestId: string, selection: AdoptionSelection): Promise<Record<string, unknown>> {
    requireScope(this.actor, "history:adopt"); identifier(requestId); identifier(selection.task_id); identifier(selection.workspace_id); identifier(selection.capability);
    return this.bounded(async () => {
      const selected = this.profile(selection.workspace_id, selection.capability, selection.task_id), profile = digest(selected);
      const current = () => { this.current(); requireThat(digest(this.profile(selection.workspace_id, selection.capability, selection.task_id)) === profile, "native_adoption_profile_changed"); };
      const reference = await this.history.inspect(selection.session_id, current); current();
      requireThat(reference.directory === selected.directory && reference.model === selected.model, "native_adoption_model_or_workspace_mismatch");
      this.store.baseline(reference); // Read-only idle/revision check; never repairs or executes the selected session.
      const adoptionId = digest([this.actor.id, this.store.deviceId, requestId]);
      const body = { adoption_id: adoptionId, principal: this.actor.id, device_id: this.store.deviceId,
        task_id: selection.task_id, workspace_id: selection.workspace_id, capability: selection.capability,
        profile_digest: selected.digest, reference };
      const contextDigest = digest(body), encoded = canonical(reference);
      requireThat(Buffer.byteLength(encoded) <= 16384, "native_adoption_reference_too_large");
      this.db.transaction(() => {
        current();
        const prior = this.db.sql.query("SELECT context_digest FROM device_native_adoptions WHERE adoption_id=?").get(adoptionId) as { context_digest: string } | null;
        requireThat(!prior || prior.context_digest === contextDigest, "native_adoption_request_changed");
        if (!prior) this.db.sql.query("INSERT INTO device_native_adoptions VALUES (?,?,?,?,?,?,?,?,?)").run(adoptionId, this.actor.id, this.store.deviceId,
          selection.task_id, selection.workspace_id, selection.capability, selected.digest, encoded, contextDigest);
      });
      const handle: DeviceNativeAdoption = { schema_version: "controlmesh.device_native_adoption.v1", device_id: this.store.deviceId,
        adoption_id: adoptionId, context_digest: contextDigest };
      assertProtocolSchema("device-native-adoption.schema.json", handle);
      return { authorization: "context_only", task_id: selection.task_id, workspace_id: selection.workspace_id,
        provider: reference.provider, model: reference.model, title: reference.title, reference_revision: reference.revision, native_session: handle };
    });
  }

  /** Returns the original immutable reference. Execution revalidates it; recovery verifies its appended native turn. */
  resolve(value: unknown, job: Pick<DeviceJob, "task_id" | "workspace_id" | "capability">): NativeSessionRef<P> {
    this.current(); assertProtocolSchema<DeviceNativeAdoption>("device-native-adoption.schema.json", value);
    requireThat(value.device_id === this.store.deviceId, "native_adoption_device_mismatch");
    const row = this.db.sql.query("SELECT * FROM device_native_adoptions WHERE adoption_id=? AND principal=? AND device_id=?")
      .get(value.adoption_id, this.actor.id, this.store.deviceId) as AdoptionRow | null;
    requireThat(row && row.task_id === job.task_id && row.workspace_id === job.workspace_id && row.capability === job.capability, "native_adoption_scope_mismatch");
    const reference: unknown = JSON.parse(row.reference);
    requireThat(object(reference), "native_adoption_reference_corrupted");
    const { context_digest: stored, ...body } = row;
    requireThat(stored === value.context_digest && stored === digest({ ...body, reference }), "native_adoption_reference_corrupted");
    const selected = this.profile(job.workspace_id, job.capability, job.task_id);
    requireThat(row.profile_digest === selected.digest && reference.directory === selected.directory && reference.model === selected.model,
      "native_adoption_profile_changed");
    return reference as unknown as NativeSessionRef<P>;
  }
}
