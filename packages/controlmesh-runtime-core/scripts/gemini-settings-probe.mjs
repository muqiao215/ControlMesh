import fs from "node:fs";
import { syncBuiltinESMExports } from "node:module";
import { geminiSourceIdentity } from "./gemini-source-identity.mjs";
import { createHash } from "node:crypto";
import { registerHooks } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";

try {
  if (process.env.NODE_OPTIONS || JSON.stringify(process.execArgv) !== JSON.stringify(["--experimental-permission", "--allow-fs-read=*"])) throw new Error("fixed_probe_flags_required");
  if (!process.permission || process.permission.has("fs.write") || process.permission.has("child") || process.permission.has("worker")) throw new Error("permission_boundary_required");
  const [modulePath, workspace] = process.argv.slice(2);
  if (!modulePath?.startsWith("/") || !workspace?.startsWith("/") || !process.argv.includes("--ignore-env")) throw new Error("invalid_settings_probe");
  let registered, registeredSources;
  if (process.argv.includes("--registered-runtime")) {
    let input = "";
    for await (const chunk of process.stdin) { input += chunk; if (Buffer.byteLength(input) > 65536) throw new Error("runtime_manifest_limit"); }
    const manifest = JSON.parse(input), files = manifest.runtime_files;
    if (!Array.isArray(manifest.settings_sources) || manifest.settings_sources.length > 256 || !manifest.settings_sources.every(path => typeof path === "string")) throw new Error("invalid_source_manifest");
    registeredSources = new Set(manifest.settings_sources);
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
  const observedSources = new Map(), originalRead = fs.readFileSync, originalExists = fs.existsSync;
  let sourceFailure = false;
  const record = value => {
    try {
      const source = geminiSourceIdentity(value);
      if (registeredSources && !registeredSources.has(source.path)) throw new Error("unregistered_settings_source");
      if (observedSources.has(source.path) && observedSources.get(source.path) !== source.identity) throw new Error("settings_source_changed");
      observedSources.set(source.path, source.identity);
      if (observedSources.size > 256) throw new Error("settings_source_limit");
    } catch (error) { sourceFailure = true; throw error; }
  };
  let settings;
  try {
    fs.readFileSync = (...args) => { record(args[0]); const result = originalRead(...args); record(args[0]); return result; };
    fs.existsSync = (...args) => { record(args[0]); const result = originalExists(...args); record(args[0]); return result; };
    syncBuiltinESMExports(); settings = native.loadSettings(workspace);
  } finally { fs.readFileSync = originalRead; fs.existsSync = originalExists; syncBuiltinESMExports(); }
  if (sourceFailure) throw new Error("settings_source_unproven");
  for (const [path, identity] of observedSources) if (geminiSourceIdentity(path).identity !== identity) throw new Error("settings_source_changed");
  if (!settings.merged || settings.errors?.some(error => error.severity === "error")) throw new Error("native_settings_invalid");
  const sort = value => Array.isArray(value) ? value.map(sort) : value && typeof value === "object"
    ? Object.fromEntries(Object.keys(value).sort().map(key => [key, sort(value[key])])) : value;
  const settings_digest = createHash("sha256").update(JSON.stringify(sort(settings.merged))).digest("hex");
  console.log(JSON.stringify({ schema_version: "gemini.settings_probe.v1", settings_digest, loaded_runtime_files: [...loadedFiles].sort(), registration_checked: Boolean(registered),
    settings_sources: [...observedSources].map(([path, identity]) => ({ path, identity })),
    sources: [settings.system, settings.systemDefaults, settings.user, settings.workspace].flatMap(layer => layer?.path ? [layer.path] : []) }));
} catch (error) {
  console.log(JSON.stringify({ error: error?.message === "gemini_unregistered_runtime_dependency" ? error.message : "gemini_settings_probe_failed" })); process.exitCode = 2;
}
