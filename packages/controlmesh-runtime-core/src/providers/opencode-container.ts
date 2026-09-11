import { randomUUID } from "node:crypto";
import { isAbsolute, join } from "node:path";
import { ContainerProcessSupervisor } from "../containers/process";
import { contains, resourceMounts, type ContainerConfiguration } from "../containers/plan";
import type { ProcessAdmission, ProcessOutcome, ProcessSpec } from "../process-supervisor";
import { digest, requireThat } from "../value";
import type { NativeRunner } from "./opencode-execution";
import { assertNativeAgentConfiguration, type NativeAgentConfiguration } from "./native-agent-profile";
import { enforceExecutionPolicy } from "../execution-policy";
import type { ExecutionContext } from "../execution-context";
import { directoryIdentity } from "./native-manifest";
import type { WorkspaceStage } from "../workspace-stage";
import type { WorkspaceProjection } from "../containers/plan";

export interface OpenCodeContainerProfile {
  container: Omit<ContainerConfiguration, "resources" | "workspace_layout">;
  executable: string;
  data_home: string;
  cache_home: string;
  communication?: NativeAgentConfiguration;
}

export interface OpenCodeWriteScope { directory: string; write_roots: readonly string[] }

/** Common concrete container boundary; canonical project mounts are always read-only. */
class OpenCodeContainerRunner implements NativeRunner {
  protected readonly profile: OpenCodeContainerProfile;
  private readonly configuration: ContainerConfiguration;
  private readonly containers: ContainerProcessSupervisor;
  private readonly initialDigest: string;

  constructor(profile: OpenCodeContainerProfile, containers?: ContainerProcessSupervisor, private readonly writeScope?: OpenCodeWriteScope) {
    this.profile = structuredClone(profile);
    requireThat(isAbsolute(profile.executable) && !/[\x00\r\n]/.test(profile.executable), "invalid_native_executable");
    this.configuration = { ...this.profile.container, workspace_layout: "native", resources: [
      { source: join(profile.data_home, "opencode"), readonly: false },
      { source: join(profile.cache_home, "opencode"), readonly: false },
      { source: join(profile.data_home, "opencode/auth.json"), readonly: true },
      ...(profile.communication ? [{ source: profile.communication.directory, readonly: true }] : []),
    ] };
    this.initialDigest = this.runtimeDigest();
    this.containers = containers ?? new ContainerProcessSupervisor(this.configuration);
  }

  runtimeDigest(): string {
    return digest({ schema_version: this.writeScope ? "controlmesh.opencode_container_staged.v1" : "controlmesh.opencode_container_read.v1", profile: this.profile,
      resources: resourceMounts(this.configuration),
      ...(this.writeScope ? { workspace: directoryIdentity(this.writeScope.directory), write_roots: this.writeScope.write_roots.map(directoryIdentity) } : {}),
      ...(this.profile.communication ? { communication_identity: assertNativeAgentConfiguration(this.profile.communication) } : {}) });
  }

  protected projection(_spec: ProcessSpec): readonly WorkspaceProjection[] | undefined { return undefined; }

  assertSource(context: ExecutionContext): void {
    requireThat(this.runtimeDigest() === this.initialDigest, "native_container_profile_changed");
    enforceExecutionPolicy(context, true);
    requireThat(context.origin === "user" && ["local_foreground", "direct_message", "group_message"].includes(context.source_scope), "source_execution_floor_unavailable");
    // Every run below goes through ContainerProcessSupervisor; Docker failure never selects a host runner.
  }

  async run(spec: ProcessSpec, admission: ProcessAdmission): Promise<ProcessOutcome> {
    requireThat(spec.command[0] === this.profile.executable, "native_container_executable_mismatch");
    requireThat(spec.env.XDG_DATA_HOME === this.profile.data_home && spec.env.XDG_CACHE_HOME === this.profile.cache_home, "native_container_store_mismatch");
    const assertCurrent = () => {
      requireThat(this.runtimeDigest() === this.initialDigest, "native_container_profile_changed");
      this.projection(spec);
      return admission.assertCurrent();
    };
    assertCurrent();
    const projection = this.projection(spec);
    return this.containers.run({ ...spec, execution_id: `opencode-${randomUUID()}`, writable_roots: [], no_network: false,
      ...(projection ? { workspace_projection: projection } : {}),
      env: { ...spec.env, HOME: "/tmp/cm-home", XDG_CONFIG_HOME: "/tmp/cm-home/config",
        XDG_STATE_HOME: "/tmp/cm-home/state", OPENCODE_CONFIG_DIR: "/tmp/cm-home/config/opencode" },
    }, { ...admission, assertCurrent });
  }
}

/** Device-local read profile: auth and project remain read-only, native conversation data persists. */
export class OpenCodeReadContainerRunner extends OpenCodeContainerRunner {
  constructor(profile: OpenCodeContainerProfile, containers?: ContainerProcessSupervisor) { super(profile, containers); }
}

/** Explicit staged write profile. Its preflight is still tool-denied and has no writable project mount. */
export class OpenCodeStagedContainerRunner extends OpenCodeContainerRunner {
  private readonly scope: OpenCodeWriteScope;
  constructor(profile: OpenCodeContainerProfile, scope: OpenCodeWriteScope, private readonly stage?: WorkspaceStage) {
    const selected = structuredClone(scope);
    requireThat(selected.write_roots.length > 0 && selected.write_roots.length <= 64, "native_staged_roots_required");
    requireThat(directoryIdentity(selected.directory).path === selected.directory && selected.write_roots.every(path => directoryIdentity(path).path === path
      && contains(selected.directory, path)), "native_staged_scope_outside_workspace");
    selected.write_roots = [...new Set(selected.write_roots)].filter(path => !selected.write_roots.some(parent => parent !== path && contains(parent, path))).sort();
    super(profile, undefined, selected); this.scope = selected; stage?.assertPrepared();
  }
  forStage(stage: WorkspaceStage): OpenCodeStagedContainerRunner {
    const runner = new OpenCodeStagedContainerRunner(this.profile, this.scope, stage);
    requireThat(runner.runtimeDigest() === this.runtimeDigest(), "native_staged_runtime_changed"); return runner;
  }
  protected override projection(spec: ProcessSpec): readonly WorkspaceProjection[] | undefined {
    if (spec.cwd !== this.scope.directory) return undefined;
    requireThat(this.stage, "native_workspace_stage_required"); this.stage.assertSourceCurrent();
    const projection = this.stage.projection();
    requireThat(digest(projection.filter(entry => !entry.readonly).map(entry => entry.target).sort()) === digest([...this.scope.write_roots].sort()), "native_workspace_stage_scope_mismatch");
    return projection;
  }
}
