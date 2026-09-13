import { createHash } from "node:crypto";
import { closeSync, constants, fstatSync, lstatSync, openSync, readSync, realpathSync } from "node:fs";
import { basename, isAbsolute, relative, resolve, sep } from "node:path";
import { digest, requireThat } from "./value";

export interface DeliveryFileSnapshot {
  root: string; root_device: string; root_inode: string; path: string;
  device: string; inode: string; size: number; modified_ns: string; changed_ns: string; sha256: string;
}
export interface CapturedDeliveryFile {
  filename: string; bytes: Buffer; snapshot: DeliveryFileSnapshot; assertCurrent(): void;
}
const maximumBytes = 50 * 1024 * 1024;

/** The caller supplies an authorized canonical root; a file tag never grants a root. */
export function captureDeliveryFile(root: string, requested: string, authorize: () => void): CapturedDeliveryFile {
  const current = () => {
    const result: unknown = authorize();
    if (result !== undefined) { void Promise.resolve(result).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
  };
  current();
  requireThat(isAbsolute(root) && resolve(root) === root && realpathSync(root) === root, "delivery_file_root_invalid");
  requireThat(typeof requested === "string" && requested.length > 0 && !requested.includes("\0"), "delivery_file_path_invalid");
  const path = resolve(root, requested), inside = relative(root, path);
  requireThat(inside !== "" && !isAbsolute(inside) && inside !== ".." && !inside.startsWith(`..${sep}`), "delivery_file_outside_root");
  const metadata = () => {
    const parent = lstatSync(root, { bigint: true }), file = lstatSync(path, { bigint: true });
    requireThat(parent.isDirectory() && file.isFile() && realpathSync(root) === root && realpathSync(path) === path, "delivery_file_replaced");
    requireThat(file.size >= 0n && file.size <= BigInt(maximumBytes), "delivery_file_too_large");
    return { root, root_device: String(parent.dev), root_inode: String(parent.ino), path,
      device: String(file.dev), inode: String(file.ino), size: Number(file.size), modified_ns: String(file.mtimeNs), changed_ns: String(file.ctimeNs) };
  };
  const before = metadata(); current();
  const descriptor = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  let bytes: Buffer;
  try {
    const file = fstatSync(descriptor, { bigint: true });
    requireThat(file.isFile() && String(file.dev) === before.device && String(file.ino) === before.inode && Number(file.size) === before.size
      && String(file.mtimeNs) === before.modified_ns && String(file.ctimeNs) === before.changed_ns, "delivery_file_replaced");
    bytes = Buffer.alloc(before.size); let offset = 0;
    while (offset < bytes.length) {
      current(); const count = readSync(descriptor, bytes, offset, Math.min(65536, bytes.length - offset), offset);
      requireThat(count > 0, "delivery_file_changed"); offset += count;
    }
    requireThat(readSync(descriptor, Buffer.alloc(1), 0, 1, bytes.length) === 0, "delivery_file_changed");
    const after = fstatSync(descriptor, { bigint: true });
    requireThat(after.size === file.size && after.mtimeNs === file.mtimeNs && after.ctimeNs === file.ctimeNs, "delivery_file_changed");
  } finally { closeSync(descriptor); }
  const sha256 = createHash("sha256").update(bytes).digest("hex");
  const assertCurrent = () => {
    current(); requireThat(digest(metadata()) === digest(before), "delivery_file_changed");
    requireThat(createHash("sha256").update(bytes).digest("hex") === sha256, "delivery_file_buffer_changed");
  };
  assertCurrent();
  return { filename: basename(path), bytes, snapshot: { ...before, sha256 }, assertCurrent };
}
