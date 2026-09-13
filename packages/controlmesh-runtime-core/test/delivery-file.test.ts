import { afterEach, expect, test } from "bun:test";
import { mkdtempSync, mkdirSync, rmSync, symlinkSync, writeFileSync, renameSync, truncateSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { captureDeliveryFile } from "../src/delivery-file";
const roots: string[] = [];
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });
function setup() {
  const base = mkdtempSync(join(tmpdir(), "cm-delivery-file-")); roots.push(base);
  const root = join(base, "allowed"); mkdirSync(root); writeFileSync(join(root, "result.txt"), "published result");
  return { base, root, path: join(root, "result.txt") };
}
test("capture binds bytes and descriptor identity within the explicitly allowed root", () => {
  const f = setup(), captured = captureDeliveryFile(f.root, "result.txt", () => {});
  expect(captured.bytes.toString()).toBe("published result"); expect(captured.filename).toBe("result.txt");
  expect(captured.snapshot.sha256).toMatch(/^[a-f0-9]{64}$/); captured.assertCurrent();
  writeFileSync(f.path, "changed result"); expect(captured.bytes.toString()).toBe("published result");
  expect(() => captured.assertCurrent()).toThrow("delivery_file_changed");
});
test("links, directory traversal and directories cannot become upload bytes", () => {
  const f = setup(); writeFileSync(join(f.base, "private"), "outside"); symlinkSync(join(f.base, "private"), join(f.root, "link"));
  for (const path of ["../private", join(f.base, "private"), "link", "."]) expect(() => captureDeliveryFile(f.root, path, () => {})).toThrow();
});
test("root replacement and retained-buffer tampering invalidate upload admission", () => {
  const f = setup(), captured = captureDeliveryFile(f.root, f.path, () => {});
  captured.bytes[0] = 0; expect(() => captured.assertCurrent()).toThrow("delivery_file_buffer_changed");
  const again = captureDeliveryFile(f.root, f.path, () => {}); renameSync(f.root, join(f.base, "old")); mkdirSync(f.root); writeFileSync(f.path, "published result");
  expect(() => again.assertCurrent()).toThrow("delivery_file_changed");
});
test("oversized media is rejected before allocation, and current authority is required", () => {
  const f = setup(); truncateSync(f.path, 50 * 1024 * 1024 + 1);
  expect(() => captureDeliveryFile(f.root, f.path, () => {})).toThrow("delivery_file_too_large");
  writeFileSync(f.path, "data"); let revoked = false;
  const captured = captureDeliveryFile(f.root, f.path, () => { if (revoked) throw new Error("revoked"); });
  revoked = true; expect(() => captured.assertCurrent()).toThrow("revoked");
});

test("media capture supports files larger than native context snapshots without weakening its cap", () => {
  const f = setup(); truncateSync(f.path, 5 * 1024 * 1024);
  const captured = captureDeliveryFile(f.root, f.path, () => {});
  expect(captured.bytes.length).toBe(5 * 1024 * 1024); captured.assertCurrent();
});

test("authority loss during chunked capture prevents returning partial upload content", () => {
  const f = setup(); truncateSync(f.path, 256 * 1024); let checks = 0;
  expect(() => captureDeliveryFile(f.root, f.path, () => { if (++checks === 4) throw new Error("revoked-during-read"); })).toThrow("revoked-during-read");
});
