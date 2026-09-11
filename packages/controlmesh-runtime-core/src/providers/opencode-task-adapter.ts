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
    const check = () => {
      requireThat(digest(this.config) === configuration && digest(this.registration.binding()) === digest(selected), "task_provider_configuration_changed");
      requireThat(selected.provider === "opencode" && task.task.provider === selected.provider && task.task.model === selected.model
        && selected.device_id === this.actor.device_id && selected.runtime_digest === this.runner.runtimeDigest?.(), "task_provider_registration_mismatch");
      requireThat(typeof task.task.repo_root === "string" && realpathSync(task.task.repo_root) === identity.path
        && digest(directoryIdentity(identity.path)) === digest(identity), "task_workspace_registration_mismatch");
      requireThat(nativeTaskDigest(this.kernel.inspect(this.actor, task.task.task_id).task) === issued, "worker_task_binding_changed");
      const source = enforceNativeReadSource(task.task.execution_context, this.runner);
      requireThat(source.source_scope === this.registration.admission.source_scope, "source_execution_floor_unavailable");
      const files = readFileGrant(identity.path, this.registration.admission.read_files);
      assertReadGrantSnapshot(task.task.tool_grant, files, this.config.communication ? nativeAgentTools : []);
      if (this.config.communication) {
        requireThat(this.config.communication.task_id === task.task.task_id, "native_agent_task_mismatch");
        assertNativeAgentConfiguration(this.config.communication);
      }
      requireThat(this.registration.admission.required_reads.every(file => files.includes(realpathSync(file))), "required_read_not_granted");
      const checked: unknown = this.registration.admission.assertCurrent();
      if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    };
    check();
    const grant = digest({ files: this.registration.admission.read_files, required: this.registration.admission.required_reads });
    const current = () => {
      check(); requireThat(digest({ files: this.registration.admission.read_files, required: this.registration.admission.required_reads }) === grant, "issued_read_grant_changed");
    };
    return {
      binding_digest: digest({ selected, configuration, identity, issued, grant }), assertCurrent: current,
      ensureReady: async (requestId, context) => new ProviderPreflightService(this.cache, new OpenCodePreflight(this.runner)).ensure(this.actor, requestId, selected,
        { executable: this.config.executable, model: selected.model, native_configuration: this.config.native_configuration,
          environment: this.config.environment, signal: context.signal, remainingMs: context.remainingMs, assertCurrent: context.assertCurrent }),
      execute: (lease, context) => new OpenCodeWorker(this.kernel, this.cache, this.store, this.config, this.runner).execute(this.actor, lease, selected,
        { ...this.registration.admission, assertCurrent: context.assertCurrent }, this.registration.timeout_ms ?? 60_000, { signal: context.signal, remainingMs: context.remainingMs }),
    };
  }
}
