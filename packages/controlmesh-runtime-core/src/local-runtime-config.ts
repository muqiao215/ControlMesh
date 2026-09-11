import { closeSync, constants, fstatSync, mkdirSync, openSync, readSync, realpathSync, statSync, existsSync } from "node:fs";
import { createHash } from "node:crypto";
import { isAbsolute, join } from "node:path";
import { RuntimeDatabase } from "./database";
import { RuntimeKernel, type Principal } from "./kernel";
import { LocalTaskRuntime } from "./local-task-runtime";
import { PreflightCache } from "./providers/preflight-cache";
import { OpenCodeReadContainerRunner, type OpenCodeContainerProfile } from "./providers/opencode-container";
import { OpenCodeTaskAdapter } from "./providers/opencode-task-adapter";
import { NativeSessionStore } from "./providers/native-session";
import { directoryIdentity } from "./providers/native-manifest";
import { decodeSnapshot } from "./migration";
import { digest, identifier, object, requireThat } from "./value";

/** Never log the content: configuration and native auth may contain credentials. */
function privateFile(path: string): { bytes: Buffer; revision: string } {
  requireThat(isAbsolute(path) && realpathSync(path) === path, "private_config_path_required");
  const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const before = fstatSync(fd);
    requireThat(before.isFile() && before.uid === process.getuid?.() && (before.mode & 0o077) === 0 && before.size <= 2 * 1024 * 1024, "private_runtime_config_required");
    const bounded = Buffer.alloc(before.size + 1);
    let count = 0;
    while (count < bounded.length) { const read = readSync(fd, bounded, count, bounded.length - count, null); if (!read) break; count += read; }
    const bytes = bounded.subarray(0, count), after = fstatSync(fd);
    requireThat(bytes.byteLength === before.size && before.size === after.size && before.mtimeMs === after.mtimeMs && before.ctimeMs === after.ctimeMs, "runtime_config_changed");
    return { bytes, revision: digest({ device: before.dev, inode: before.ino, content: createHash("sha256").update(bytes).digest("hex") }) };
  } finally { closeSync(fd); }
}

/** Explicit isolated candidate configuration. Reading task state does not inspect or probe any provider. */
export function openLocalRuntime(path: string): { runtime: LocalTaskRuntime; close: () => Promise<void> } {
  const loaded = privateFile(path), config = decodeSnapshot(loaded.bytes).source;
  requireThat(object(config) && config.schema_version === "controlmesh.local_runtime.v1" && config.mode === "candidate", "unsupported_local_runtime_config");
  requireThat(typeof config.state_root === "string" && isAbsolute(config.state_root) && realpathSync(config.state_root) === config.state_root, "private_runtime_state_required");
  const root = config.state_root, state = statSync(root);
  requireThat(state.isDirectory() && state.uid === process.getuid?.() && (state.mode & 0o077) === 0, "private_runtime_state_required");
  requireThat(!["tasks.json", "config.json", "controlmesh_state"].some(name => existsSync(join(root, name))), "legacy_runtime_state_forbidden");
  identifier(config.principal_id); identifier(config.device_id);
  requireThat(object(config.source) && config.source.command_origin === "human_request" && config.source.origin === "user"
    && config.source.source_scope === "local_foreground" && typeof config.source.transport === "string", "local_source_profile_unqualified");
  requireThat(object(config.opencode) && typeof config.opencode.model === "string" && config.opencode.cli_version === "1.18.29"
    && object(config.opencode.native_configuration) && object(config.opencode.environment) && Object.values(config.opencode.environment).every(value => typeof value === "string")
    && object(config.opencode.container) && typeof config.opencode.executable === "string", "invalid_local_provider_profile");
  requireThat(object(config.workspace) && typeof config.workspace.directory === "string" && Array.isArray(config.workspace.read_files)
    && config.workspace.read_files.every(value => typeof value === "string") && Array.isArray(config.workspace.required_reads)
    && config.workspace.required_reads.every(value => typeof value === "string"), "invalid_local_workspace_profile");
  const provider = config.opencode, workspace = config.workspace;
  const environment = provider.environment as Record<string, string>;
  requireThat(typeof environment.XDG_DATA_HOME === "string" && typeof environment.XDG_CACHE_HOME === "string", "explicit_native_state_required");
  const native = provider.native_configuration as Record<string, unknown>;
  const initialRoot = digest(directoryIdentity(root));
  const current = () => {
    requireThat(privateFile(path).revision === loaded.revision && digest(directoryIdentity(root)) === initialRoot, "runtime_configuration_changed");
  };
  const actor: Principal = { id: config.principal_id, device_id: config.device_id, origin: "human_request",
    scopes: ["task:create", "task:read", "task:execute", "task:resume", "task:cancel", "task:reconcile", "task:admin", "message:send", "provider:probe"] };
  const db = new RuntimeDatabase(join(root, "runtime.sqlite")), kernel = new RuntimeKernel(db), cache = new PreflightCache(db);
  try {
    const runtime = new LocalTaskRuntime(kernel, actor, { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: config.source.transport }, task => {
      current();
      const control = join(root, "containers"); mkdirSync(control, { recursive: true, mode: 0o700 });
      const profile: OpenCodeContainerProfile = { container: { ...provider.container as OpenCodeContainerProfile["container"], state_root: control },
        executable: provider.executable as string, data_home: environment.XDG_DATA_HOME, cache_home: environment.XDG_CACHE_HOME };
      const runner = new OpenCodeReadContainerRunner(profile), store = new NativeSessionStore(join(profile.data_home, "opencode/opencode.db"), actor.device_id!);
      const registration = { workspace: workspace.directory as string,
        binding: () => ({ provider: "opencode", model: provider.model as string, cli_version: "1.18.29", device_id: actor.device_id!,
          config_digest: digest(native), credential_revision: privateFile(join(profile.data_home, "opencode/auth.json")).revision,
          permission_profile: "opencode-native-read-v1", runtime_digest: runner.runtimeDigest() }),
        admission: { source_scope: "local_foreground" as const, read_files: workspace.read_files as string[], required_reads: workspace.required_reads as string[], assertCurrent: current } };
      return new OpenCodeTaskAdapter(kernel, cache, actor, store, { executable: profile.executable, native_configuration: native,
        environment, state_home: root }, runner, registration).prepare(task);
    }, current, object(config.limits) ? config.limits : {});
    return { runtime, close: async () => { await runtime.stop(); db.close(); } };
  } catch (error) { db.close(); throw error; }
}
