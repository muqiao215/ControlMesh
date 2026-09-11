import { createHash } from "node:crypto";
import { closeSync, constants, fchmodSync, fstatSync, lstatSync, mkdirSync, openSync, realpathSync } from "node:fs";
import { isAbsolute, join } from "node:path";
import { requireThat } from "../value";
import type { NativeSessionRef } from "./native-session";

const sha = (value: string) => createHash("sha256").update(value).digest("hex");

/** Linux advisory flock interoperates with Python NativeSessionLease during cutover.
 * flock(1) locks an inherited descriptor; the parent retains the same open-file
 * description after the helper exits. No daemon, stale PID lock or FFI is needed.
 */
export class NativeSessionLease {
  private fd: number | null = null;
  private readonly path: string;
  private readonly identity: { dev: bigint; ino: bigint };

  constructor(stateHome: string, storePath: string, ref: NativeSessionRef, flock = "/usr/bin/flock") {
    requireThat(process.platform === "linux", "native_lease_platform_unsupported");
    requireThat(isAbsolute(stateHome) && isAbsolute(flock), "native_lease_path_must_be_explicit");
    const root = join(stateHome, "controlmesh/native-sessions");
    mkdirSync(root, { recursive: true, mode: 0o700 });
    const directory = lstatSync(root);
    requireThat(directory.isDirectory() && (directory.mode & 0o077) === 0 && directory.uid === process.getuid!(), "native_lease_directory_not_private");
    // v1 Python hashes the resolved store path, then '<store-id>:<session-id>'.
    this.path = join(root, sha(`${sha(realpathSync(storePath))}:${ref.session_id}`) + ".lock");
    const fd = openSync(this.path, constants.O_RDWR | constants.O_CREAT | constants.O_NOFOLLOW, 0o600);
    try {
      const stat = fstatSync(fd, { bigint: true });
      requireThat(stat.isFile() && stat.uid === BigInt(process.getuid!()), "native_lease_file_not_private");
      // Legacy Python creates 0644 lock files inside its 0700 directory. Narrow only this owned descriptor.
      fchmodSync(fd, 0o600);
      const result = Bun.spawnSync([flock, "--nonblock", "--conflict-exit-code", "75", "3"], {
        stdio: ["ignore", "pipe", "pipe", fd], timeout: 2_000,
      });
      requireThat(result.exitCode === 0, result.exitCode === 75 ? "native_session_busy" : "native_lease_unavailable");
      this.fd = fd;
      this.identity = { dev: stat.dev, ino: stat.ino };
      this.assertCurrent();
    } catch (error) { this.fd = null; closeSync(fd); throw error; }
  }

  assertCurrent(): void {
    requireThat(this.fd !== null, "native_lease_closed");
    const current = lstatSync(this.path, { bigint: true });
    requireThat(current.isFile() && current.dev === this.identity.dev && current.ino === this.identity.ino, "native_lease_replaced");
  }

  close(): void { if (this.fd !== null) { closeSync(this.fd); this.fd = null; } }
}
