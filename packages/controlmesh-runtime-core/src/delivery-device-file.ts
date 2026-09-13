import { createHash } from "node:crypto";
import { posix } from "node:path";
import type { TerminalDelivery } from "@controlmesh/protocol";
import { DeviceArtifactInbox } from "./device-artifacts";
import type { RuntimeKernel, Principal } from "./kernel";
import { digest, object, requireThat } from "./value";

export interface CapturedDeviceDeliveryFile {
  filename: string; bytes: Buffer;
  snapshot: { source: "device_artifact"; task_id: string; revision: number; effect_id: string;
    event_seq: number; path: string; evidence_digest: string; size: number; sha256: string };
  assertCurrent(): void;
}

/** Resolve only the accepted execution named by the original terminal event. */
export class DeliveryDeviceFiles {
  private readonly actor: Principal;
  constructor(private readonly kernel: RuntimeKernel, actor: Principal, private readonly authorize: () => void) {
    this.actor = structuredClone(actor);
  }
  capture(envelope: TerminalDelivery, path: string): CapturedDeviceDeliveryFile {
    const current = () => {
      const checked: unknown = this.authorize();
      if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    };
    current();
    requireThat(path.length > 0 && !/[\\\x00-\x1f]/.test(path)
      && path.split("/").every(part => part && part !== "." && part !== ".." && part !== ".git"), "delivery_device_path_invalid");
    const event = this.kernel.db.sql.query("SELECT task_id,revision,kind,payload FROM events WHERE seq=?")
      .get(envelope.event_seq) as { task_id: string; revision: number; kind: string; payload: string } | null;
    requireThat(envelope.status === "done" && event?.task_id === envelope.task_id && event.revision === envelope.task_revision
      && event.kind === "task.done", "delivery_device_event_mismatch");
    const payload = JSON.parse(event.payload), result = payload.result;
    requireThat(object(result) && result.schema_version === "controlmesh.device_native_result.v1" && object(result.evidence)
      && typeof result.evidence.effect_id === "string", "delivery_device_result_required");
    const effect = result.evidence.effect_id, inbox = new DeviceArtifactInbox(this.kernel);
    const read = (offset: number, hash?: string) => {
      current();
      return inbox.read(this.actor, envelope.task_id, envelope.task_revision, effect, path, offset, hash);
    };
    const first = read(0), chunks = [Buffer.from(first.content_base64, "base64")];
    let page = first;
    while (!page.eof) {
      page = read(page.next_offset, first.sha256); chunks.push(Buffer.from(page.content_base64, "base64"));
    }
    const bytes = Buffer.concat(chunks), sha = () => createHash("sha256").update(bytes).digest("hex");
    const assertCurrent = () => {
      const checked = read(0, first.sha256);
      requireThat(checked.size === first.size && bytes.length === first.size && sha() === first.sha256, "delivery_device_content_changed");
    };
    assertCurrent();
    return { filename: posix.basename(path), bytes, snapshot: { source: "device_artifact", task_id: envelope.task_id,
      revision: envelope.task_revision, effect_id: effect, event_seq: envelope.event_seq, path,
      evidence_digest: digest(result.evidence), size: first.size, sha256: first.sha256 }, assertCurrent };
  }
}
