import { expect, test } from "bun:test";
import { closeSync, mkdtempSync, openSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { NativeSessionLease } from "../src/providers/native-lease";
import type { NativeSessionRef } from "../src/providers/native-session";

test("inherited-descriptor flock excludes another owner until parent close; helper exit does not unlock", () => {
  const dir = mkdtempSync(join(tmpdir(), "cm-native-flock-"));
  const path = join(dir, "native.sqlite"); closeSync(openSync(path, "wx", 0o600));
  const ref = { session_id: "ses_Synthetic" } as NativeSessionRef;
  let first: NativeSessionLease | null = null, next: NativeSessionLease | null = null;
  try {
    first = new NativeSessionLease(dir, path, ref);
    expect(() => new NativeSessionLease(dir, path, ref)).toThrow("native_session_busy");
    first.assertCurrent(); first.close();
    expect(() => first!.assertCurrent()).toThrow("native_lease_closed");
    next = new NativeSessionLease(dir, path, ref);
    next.assertCurrent();
  } finally { first?.close(); next?.close(); rmSync(dir, { recursive: true, force: true }); }
});
