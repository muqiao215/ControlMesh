import { createHash } from "node:crypto";
import { closeSync, constants, fstatSync, lstatSync, openSync, readSync, realpathSync } from "node:fs";
import { isAbsolute } from "node:path";
import { RuntimeDatabase } from "./database";
import { RuntimeEventStore } from "./runtime-events";
import { identifier, requireThat } from "./value";

export function runtimeEventFileSnapshot(path: string) {
  requireThat(isAbsolute(path) && realpathSync(path) === path, "event_source_must_be_canonical");
  const before = lstatSync(path, { bigint: true });
  requireThat(before.isFile() && before.size <= 16n * 1024n * 1024n, "event_source_invalid");
  const stamp = (s: typeof before) => [s.dev, s.ino, s.size, s.mtimeNs, s.ctimeNs].map(String).join(":");
  const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    requireThat(stamp(fstatSync(fd, { bigint: true })) === stamp(before), "event_source_changed");
    const bytes = Buffer.alloc(Number(before.size) + 1); let count = 0;
    while (count < bytes.length) { const n = readSync(fd, bytes, count, bytes.length - count, null); if (!n) break; count += n; }
    requireThat(count === Number(before.size) && stamp(fstatSync(fd, { bigint: true })) === stamp(before)
      && stamp(lstatSync(path, { bigint: true })) === stamp(before) && realpathSync(path) === path, "event_source_changed");
    const content = bytes.subarray(0, count);
    return { text: new TextDecoder("utf-8", { fatal: true }).decode(content), sha256: createHash("sha256").update(content).digest("hex"), bytes: count };
  } finally { closeSync(fd); }
}
export function importRuntimeEventFile(input: { source: string; database: string; principal: string; session: string; apply: boolean; sha256?: string }) {
  identifier(input.principal);
  requireThat(isAbsolute(input.database), "database_path_must_be_explicit");
  requireThat(!input.apply || (typeof input.sha256 === "string" && /^[a-f0-9]{64}$/.test(input.sha256)), "event_source_digest_required");
  const source = runtimeEventFileSnapshot(input.source);
  requireThat(!input.apply || source.sha256 === input.sha256, "event_source_digest_changed");
  // Validate the full batch before touching a target database, including schema upgrades.
  const preview = new RuntimeDatabase(":memory:");
  let validated: { imported: number; replayed: number };
  try { validated = new RuntimeEventStore(preview).importJsonl(input.principal, input.session, source.text); }
  finally { preview.close(); }
  if (!input.apply) return { mode: "dry_run", sha256: source.sha256, bytes: source.bytes, unique_events: validated.imported, duplicate_events: validated.replayed };
  const target = new RuntimeDatabase(input.database);
  try { return { mode: "applied", sha256: source.sha256, bytes: source.bytes, ...new RuntimeEventStore(target).importJsonl(input.principal, input.session, source.text) }; }
  finally { target.close(); }
}
