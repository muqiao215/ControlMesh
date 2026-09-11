import { randomUUID } from "node:crypto";
import { isAbsolute, join } from "node:path";
import { ContainerProcessSupervisor } from "../containers/process";
import { resourceMounts, type ContainerConfiguration } from "../containers/plan";
import type { ProcessAdmission, ProcessOutcome, ProcessSpec } from "../process-supervisor";
import { digest, requireThat } from "../value";
import type { NativeRunner } from "./opencode-execution";

export interface OpenCodeContainerProfile {
  container: Omit<ContainerConfiguration, "resources" | "workspace_layout">;
  executable: string;
  data_home: string;
  cache_home: string;
}

/** Device-local OpenCode read execution; native data persists, while auth and project stay read-only. */
export class OpenCodeReadContainerRunner implements NativeRunner {
  private readonly profile: OpenCodeContainerProfile;
  private readonly configuration: ContainerConfiguration;
  private readonly containers: ContainerProcessSupervisor;
  private readonly initialDigest: string;

  constructor(profile: OpenCodeContainerProfile, containers?: ContainerProcessSupervisor) {
    this.profile = structuredClone(profile);
    requireThat(isAbsolute(profile.executable) && !/[\x00\r\n]/.test(profile.executable), "invalid_native_executable");
    this.configuration = { ...this.profile.container, workspace_layout: "native", resources: [
      { source: join(profile.data_home, "opencode"), readonly: false },
      { source: join(profile.cache_home, "opencode"), readonly: false },
      { source: join(profile.data_home, "opencode/auth.json"), readonly: true },
    ] };
    this.initialDigest = this.runtimeDigest();
    this.containers = containers ?? new ContainerProcessSupervisor(this.configuration);
  }

  runtimeDigest(): string {
    return digest({ schema_version: "controlmesh.opencode_container_read.v1", profile: this.profile,
      resources: resourceMounts(this.configuration) });
  }

  async run(spec: ProcessSpec, admission: ProcessAdmission): Promise<ProcessOutcome> {
    requireThat(spec.command[0] === this.profile.executable, "native_container_executable_mismatch");
    requireThat(spec.env.XDG_DATA_HOME === this.profile.data_home && spec.env.XDG_CACHE_HOME === this.profile.cache_home, "native_container_store_mismatch");
    const assertCurrent = () => {
      requireThat(this.runtimeDigest() === this.initialDigest, "native_container_profile_changed");
      return admission.assertCurrent();
    };
    assertCurrent();
    return this.containers.run({ ...spec, execution_id: `opencode-${randomUUID()}`, writable_roots: [], no_network: false,
      env: { ...spec.env, HOME: "/tmp/cm-home", XDG_CONFIG_HOME: "/tmp/cm-home/config",
        XDG_STATE_HOME: "/tmp/cm-home/state", OPENCODE_CONFIG_DIR: "/tmp/cm-home/config/opencode" },
    }, { ...admission, assertCurrent });
  }
}
