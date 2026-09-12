import { assertOpenCodeCompletionScope } from "./opencode-completion";
import { realpathSync } from "node:fs";
import { digest, requireThat } from "../value";
import type { RuntimeKernel, Principal, TaskSnapshot } from "../kernel";
import type { LocalTaskExecution } from "../local-task-runtime";
import { enforceNativeReadSource } from "../execution-policy";
import { directoryIdentity, nativeTaskDigest } from "./native-manifest";
import { readFileGrant, assertReadGrantSnapshot } from "./opencode-profile";
import { OpenCodePreflight } from "./opencode-preflight";
import { OpenCodeWorker, type IssuedReadAdmission, type OpenCodeWorkerConfig } from "./opencode-worker";
import type { NativeRunner } from "./opencode-execution";
import { NativeSessionStore, type NativeSessionRef } from "./native-session";
import { PreflightCache, type ProbeBinding } from "./preflight-cache";
import { ProviderPreflightService } from "./preflight-service";
import { nativeAgentTools } from "./native-agent-journal";
import { assertNativeAgentConfiguration } from "./native-agent-profile";
import { WorkspaceStage } from "../workspace-stage";
import { registeredReads, writeRoots } from "./native-workspace";
import { assertWorkspaceGrantSnapshot } from "./opencode-profile";

export interface OpenCodeTaskRegistration {
  workspace: string;
  binding: () => ProbeBinding;
  admission: IssuedReadAdmission;
  timeout_ms?: number;
}

/** Pure task/profile selection followed by one durable preflight and the actual native driver. */
export class OpenCodeTaskAdapter {
  constructor(private readonly kernel: RuntimeKernel, private readonly cache: PreflightCache, private readonly actor: Principal,
    private readonly store: NativeSessionStore, private readonly config: OpenCodeWorkerConfig, private readonly runner: NativeRunner,
    private readonly registration: OpenCodeTaskRegistration) {}

  prepare(task: TaskSnapshot): LocalTaskExecution {
    const selected = structuredClone(this.registration.binding());
    const configuration = digest(this.config), identity = directoryIdentity(this.registration.workspace), issued = nativeTaskDigest(task.task);
    if (task.task.native_session) {
      const reference = this.store.validate(task.task.native_session as NativeSessionRef);
      requireThat(reference.model === selected.model && reference.directory === identity.path, "native_result_binding_mismatch");
    }
    const roots = this.registration.admission.workspace_write ? writeRoots(identity.path, this.registration.admission.workspace_write) : [];
    const check = (afterWrites = false) => {
      requireThat(digest(this.config) === configuration && digest(this.registration.binding()) === digest(selected), "task_provider_configuration_changed");
      requireThat(selected.provider === "opencode" && task.task.provider === selected.provider && task.task.model === selected.model
        && selected.device_id === this.actor.device_id && selected.runtime_digest === this.runner.runtimeDigest?.(), "task_provider_registration_mismatch");
      requireThat(typeof task.task.repo_root === "string" && realpathSync(task.task.repo_root) === identity.path
        && digest(directoryIdentity(identity.path)) === digest(identity), "task_workspace_registration_mismatch");
      requireThat(nativeTaskDigest(this.kernel.inspect(this.actor, task.task.task_id).task) === issued, "worker_task_binding_changed");
      const source = enforceNativeReadSource(task.task.execution_context, this.runner);
      requireThat(source.source_scope === this.registration.admission.source_scope, "source_execution_floor_unavailable");
      const files = roots.length ? registeredReads(identity.path, this.registration.admission.read_files, roots, afterWrites)
        : readFileGrant(identity.path, this.registration.admission.read_files);
      assertOpenCodeCompletionScope(task.task.completion_requirements, identity.path, files, roots);
      assertReadGrantSnapshot(task.task.tool_grant, files, this.config.communication ? nativeAgentTools : []);
      if (roots.length) {
        WorkspaceStage.assertLocation(this.config.state_home, identity.path);
        requireThat(this.runner.forStage && this.registration.admission.workspace_write
          && digest(writeRoots(identity.path, this.registration.admission.workspace_write)) === digest(roots), "native_write_owner_required");
        assertWorkspaceGrantSnapshot(task.task.tool_grant, identity.path, roots, this.config.communication ? nativeAgentTools : []);
      }
      if (this.config.communication) {
        requireThat(this.config.communication.task_id === task.task.task_id, "native_agent_task_mismatch");
        assertNativeAgentConfiguration(this.config.communication);
      }
      const required = roots.length ? registeredReads(identity.path, this.registration.admission.required_reads, roots, afterWrites)
        : this.registration.admission.required_reads.map(file => realpathSync(file));
      requireThat(required.every(file => files.includes(file)), "required_read_not_granted");
      const checked: unknown = this.registration.admission.assertCurrent();
      if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    };
    check();
    const issuedGrantValue = () => ({ files: this.registration.admission.read_files, required: this.registration.admission.required_reads,
      ...(this.registration.admission.workspace_write ? { workspace_write: this.registration.admission.workspace_write } : {}) });
    const grant = digest(issuedGrantValue());
    const current = (afterWrites = false) => {
      check(afterWrites); requireThat(digest(issuedGrantValue()) === grant, "issued_read_grant_changed");
    };
    return {
      binding_digest: digest({ selected, configuration, identity, issued, grant }), assertCurrent: current,
      ...(roots.length ? { assertPublicationAuthority: () => current(true) } : {}),
      ensureReady: async (requestId, context) => new ProviderPreflightService(this.cache, new OpenCodePreflight(this.runner)).ensure(this.actor, requestId, selected,
        { executable: this.config.executable, model: selected.model, native_configuration: this.config.native_configuration,
          environment: this.config.environment, signal: context.signal, remainingMs: context.remainingMs, assertCurrent: context.assertCurrent }),
      execute: (lease, context) => new OpenCodeWorker(this.kernel, this.cache, this.store, this.config, this.runner).execute(this.actor, lease, selected,
        { ...this.registration.admission, assertCurrent: context.assertCurrent }, this.registration.timeout_ms ?? 60_000, {
          signal: context.signal, remainingMs: context.remainingMs, assertPublicationAuthority: context.assertPublicationAuthority,
          verifyPublication: context.verifyPublication }),
    };
  }
}
