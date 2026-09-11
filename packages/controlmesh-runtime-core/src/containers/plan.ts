import { lstatSync, realpathSync } from "node:fs";
import { isAbsolute, relative, sep } from "node:path";
import { directoryIdentity, type DirectoryIdentity } from "../providers/native-manifest";
import { digest, requireThat } from "../value";

export interface ContainerConfiguration {
  docker: string;
  socket: string;
  state_root: string;
  image_id: string;
  node_executable: string;
  memory_mb?: number;
  pids?: number;
  cpus?: number;
}
export interface ContainerMount { source: string; target: string; readonly: boolean; identity: DirectoryIdentity }
export interface ContainerPlan { mounts: ContainerMount[]; network: "none" | "bridge"; memory: number; pids: number; cpus: number; user: string }

export function contains(root: string, child: string): boolean {
  const part = relative(root, child);
  return part === "" || (!part.startsWith(`..${sep}`) && part !== ".." && !isAbsolute(part));
}
function canonicalDirectory(path: string): DirectoryIdentity {
  requireThat(isAbsolute(path) && !/[\x00\r\n,]/.test(path) && realpathSync(path) === path, "container_path_not_canonical");
  return directoryIdentity(path);
}
export function planContainer(configuration: ContainerConfiguration, workspace: string, roots: readonly string[], noNetwork: boolean): ContainerPlan {
  requireThat(/^sha256:[0-9a-f]{64}$/.test(configuration.image_id), "container_image_digest_required");
  requireThat(isAbsolute(configuration.node_executable) && !/[\x00\r\n]/.test(configuration.node_executable), "invalid_container_node");
  const state = canonicalDirectory(configuration.state_root), directory = canonicalDirectory(workspace);
  requireThat(!["/proc", "/sys", "/dev", "/run"].some(root => contains(root, workspace)), "container_system_workspace_forbidden");
  requireThat(!contains(workspace, state.path) && !contains(state.path, workspace), "container_state_workspace_overlap");
  const uid = process.getuid?.(), gid = process.getgid?.();
  requireThat(typeof uid === "number" && uid > 0 && typeof gid === "number" && gid > 0, "container_nonroot_owner_required");
  const mount = (source: string, readonly: boolean): ContainerMount => ({ source, target: source === workspace ? "/workspace" : `/workspace/${relative(workspace, source)}`, readonly, identity: canonicalDirectory(source) });
  const allowed = [...new Set(roots)];
  requireThat(allowed.length <= 64, "too_many_container_write_roots");
  for (const root of allowed) requireThat(isAbsolute(root) && contains(workspace, root), "container_write_root_outside_workspace");
  const mounts = [mount(directory.path, !allowed.includes(workspace)), ...allowed.filter(root => root !== workspace && !allowed.some(parent => parent !== root && contains(parent, root))).map(root => mount(root, false))];
  const memory = configuration.memory_mb ?? 1024, pids = configuration.pids ?? 128, cpus = configuration.cpus ?? 1;
  requireThat(Number.isSafeInteger(memory) && memory >= 64 && memory <= 16384 && Number.isSafeInteger(pids) && pids >= 16 && pids <= 1024 && Number.isFinite(cpus) && cpus >= 0.1 && cpus <= 16, "invalid_container_resource_limits");
  return { mounts, network: noNetwork ? "none" : "bridge", memory, pids, cpus, user: `${uid}:${gid}` };
}
export function assertMounts(plan: ContainerPlan): void {
  for (const mount of plan.mounts) requireThat(realpathSync(mount.source) === mount.source && digest(directoryIdentity(mount.source)) === digest(mount.identity), "container_mount_replaced");
}
export function assertLocalDocker(configuration: ContainerConfiguration): void {
  requireThat(process.platform === "linux", "container_platform_unverified");
  requireThat(isAbsolute(configuration.docker) && realpathSync(configuration.docker) === configuration.docker && lstatSync(configuration.docker).isFile(), "container_docker_executable_invalid");
  requireThat(isAbsolute(configuration.socket) && realpathSync(configuration.socket) === configuration.socket && lstatSync(configuration.socket).isSocket(), "container_local_socket_required");
  const root = lstatSync(configuration.state_root);
  requireThat(root.isDirectory() && root.uid === process.getuid?.() && (root.mode & 0o077) === 0, "container_private_state_required");
}
