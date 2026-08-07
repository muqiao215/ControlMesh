export interface ControlMeshPluginManifest {
  schema_version: "controlmesh.plugin_manifest.v1";
  name: string;
  version: string;
  description?: string;
  permissions?: ControlMeshPluginPermission[];
}

export type ControlMeshPluginPermission =
  | "tasks:read"
  | "tasks:write"
  | "artifacts:read"
  | "memory:read"
  | "providers:read"
  | "doctor:run";

export function validatePluginManifest(manifest: ControlMeshPluginManifest): void {
  if (manifest.schema_version !== "controlmesh.plugin_manifest.v1") {
    throw new Error("Unsupported plugin manifest schema_version");
  }
  if (!manifest.name || !manifest.version) {
    throw new Error("Plugin manifest requires name and version");
  }
}
