import { closeSync, constants, fstatSync, openSync, readSync, realpathSync } from "node:fs";
import { createHash } from "node:crypto";
import { isAbsolute } from "node:path";
import { digest, requireThat } from "./value";

/** Bounded descriptor read; never log configuration or credential content. */
export function privateFile(path: string, maxBytes = 2 * 1024 * 1024): { bytes: Buffer; revision: string } {
  requireThat(Number.isSafeInteger(maxBytes) && maxBytes > 0 && maxBytes <= 16 * 1024 * 1024, "invalid_private_file_limit");
  requireThat(isAbsolute(path) && realpathSync(path) === path, "private_config_path_required");
  const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const before = fstatSync(fd);
    requireThat(before.isFile() && before.uid === process.getuid?.() && (before.mode & 0o077) === 0 && before.size <= maxBytes, "private_runtime_config_required");
    const bounded = Buffer.alloc(before.size + 1);
    let count = 0;
    while (count < bounded.length) { const read = readSync(fd, bounded, count, bounded.length - count, null); if (!read) break; count += read; }
    const bytes = bounded.subarray(0, count), after = fstatSync(fd);
    requireThat(bytes.byteLength === before.size && before.size === after.size && before.mtimeMs === after.mtimeMs && before.ctimeMs === after.ctimeMs, "runtime_config_changed");
    return { bytes, revision: digest({ device: before.dev, inode: before.ino, content: createHash("sha256").update(bytes).digest("hex") }) };
  } finally { closeSync(fd); }
}
