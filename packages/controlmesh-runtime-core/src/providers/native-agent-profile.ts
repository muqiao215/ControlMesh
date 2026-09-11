import { createHash } from "node:crypto";
import { constants, closeSync, fstatSync, mkdirSync, openSync, readFileSync, realpathSync, statSync, writeFileSync } from "node:fs";
import { isAbsolute, join } from "node:path";
import { digest, identifier, requireThat } from "../value";
import { decodeNativeAgentScope, type NativeAgentScope } from "./native-agent-journal";
import type { Lease } from "../kernel";

export interface NativeAgentConfiguration {
  task_id: string;
  directory: string;
  node_executable: string;
  client_digest: string;
  peer_tasks: string[];
  parent_task: string | null;
}
export function nativeAgentScope(config: NativeAgentConfiguration, lease: Pick<Lease, "task_id" | "episode_id" | "fence">): NativeAgentScope {
  requireThat(config.task_id === lease.task_id, "native_agent_task_mismatch");
  return decodeNativeAgentScope({ schema_version: "controlmesh.native_agent_scope.v1", task_id: lease.task_id,
    episode_id: lease.episode_id, fence: lease.fence, peer_tasks: [...config.peer_tasks], parent_task: config.parent_task, client_digest: config.client_digest });
}
export function assertNativeAgentConfiguration(config: NativeAgentConfiguration): string {
  identifier(config.task_id);
  requireThat(isAbsolute(config.directory) && realpathSync(config.directory) === config.directory, "native_agent_directory_not_canonical");
  requireThat(isAbsolute(config.node_executable) && !/[\x00\r\n]/.test(config.node_executable), "invalid_native_agent_node");
  const directory = statSync(config.directory, { bigint: true });
  requireThat(directory.isDirectory() && Number(directory.uid) === process.getuid?.() && (directory.mode & 0o077n) === 0n, "native_agent_private_directory_required");
  const fd = openSync(join(config.directory, "client.mjs"), constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const file = fstatSync(fd);
    requireThat(file.isFile() && file.uid === process.getuid?.() && (file.mode & 0o077) === 0 && file.size <= 65536, "native_agent_client_changed");
    requireThat(createHash("sha256").update(readFileSync(fd)).digest("hex") === config.client_digest, "native_agent_client_changed");
  } finally { closeSync(fd); }
  nativeAgentScope(config, { task_id: config.task_id, episode_id: "profile-validation", fence: 1 });
  return digest({ config, directory: { device: String(directory.dev), inode: String(directory.ino) } });
}

/** Trusted registration only: creates no broker, provider process or model invocation. */
export function prepareNativeAgentConfiguration(directory: string, node: string, taskId: string, peers: string[], parent: string | null): NativeAgentConfiguration {
  identifier(taskId);
  const source = readFileSync(join(import.meta.dir, "native-agent-client.ts"), "utf8");
  const compiled = new Bun.Transpiler({ loader: "ts", target: "node" }).transformSync(source);
  const config: NativeAgentConfiguration = { task_id: taskId, directory, node_executable: node,
    client_digest: createHash("sha256").update(compiled).digest("hex"), peer_tasks: [...peers], parent_task: parent };
  nativeAgentScope(config, { task_id: taskId, episode_id: "profile-validation", fence: 1 });
  mkdirSync(directory, { recursive: true, mode: 0o700 });
  requireThat(isAbsolute(directory) && realpathSync(directory) === directory, "native_agent_directory_not_canonical");
  const stat = statSync(directory);
  requireThat(stat.isDirectory() && stat.uid === process.getuid?.() && (stat.mode & 0o077) === 0, "native_agent_private_directory_required");
  try { writeFileSync(join(directory, "client.mjs"), compiled, { mode: 0o600, flag: "wx" }); }
  catch (error) { if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error; }
  assertNativeAgentConfiguration(config);
  return config;
}
