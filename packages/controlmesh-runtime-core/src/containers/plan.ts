import { lstatSync, realpathSync } from "node:fs";
import { isAbsolute, join, relative, sep } from "node:path";
import { directoryIdentity, type DirectoryIdentity } from "../providers/native-manifest";
import { digest, requireThat } from "../value";

export interface ContainerConfiguration {
  docker: string;
  socket: string;
  state_root: string;
  image_id: string;
  node_executable: string;
  workspace_layout?: "portable" | "native";
  resources?: readonly { source: string; readonly: boolean }[];
  memory_mb?: number;
  pids?: number;
  cpus?: number;
}
export interface ContainerMount { source: string; target: string; readonly: boolean; kind: "file" | "directory"; identity: DirectoryIdentity }
export interface WorkspaceProjection { source: string; target: string; readonly: boolean }
export interface ContainerPlan { mounts: ContainerMount[]; working_directory: string; network: "none" | "bridge"; memory: number; pids: number; cpus: number; user: string }

export function contains(root: string, child: string): boolean {
  const part = relative(root, child);
  return part === "" || (!part.startsWith(`..${sep}`) && part !== ".." && !isAbsolute(part));
}
function canonicalDirectory(path: string): DirectoryIdentity {
  requireThat(isAbsolute(path) && !/[\x00\r\n,]/.test(path) && realpathSync(path) === path, "container_path_not_canonical");
  return directoryIdentity(path);
}
function assertNativeTarget(path: string, node: string): void {
  const reserved = ["/proc", "/sys", "/dev", "/run", "/cm-control", "/tmp/cm-home", "/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc", node];
  requireThat(!reserved.some(root => contains(root, path) || contains(path, root)), "container_native_workspace_conflict");
}

