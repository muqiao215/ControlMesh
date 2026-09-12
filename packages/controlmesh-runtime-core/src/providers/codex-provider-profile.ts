import { requireThat } from "../value";

/** Shared backend selection for the probe and the task using its readiness. */
export function codexProviderArguments(baseUrl?: string): string[] {
  const provider: string[] = [];
  if (baseUrl !== undefined) {
    let url: URL; try { url = new URL(baseUrl); } catch { requireThat(false, "invalid_codex_probe_endpoint"); }
    requireThat(["http:", "https:"].includes(url!.protocol) && !url!.username && !url!.password && !url!.search && !url!.hash, "invalid_codex_probe_endpoint");
    for (const [key, value] of Object.entries({ model_provider: "controlmesh_preflight", "model_providers.controlmesh_preflight.name": "ControlMesh preflight",
      "model_providers.controlmesh_preflight.base_url": baseUrl, "model_providers.controlmesh_preflight.env_key": "OPENAI_API_KEY",
      "model_providers.controlmesh_preflight.wire_api": "responses", "model_providers.controlmesh_preflight.requires_openai_auth": false })) provider.push("-c", `${key}=${JSON.stringify(value)}`);
  }
  return provider;
}
