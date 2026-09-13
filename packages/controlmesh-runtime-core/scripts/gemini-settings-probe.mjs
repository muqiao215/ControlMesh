import { createHash } from "node:crypto";
import { registerHooks } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";

try {
  if (process.env.NODE_OPTIONS || JSON.stringify(process.execArgv) !== JSON.stringify(["--experimental-permission", "--allow-fs-read=*"])) throw new Error("fixed_probe_flags_required");
  if (!process.permission || process.permission.has("fs.write") || process.permission.has("child") || process.permission.has("worker")) throw new Error("permission_boundary_required");
  const [modulePath, workspace] = process.argv.slice(2);
  if (!modulePath?.startsWith("/") || !workspace?.startsWith("/") || !process.argv.includes("--ignore-env")) throw new Error("invalid_settings_probe");
  let registered;
  if (process.argv.includes("--registered-runtime")) {
    let input = "";
    for await (const chunk of process.stdin) { input += chunk; if (Buffer.byteLength(input) > 65536) throw new Error("runtime_manifest_limit"); }
    const files = JSON.parse(input);
    if (!Array.isArray(files) || files.length > 1024 || !files.every(file => typeof file === "string" && file.startsWith("/"))) throw new Error("invalid_runtime_manifest");
    registered = new Set(files);
  }
  const loadedFiles = new Set();
  registerHooks({ load(url, context, nextLoad) {
    if (url.startsWith("file:")) {
      const path = fileURLToPath(url);
      if (registered && !registered.has(path)) throw new Error("gemini_unregistered_runtime_dependency");
      loadedFiles.add(path);
      if (loadedFiles.size > 256) throw new Error("native_dependency_limit");
    } else if (!url.startsWith("node:")) throw new Error("unsupported_native_module_source");
    return nextLoad(url, context);
  } });
  const native = await import(pathToFileURL(modulePath).href);
  const settings = native.loadSettings(workspace);
  if (!settings.merged || settings.errors?.some(error => error.severity === "error")) throw new Error("native_settings_invalid");
  const sort = value => Array.isArray(value) ? value.map(sort) : value && typeof value === "object"
    ? Object.fromEntries(Object.keys(value).sort().map(key => [key, sort(value[key])])) : value;
  const settings_digest = createHash("sha256").update(JSON.stringify(sort(settings.merged))).digest("hex");
  console.log(JSON.stringify({ schema_version: "gemini.settings_probe.v1", settings_digest, loaded_runtime_files: [...loadedFiles].sort(), registration_checked: Boolean(registered),
    sources: [settings.system, settings.systemDefaults, settings.user, settings.workspace].flatMap(layer => layer?.path ? [layer.path] : []) }));
} catch (error) {
  console.log(JSON.stringify({ error: error?.message === "gemini_unregistered_runtime_dependency" ? error.message : "gemini_settings_probe_failed" })); process.exitCode = 2;
}
