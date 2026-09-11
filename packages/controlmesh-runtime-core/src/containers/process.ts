import { randomUUID } from "node:crypto";
import { closeSync, fsyncSync, mkdirSync, openSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { elapsedMs } from "../elapsed-clock";
import { ProcessSupervisor, type ProcessAdmission, type ProcessOutcome, type ProcessSpec } from "../process-supervisor";
import { canonical, digest, object, requireThat } from "../value";
import { directoryIdentity } from "../providers/native-manifest";
import { assertLocalDocker, assertMounts, planContainer, type ContainerConfiguration, type ContainerPlan } from "./plan";

export interface ContainerProcessSpec extends ProcessSpec {
  execution_id: string;
  writable_roots: readonly string[];
  no_network: boolean;
}
interface RecordState { schema_version: "controlmesh.container_execution.v1"; execution: string; owner: string; input_digest: string; isolation_digest: string; nonce: string; name: string; image: string; socket: string; engine_id: string | null; container_id: string | null; creation_uncertain: boolean; state: "preparing" | "created" | "running" | "removed" | "cleanup_pending"; outcome?: ProcessOutcome }
export interface ContainerOutcome extends ProcessOutcome { container_id: string | null; cleanup: "removed" | "pending" }

const ID = /^[0-9a-f]{64}$/;
const labels = (record: RecordState) => ({ "io.controlmesh.execution": record.execution, "io.controlmesh.owner": record.owner, "io.controlmesh.nonce": record.nonce });
function atomic(path: string, value: unknown): void {
  const pending = `${path}.next`;
  writeFileSync(pending, canonical(value), { mode: 0o600 });
  if (path.endsWith("record.json")) { const fd = openSync(pending, "r"); try { fsyncSync(fd); } finally { closeSync(fd); } }
  renameSync(pending, path);
  if (path.endsWith("record.json")) { const fd = openSync(dirname(path), "r"); try { fsyncSync(fd); } finally { closeSync(fd); } }
}
const control = { assertCurrent() {} };
const bootId = () => readFileSync("/proc/sys/kernel/random/boot_id", "utf8").trim();

/** One private container per execution, with an in-namespace lease watchdog and explicit cleanup recovery. */
export class ContainerProcessSupervisor {
  constructor(private readonly configuration: ContainerConfiguration, private readonly supervisor = new ProcessSupervisor()) {}

  private async docker(args: string[], admission: ProcessAdmission = control): Promise<ProcessOutcome> {
    const config = this.configuration;
    return this.supervisor.run({ command: [config.docker, "--host", `unix://${config.socket}`, "--config", join(config.state_root, "cli"), ...args],
      cwd: config.state_root, env: { PATH: "/usr/bin:/bin", HOME: config.state_root, LC_ALL: "C" }, timeout_ms: 10_000, max_output_bytes: 512 * 1024 }, admission);
  }

  private async inspect(record: RecordState, admission: ProcessAdmission = control): Promise<Record<string, any> | null> {
    requireThat(record.socket === this.configuration.socket, "container_engine_changed");
    const result = await this.docker(["container", "inspect", record.container_id ?? record.name], admission);
    if (result.reason === "exited" && result.exit_code !== 0 && /No such (object|container)/i.test(result.stderr)) return null;
    requireThat(result.reason === "exited" && result.exit_code === 0, "container_inspection_unavailable");
    const values: unknown = JSON.parse(result.stdout);
    requireThat(Array.isArray(values) && values.length === 1 && object(values[0]), "container_inspection_invalid");
    const value = values[0] as Record<string, any>;
    requireThat(ID.test(value.Id) && (record.container_id === null || record.container_id === value.Id) && value.Name === `/${record.name}` && value.Image === record.image, "container_identity_conflict");
    for (const [key, expected] of Object.entries(labels(record))) requireThat(value.Config?.Labels?.[key] === expected, "container_identity_conflict");
    return value;
  }

  private verifyIsolation(value: Record<string, any>, plan: ContainerPlan, directory: string): void {
    const host = value.HostConfig;
    requireThat(value.Config.User === plan.user && value.Config.Entrypoint?.length === 1 && value.Config.Entrypoint[0] === this.configuration.node_executable
      && value.Config.Cmd?.length === 1 && value.Config.Cmd[0] === "/cm-control/init.cjs" && value.Config.WorkingDir === plan.working_directory
      && host.ReadonlyRootfs === true && host.Privileged === false && host.NetworkMode === plan.network && host.RestartPolicy?.Name === "no"
      && host.PidMode === "" && host.IpcMode === "private" && host.CgroupnsMode === "private" && !host.Devices?.length && !host.CapAdd?.length
      && host.CapDrop?.length === 1 && host.CapDrop[0].toLowerCase() === "all" && host.SecurityOpt?.includes("no-new-privileges")
      && host.Memory === plan.memory * 1024 * 1024 && host.MemorySwap === host.Memory && host.PidsLimit === plan.pids && host.NanoCpus === Math.round(plan.cpus * 1e9)
      && !Object.keys(host.PortBindings ?? {}).length, "container_isolation_mismatch");
    const mounts = [...plan.mounts.map(mount => ({ Source: mount.source, Destination: mount.target, RW: !mount.readonly })), { Source: directory, Destination: "/cm-control", RW: false }];
    const actual = value.Mounts;
    requireThat(Array.isArray(actual) && actual.length === mounts.length && mounts.every(expected => actual.some(mount => mount.Type === "bind" && mount.Source === expected.Source && mount.Destination === expected.Destination && mount.RW === expected.RW && mount.Propagation === "rprivate")), "container_mount_mismatch");
  }

  private async remove(record: RecordState, directory: string): Promise<boolean> {
    try {
      if (record.engine_id) requireThat(await this.engine() === record.engine_id, "container_engine_changed");
      const existing = await this.inspect(record);
      if (existing) {
        record.container_id = existing.Id; record.creation_uncertain = false;
        atomic(join(directory, "record.json"), record);
        await this.docker(["container", "rm", "--force", record.container_id!]);
        requireThat(await this.inspect(record) === null, "container_remove_unconfirmed");
      }
      // A timed-out create may still arrive at the daemon after an absence check.
      // Without an observed immutable ID, absence cannot close that uncertainty.
      requireThat(!record.creation_uncertain || record.container_id !== null, "container_creation_still_unknown");
      record.state = "removed";
      for (const name of ["launch.json", "lease.json", "lease.json.next", "init.cjs"]) rmSync(join(directory, name), { force: true });
      atomic(join(directory, "record.json"), record);
      return true;
    } catch {
      record.state = "cleanup_pending"; atomic(join(directory, "record.json"), record); return false;
    }
  }

  private async engine(admission: ProcessAdmission = control): Promise<string> {
    const result = await this.docker(["info", "--format", '{"ID":{{json .ID}},"OSType":{{json .OSType}},"SecurityOptions":{{json .SecurityOptions}}}'], admission);
    requireThat(result.reason === "exited" && result.exit_code === 0, "container_engine_unavailable");
    const info = JSON.parse(result.stdout);
    requireThat(info.OSType === "linux" && typeof info.ID === "string" && info.ID.length > 0 && info.SecurityOptions?.some((option: string) => option.startsWith("name=seccomp,")), "container_engine_profile_unverified");
    return info.ID;
  }

  /** Explicit recovery of an expired execution only. It never starts or resumes its container. */
  async cleanupExpired(executionId: string, authorize: () => void): Promise<boolean> {
    const checked: unknown = authorize();
    if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    assertLocalDocker(this.configuration);
    const execution = digest(executionId), directory = join(this.configuration.state_root, execution);
    const record: RecordState = JSON.parse(readFileSync(join(directory, "record.json"), "utf8"));
    requireThat(record.schema_version === "controlmesh.container_execution.v1" && typeof record.creation_uncertain === "boolean" && ID.test(record.input_digest) && ID.test(record.isolation_digest)
      && record.execution === execution && record.owner === digest(this.configuration.state_root)
      && /^cm-exec-[0-9a-f-]{36}$/.test(record.name) && /^[0-9a-f-]{36}$/.test(record.nonce)
      && /^sha256:[0-9a-f]{64}$/.test(record.image) && (record.container_id === null || ID.test(record.container_id)), "container_record_mismatch");
    if (record.state === "removed") return true;
    const lease = JSON.parse(readFileSync(join(directory, "lease.json"), "utf8"));
    requireThat(typeof lease.expires_ms === "number" && Number.isFinite(lease.expires_ms) && typeof lease.boot_id === "string", "container_lease_invalid");
    requireThat(lease.boot_id !== bootId() || lease.expires_ms <= elapsedMs(), "container_lease_still_active");
    return this.remove(record, directory);
  }

  async run(spec: ContainerProcessSpec, admission: ProcessAdmission): Promise<ContainerOutcome> {
    assertLocalDocker(this.configuration);
    requireThat(typeof spec.execution_id === "string" && spec.execution_id.length > 0 && spec.execution_id.length <= 256, "container_execution_identity_required");
    const plan = planContainer(this.configuration, spec.cwd, spec.writable_roots, spec.no_network);
    requireThat(typeof spec.no_network === "boolean", "invalid_container_network_policy");
    const original = digest([spec, this.configuration]), boot = bootId(), start = elapsedMs(), deadline = start + spec.timeout_ms;
    const stateIdentity = digest(directoryIdentity(this.configuration.state_root));
    requireThat(Number.isSafeInteger(spec.timeout_ms) && spec.timeout_ms > 0 && spec.timeout_ms <= 86_400_000, "invalid_process_deadline");
    requireThat(spec.command.length > 0 && spec.command.length <= 256 && spec.command.every(arg => typeof arg === "string" && arg.length <= 65536 && !arg.includes("\0")), "invalid_container_command");
    requireThat(spec.stdin_text === undefined || Buffer.byteLength(spec.stdin_text) <= 65536, "invalid_process_input");
    requireThat(Object.keys(spec.env).length <= 256 && Object.entries(spec.env).every(([key, value]) => /^[A-Za-z_][A-Za-z0-9_]*$/.test(key) && typeof value === "string" && value.length <= 32768 && !value.includes("\0")), "invalid_container_environment");
    const execution = digest(spec.execution_id), directory = join(this.configuration.state_root, execution);
    let active = true, previousExpiry = Infinity;
    const current = () => {
      requireThat(active && !admission.signal?.aborted && elapsedMs() < deadline && elapsedMs() < previousExpiry, "container_authority_expired");
      requireThat(digest([spec, this.configuration]) === original, "container_launch_changed");
      requireThat(digest(directoryIdentity(this.configuration.state_root)) === stateIdentity, "container_state_replaced");
      assertMounts(plan);
      const checked: unknown = admission.assertCurrent();
      if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
      const remaining = admission.remainingMs?.() ?? spec.timeout_ms;
      requireThat(Number.isFinite(remaining) && remaining > 0, "container_authority_expired");
      previousExpiry = Math.min(elapsedMs() + 1000, deadline, elapsedMs() + remaining);
    };
    current();
    // An execution directory is a durable no-replay marker, including failed preparation.
    mkdirSync(directory, { mode: 0o700 });
    const parent = openSync(this.configuration.state_root, "r"); try { fsyncSync(parent); } finally { closeSync(parent); }
    const record: RecordState = { schema_version: "controlmesh.container_execution.v1", execution, owner: digest(this.configuration.state_root), input_digest: original, isolation_digest: digest(plan),
      nonce: randomUUID(), name: `cm-exec-${randomUUID()}`, image: this.configuration.image_id,
      socket: this.configuration.socket, engine_id: null, container_id: null, creation_uncertain: false, state: "preparing" };
    atomic(join(directory, "record.json"), record);
    const renew = () => { current(); atomic(join(directory, "lease.json"), { boot_id: boot, expires_ms: previousExpiry }); };
    renew();
    const context: ProcessAdmission = { assertCurrent: renew, remainingMs: () => Math.min(deadline - elapsedMs(), admission.remainingMs?.() ?? Infinity), signal: admission.signal };
    let removed = false;
    let outcome: ProcessOutcome = { reason: "spawn_failed", exit_code: null, stdout: "", stderr: "", duration_ms: 0 };
    try {
      record.engine_id = await this.engine(context); atomic(join(directory, "record.json"), record);
      const build = await Bun.build({ entrypoints: [join(import.meta.dir, "init.ts")], target: "node", format: "cjs" });
      requireThat(build.success && build.outputs.length === 1, "container_init_build_failed");
      writeFileSync(join(directory, "init.cjs"), await build.outputs[0].text(), { mode: 0o600 });
      atomic(join(directory, "launch.json"), { command: spec.command, environment: spec.env, working_directory: plan.working_directory });
      const image = await this.docker(["image", "inspect", this.configuration.image_id], context);
      requireThat(image.reason === "exited" && image.exit_code === 0, "container_image_unavailable");
      const imageConfig = JSON.parse(image.stdout);
      requireThat(imageConfig.length === 1 && imageConfig[0].Id === record.image && !Object.keys(imageConfig[0].Config?.Volumes ?? {}).length, "container_image_volumes_unsupported");
      const args = ["container", "create", "--pull", "never", "--name", record.name, "--interactive", "--read-only", "--network", plan.network, "--user", plan.user,
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--ipc", "private", "--cgroupns", "private", "--restart", "no", "--no-healthcheck", "--log-driver", "none",
        "--memory", `${plan.memory}m`, "--memory-swap", `${plan.memory}m`, "--pids-limit", String(plan.pids), "--cpus", String(plan.cpus), "--shm-size", "16m",
        "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=67108864,mode=1777", "--workdir", plan.working_directory, "--entrypoint", this.configuration.node_executable];
      for (const [key, value] of Object.entries(labels(record))) args.push("--label", `${key}=${value}`);
      for (const key of ["NODE_OPTIONS", "NODE_PATH", "LD_PRELOAD", "LD_LIBRARY_PATH"]) args.push("--env", `${key}=`);
      for (const mount of plan.mounts) args.push("--mount", `type=bind,source=${mount.source},destination=${mount.target},bind-propagation=rprivate${mount.kind === "directory" ? ",bind-recursive=disabled" : ""}${mount.readonly ? ",readonly" : ""}`);
      args.push("--mount", `type=bind,source=${directory},destination=/cm-control,readonly,bind-propagation=rprivate,bind-recursive=disabled`, record.image, "/cm-control/init.cjs");
      record.creation_uncertain = true; atomic(join(directory, "record.json"), record);
      const created = await this.docker(args, context);
      requireThat(created.reason === "exited" && created.exit_code === 0 && ID.test(created.stdout.trim()), "container_creation_unconfirmed");
      record.container_id = created.stdout.trim(); record.creation_uncertain = false; record.state = "created"; atomic(join(directory, "record.json"), record);
      const inspected = await this.inspect(record, context);
      requireThat(inspected !== null && inspected.State?.Status === "created", "container_start_state_invalid");
      this.verifyIsolation(inspected, plan, directory);
      renew(); record.state = "running"; atomic(join(directory, "record.json"), record);
      outcome = await this.supervisor.run({ command: [this.configuration.docker, "--host", `unix://${this.configuration.socket}`, "--config", join(this.configuration.state_root, "cli"), "container", "start", "--attach", "--interactive", record.container_id],
        cwd: this.configuration.state_root, env: { PATH: "/usr/bin:/bin", HOME: this.configuration.state_root, LC_ALL: "C" }, timeout_ms: Math.max(1, Math.floor(deadline - elapsedMs())),
        ...(spec.stdin_text === undefined ? {} : { stdin_text: spec.stdin_text }), ...(spec.max_output_bytes === undefined ? {} : { max_output_bytes: spec.max_output_bytes }) },
      { ...context, abortOnStderrLine: admission.abortOnStderrLine });
      const finished = await this.inspect(record);
      if (!finished || finished.State.Running || finished.State.ExitCode !== outcome.exit_code) outcome = { ...outcome, reason: outcome.reason === "exited" ? "anchor_failed" : outcome.reason };
      if (outcome.reason === "exited") { try { current(); } catch { outcome.reason = "authority_lost"; } }
    } finally {
      active = false;
      atomic(join(directory, "lease.json"), { boot_id: boot, expires_ms: 0 });
      outcome.duration_ms = Math.round(elapsedMs() - start);
      record.outcome = outcome;
      removed = await this.remove(record, directory);
      if (!removed) { outcome.reason = "cleanup_failed"; atomic(join(directory, "record.json"), record); }
    }
    return { ...outcome, container_id: record.container_id, cleanup: removed ? "removed" : "pending" };
  }
}
