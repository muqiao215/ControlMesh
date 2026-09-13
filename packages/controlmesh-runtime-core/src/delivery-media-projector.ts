import { lstatSync, realpathSync } from "node:fs";
import { extname, isAbsolute, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import type { TerminalDelivery } from "@controlmesh/protocol";
import { captureDeliveryFile } from "./delivery-file";
import { DeliveryMediaStore } from "./delivery-media";
import { deliveryTextParts } from "./delivery-text-parts";
import { requireThat } from "./value";

/** Explicit configured roots issue file access; file tags merely select within them. */
export class DeliveryMediaProjector {
  private readonly roots: { path: string; device: string; inode: string }[];
  constructor(roots: unknown, readonly store: DeliveryMediaStore, private readonly authorize: () => void) {
    requireThat(Array.isArray(roots) && roots.length > 0 && roots.length <= 16 && roots.every(root => typeof root === "string"), "delivery_media_roots_required");
    this.roots = roots.map(path => {
      requireThat(isAbsolute(path) && resolve(path) === path && realpathSync(path) === path, "delivery_media_root_invalid");
      const stat = lstatSync(path, { bigint: true }); requireThat(stat.isDirectory(), "delivery_media_root_invalid");
      return { path, device: String(stat.dev), inode: String(stat.ino) };
    });
  }
  current(): void {
    const checked: unknown = this.authorize();
    if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    for (const root of this.roots) {
      const stat = lstatSync(root.path, { bigint: true });
      requireThat(stat.isDirectory() && realpathSync(root.path) === root.path && String(stat.dev) === root.device && String(stat.ino) === root.inode, "delivery_media_root_changed");
    }
  }
  project(envelope: TerminalDelivery, choices: TerminalDelivery["choices"], capacity: number): TerminalDelivery[] | null {
    this.current();
    const paths: string[] = [];
    const text = envelope.text.replace(/<file:([^>]+)>/g, (_whole, raw: string) => {
      let value = raw.trim();
      if (value.startsWith("file:")) value = fileURLToPath(value);
      else { requireThat(!value.includes("://"), "delivery_media_path_invalid"); value = decodeURIComponent(value); }
      requireThat(isAbsolute(value) && !value.includes("\0"), "delivery_media_absolute_path_required");
      paths.push(resolve(value)); return "";
    }).trim();
    requireThat(paths.length <= 16, "delivery_media_count_exceeded");
    const texts = text ? deliveryTextParts({ ...envelope, text }) : paths.length ? [] : [envelope.text];
    if (texts.length + paths.length > capacity) return null;
    const parts: TerminalDelivery[] = texts.map(text => ({ ...envelope, text }));
    for (const path of paths) parts.push({ ...envelope, text: path.slice(path.lastIndexOf(sep) + 1) });
    for (const [index, part] of parts.entries()) {
      part.delivery_id = index === 0 ? envelope.delivery_id : `${envelope.delivery_id}.${index}`;
      if (choices && index === parts.length - 1) part.choices = choices;
    }
    for (const [index, path] of paths.entries()) {
      const root = this.roots.find(root => { const inner = relative(root.path, path); return inner && !isAbsolute(inner) && inner !== ".." && !inner.startsWith(`..${sep}`); });
      requireThat(root, "delivery_media_outside_roots");
      const captured = captureDeliveryFile(root.path, path, () => this.current());
      const bytes = captured.bytes, extension = extname(path).toLowerCase();
      const image = (bytes.subarray(0, 8).equals(Buffer.from([137,80,78,71,13,10,26,10])) || bytes.subarray(0, 3).equals(Buffer.from([255,216,255]))
        || /^GIF8[79]a$/.test(bytes.subarray(0, 6).toString()) || (bytes.subarray(0,4).toString() === "RIFF" && bytes.subarray(8,12).toString() === "WEBP") || bytes.subarray(0,2).toString() === "BM");
      const mp4 = bytes.subarray(4,8).toString() === "ftyp";
      const mp3 = bytes.subarray(0,3).toString() === "ID3" || (bytes.length >= 2 && bytes[0] === 255 && (bytes[1]! & 224) === 224);
      const kind = image && [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"].includes(extension) ? "photo"
        : mp4 && extension === ".mp4" ? "video" : (mp3 && extension === ".mp3") || (mp4 && extension === ".m4a") ? "audio" : "document";
      const part = parts[texts.length + index]!; part.media = this.store.stage(part, captured, kind);
    }
    this.current(); return parts;
  }
  accepted(envelope: TerminalDelivery): void { this.current(); this.store.release(envelope); }
  read(envelope: TerminalDelivery): Buffer { this.current(); return this.store.read(envelope); }
}
