import { createHash } from "node:crypto";
import { pathToFileURL } from "node:url";

try {
  if (process.env.NODE_OPTIONS || JSON.stringify(process.execArgv) !== JSON.stringify(["--experimental-permission", "--allow-fs-read=*"])) throw new Error("fixed_probe_flags_required");
  if (!process.permission || process.permission.has("fs.write") || process.permission.has("child") || process.permission.has("worker")) throw new Error("permission_boundary_required");
  const [modulePath, workspace] = process.argv.slice(2);
  if (!modulePath?.startsWith("/") || !workspace?.startsWith("/") || !process.argv.includes("--ignore-env")) throw new Error("invalid_settings_probe");
  const native = await import(pathToFileURL(modulePath).href);
  const settings = native.loadSettings(workspace);
  if (!settings.merged || settings.errors?.some(error => error.severity === "error")) throw new Error("native_settings_invalid");
  const sort = value => Array.isArray(value) ? value.map(sort) : value && typeof value === "object"
    ? Object.fromEntries(Object.keys(value).sort().map(key => [key, sort(value[key])])) : value;
  const settings_digest = createHash("sha256").update(JSON.stringify(sort(settings.merged))).digest("hex");
  console.log(JSON.stringify({ schema_version: "gemini.settings_probe.v1", settings_digest,
    sources: [settings.system, settings.systemDefaults, settings.user, settings.workspace].flatMap(layer => layer?.path ? [layer.path] : []) }));
} catch {
  console.log(JSON.stringify({ error: "gemini_settings_probe_failed" })); process.exitCode = 2;
}