/** Explicit device-local native resources. Only regular read-only files or directories are mounted. */
export function resourceMounts(configuration: ContainerConfiguration): ContainerMount[] {
  const resources = configuration.resources ?? [];
  requireThat(Array.isArray(resources) && resources.length <= 16, "invalid_container_resources");
  const seen = new Set<string>();
  return resources.map(resource => {
    const path = resource.source;
    requireThat(typeof path === "string" && isAbsolute(path) && !/[\x00\r\n,]/.test(path) && realpathSync(path) === path, "container_path_not_canonical");
    requireThat(typeof resource.readonly === "boolean" && !seen.has(path), "invalid_container_resources");
    seen.add(path);
    assertNativeTarget(path, configuration.node_executable);
    requireThat(!contains(path, configuration.state_root) && !contains(configuration.state_root, path), "container_resource_control_overlap");
    const stat = lstatSync(path, { bigint: true });
    requireThat(stat.isDirectory() || (stat.isFile() && resource.readonly), "invalid_container_resource_type");
    const kind = stat.isDirectory() ? "directory" as const : "file" as const;
    return { source: path, target: path, readonly: resource.readonly, kind, identity: { path, device: String(stat.dev), inode: String(stat.ino) } };
  }).sort((a, b) => a.source.length - b.source.length);
}
export function planContainer(configuration: ContainerConfiguration, workspace: string, roots: readonly string[], noNetwork: boolean,
  projection: readonly WorkspaceProjection[] = []): ContainerPlan {
  requireThat(/^sha256:[0-9a-f]{64}$/.test(configuration.image_id), "container_image_digest_required");
  requireThat(isAbsolute(configuration.node_executable) && !/[\x00\r\n]/.test(configuration.node_executable), "invalid_container_node");
  const state = canonicalDirectory(configuration.state_root), directory = canonicalDirectory(workspace);
  requireThat(!["/proc", "/sys", "/dev", "/run"].some(root => contains(root, workspace)), "container_system_workspace_forbidden");
  requireThat(!contains(workspace, state.path) && !contains(state.path, workspace), "container_state_workspace_overlap");
  const uid = process.getuid?.(), gid = process.getgid?.();
  requireThat(typeof uid === "number" && uid > 0 && typeof gid === "number" && gid > 0, "container_nonroot_owner_required");
  const layout = configuration.workspace_layout ?? "portable";
  requireThat(layout === "portable" || layout === "native", "invalid_container_workspace_layout");
  const workingDirectory = layout === "native" ? workspace : "/workspace";
  if (layout === "native") {
    // Preserve the provider's original directory without shadowing the image runtime,
    // kernel filesystems, controller lease or the helper's private temporary home.
    assertNativeTarget(workspace, configuration.node_executable);
  }
  const mount = (source: string, readonly: boolean): ContainerMount => ({ source, target: join(workingDirectory, relative(workspace, source)), readonly, kind: "directory", identity: canonicalDirectory(source) });
  const allowed = [...new Set(roots)];
  requireThat(allowed.length <= 64, "too_many_container_write_roots");
  for (const root of allowed) requireThat(isAbsolute(root) && contains(workspace, root), "container_write_root_outside_workspace");
  let mounts = [mount(directory.path, !allowed.includes(workspace)), ...allowed.filter(root => root !== workspace && !allowed.some(parent => parent !== root && contains(parent, root))).map(root => mount(root, false))];
  requireThat(Array.isArray(projection) && projection.length <= 128 && (!projection.length || (layout === "native" && allowed.length === 0)), "container_projection_requires_readonly_canonical_workspace");
  const seen = new Set<string>();
  for (const entry of [...projection].sort((a, b) => a.target.length - b.target.length)) {
    const { source, target, readonly } = entry;
    requireThat(typeof readonly === "boolean" && isAbsolute(source) && isAbsolute(target) && !/[\x00\r\n,]/.test(source + target)
      && contains(workspace, target) && !seen.has(target), "invalid_container_projection"); seen.add(target);
    const stat = lstatSync(source, { bigint: true });
    requireThat(realpathSync(source) === source && (stat.isDirectory() || (stat.isFile() && readonly)), "invalid_container_projection_source");
    if (readonly) requireThat(source === target && relative(workspace, target).split(sep).includes(".git"), "container_projection_readonly_scope_invalid");
    else {
      requireThat(!contains(workspace, source) && !contains(source, workspace) && !contains(state.path, source) && !contains(source, state.path)
        && !relative(workspace, target).split(sep).includes(".git"), "container_projection_canonical_write_forbidden");
      requireThat(!projection.some(other => !other.readonly && other !== entry && other.target !== target
        && (contains(other.target, target) || contains(target, other.target))), "container_projection_overlap");
      for (const resource of resourceMounts(configuration)) requireThat(!contains(source, resource.source) && !contains(resource.source, source), "container_projection_resource_overlap");
    }
    const projected: ContainerMount = { source, target, readonly, kind: stat.isDirectory() ? "directory" : "file",
      identity: { path: source, device: String(stat.dev), inode: String(stat.ino) } };
    if (target === workspace) mounts = [projected]; else mounts.push(projected);
  }
  for (const resource of resourceMounts(configuration)) {
    requireThat(!contains(resource.source, workspace) && !contains(workspace, resource.source)
      && !contains(resource.target, workingDirectory) && !contains(workingDirectory, resource.target), "container_resource_workspace_overlap");
    for (const parent of mounts) if (contains(parent.target, resource.target)) requireThat(resource.kind === "file" && resource.readonly, "container_resource_overlap");
    mounts.push(resource);
  }
  const memory = configuration.memory_mb ?? 1024, pids = configuration.pids ?? 128, cpus = configuration.cpus ?? 1;
  requireThat(Number.isSafeInteger(memory) && memory >= 64 && memory <= 16384 && Number.isSafeInteger(pids) && pids >= 16 && pids <= 1024 && Number.isFinite(cpus) && cpus >= 0.1 && cpus <= 16, "invalid_container_resource_limits");
  return { mounts, working_directory: workingDirectory, network: noNetwork ? "none" : "bridge", memory, pids, cpus, user: `${uid}:${gid}` };
}
export function assertMounts(plan: ContainerPlan): void {
  for (const mount of plan.mounts) {
    const stat = lstatSync(mount.source, { bigint: true });
    requireThat(realpathSync(mount.source) === mount.source && (mount.kind === "directory" ? stat.isDirectory() : stat.isFile())
      && digest({ path: mount.source, device: String(stat.dev), inode: String(stat.ino) }) === digest(mount.identity), "container_mount_replaced");
  }
}
export function assertLocalDocker(configuration: ContainerConfiguration): void {
  requireThat(process.platform === "linux", "container_platform_unverified");
  requireThat(isAbsolute(configuration.docker) && realpathSync(configuration.docker) === configuration.docker && lstatSync(configuration.docker).isFile(), "container_docker_executable_invalid");
  requireThat(isAbsolute(configuration.socket) && realpathSync(configuration.socket) === configuration.socket && lstatSync(configuration.socket).isSocket(), "container_local_socket_required");
  const root = lstatSync(configuration.state_root);
  requireThat(root.isDirectory() && root.uid === process.getuid?.() && (root.mode & 0o077) === 0, "container_private_state_required");
}
