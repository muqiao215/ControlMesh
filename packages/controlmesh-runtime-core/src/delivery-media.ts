import { createHash } from "node:crypto";
import { assertProtocolSchema, type TerminalDelivery } from "@controlmesh/protocol";
import { requireScope } from "./commands";
import type { CapturedDeliveryFile } from "./delivery-file";
import type { Principal, RuntimeKernel } from "./kernel";
import { canonical, digest, requireThat } from "./value";

type Media = NonNullable<TerminalDelivery["media"]>;
interface MediaRow { id: string; principal: string; task_id: string; task_revision: number; event_seq: number;
  binding_digest: string; metadata: string; source: string; content: Buffer }
const sha = (bytes: Uint8Array) => createHash("sha256").update(bytes).digest("hex");

/** Retained upload bytes. Transport requests never receive the private source path. */
export class DeliveryMediaStore {
  private readonly actor: Principal;
  constructor(private readonly kernel: RuntimeKernel, actor: Principal, private readonly authorize: () => void) { this.actor = structuredClone(actor); }
  private current(scope: string, envelope: TerminalDelivery): void {
    requireScope(this.actor, scope);
    const checked: unknown = this.authorize();
    if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    this.kernel.inspect(this.actor, envelope.task_id);
    const event = this.kernel.db.sql.query("SELECT task_id,revision,kind FROM events WHERE seq=?").get(envelope.event_seq) as { task_id: string; revision: number; kind: string } | null;
    requireThat(event && event.task_id === envelope.task_id && event.revision === envelope.task_revision
      && event.kind === `task.${envelope.status}`, "delivery_media_event_mismatch");
  }
  stage(envelope: TerminalDelivery, captured: CapturedDeliveryFile, kind: "photo" | "video" | "audio" | "document"): Media {
    this.current("delivery:project", envelope); captured.assertCurrent();
    requireThat(envelope.media === undefined && captured.bytes.length === captured.snapshot.size && sha(captured.bytes) === captured.snapshot.sha256,
      "delivery_media_capture_mismatch");
    const metadata: Media = { id: digest([envelope, captured.snapshot, kind]), filename: captured.filename,
      size: captured.bytes.length, sha256: captured.snapshot.sha256, kind };
    assertProtocolSchema("terminal-delivery.schema.json", { ...envelope, media: metadata });
    const source = canonical(captured.snapshot), binding = digest([this.actor.id, envelope, metadata, source]);
    return this.kernel.db.transaction(() => {
      this.current("delivery:project", envelope); captured.assertCurrent();
      requireThat(this.kernel.inspect(this.actor, envelope.task_id).revision === envelope.task_revision, "delivery_media_capture_stale");
      const previous = this.kernel.db.sql.query("SELECT * FROM delivery_media WHERE id=?").get(metadata.id as string) as MediaRow | null;
      if (previous) {
        requireThat(previous.binding_digest === binding && previous.principal === this.actor.id
          && sha(previous.content) === metadata.sha256, "delivery_media_conflict");
        return structuredClone(metadata);
      }
      const usage = this.kernel.db.sql.query("SELECT COALESCE(SUM(length(content)),0) AS bytes,COUNT(*) AS n FROM delivery_media").get() as { bytes: number; n: number };
      requireThat(usage.bytes + captured.bytes.length <= 256 * 1024 * 1024 && usage.n < 128, "delivery_media_store_full");
      this.kernel.db.sql.query("INSERT INTO delivery_media VALUES (?,?,?,?,?,?,?,?,?)")
        .run(metadata.id as string, this.actor.id, envelope.task_id, envelope.task_revision, envelope.event_seq, binding, canonical(metadata), source, captured.bytes);
      return structuredClone(metadata);
    });
  }
  release(envelope: TerminalDelivery): void {
    if (!envelope.media) return;
    this.current("delivery:read", envelope);
    const sent = this.kernel.db.sql.query("SELECT state,envelope_digest,receipt FROM delivery_outbox WHERE delivery_id=? AND principal=?")
      .get(envelope.delivery_id, this.actor.id) as { state: string; envelope_digest: string; receipt: string | null } | null;
    requireThat(sent?.state === "sent" && sent.envelope_digest === digest(envelope) && sent.receipt, "delivery_media_release_unconfirmed");
    const receipt = JSON.parse(sent.receipt);
    requireThat(receipt.envelope_digest === digest(envelope) && receipt.delivery_id === envelope.delivery_id, "delivery_media_release_unconfirmed");
    this.kernel.db.sql.query("DELETE FROM delivery_media WHERE id=? AND principal=? AND task_id=?")
      .run(envelope.media.id as string, this.actor.id, envelope.task_id);
  }
  read(envelope: TerminalDelivery): Buffer {
    this.current("delivery:read", envelope); assertProtocolSchema("terminal-delivery.schema.json", envelope);
    const media = envelope.media; requireThat(media && typeof media.id === "string", "delivery_media_reference_required");
    const row = this.kernel.db.sql.query("SELECT * FROM delivery_media WHERE id=? AND principal=?").get(media.id, this.actor.id) as MediaRow | null;
    requireThat(row && row.task_id === envelope.task_id && row.task_revision === envelope.task_revision && row.event_seq === envelope.event_seq,
      "delivery_media_owner_mismatch");
    const { media: _media, ...base } = envelope;
    requireThat(row.metadata === canonical(media) && row.binding_digest === digest([this.actor.id, base, media, row.source])
      && row.content.length === media.size && sha(row.content) === media.sha256, "delivery_media_corrupted");
    return Buffer.from(row.content);
  }
}
