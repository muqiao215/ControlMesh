import { lstatSync, realpathSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { createHash } from "node:crypto";
export function geminiSourceIdentity(value) {
  if (typeof value !== "string") throw new Error("unsupported_settings_source");
  const path = resolve(value); let existing = path, stat;
  while (true) {
    try { stat = lstatSync(existing, { bigint: true }); break; }
    catch (error) { if (error.code !== "ENOENT") throw error; const parent = dirname(existing); if (parent === existing) throw error; existing = parent; }
  }
  if (realpathSync(existing) !== existing || (!stat.isFile() && !stat.isDirectory())) throw new Error("settings_source_replaced");
  const fields = [path, existing, stat.dev, stat.ino, stat.mode];
  if (existing === path && stat.isFile()) fields.push(stat.size, stat.mtimeNs, stat.ctimeNs);
  return { path, identity: createHash("sha256").update(JSON.stringify(fields.map(String))).digest("hex") };
}
