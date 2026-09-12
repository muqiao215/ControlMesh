import type { DeviceJob } from "./device-coordinator";
import type { DeviceClient, DeviceLeaseAuthority } from "./device-client";
import type { RuntimeDatabase } from "./database";
import { WorkspaceSeedInbox } from "./workspace-seed-inbox";
import { validateWorkspaceSeed } from "./workspace-seed";
import { digest, object, requireThat } from "./value";

export interface DeviceWorkspaceSeedReceiver {
  db: RuntimeDatabase;
  state_root: string;
  /** Explicit local bootstrap permission, independent of native output write grants. */
  files: Readonly<Record<string, readonly string[]>>;
}

/** Download only assigned immutable inputs, under the same lease that admits execution. */
export async function receiveDeviceWorkspaceSeed(client: DeviceClient, job: DeviceJob, workspace: string,
  authority: DeviceLeaseAuthority, assertCurrent: () => void, receiver: DeviceWorkspaceSeedReceiver, signal?: AbortSignal): Promise<void> {
  assertCurrent();
  const ref = job.workspace_seed, allowed = receiver.files[job.workspace_id];
  requireThat(ref && allowed, "workspace_seed_receiver_unavailable");
  const args = () => ({ lease: authority.lease, assignment_digest: job.assignment_digest });
  const response = await client.command("seed_manifest", args(), undefined, signal);
  assertCurrent();
  requireThat(object(response) && digest(response.reference) === digest(ref), "workspace_seed_reference_invalid");
  const manifest = validateWorkspaceSeed(response.manifest, ref.manifest_digest, allowed);
  const inbox = new WorkspaceSeedInbox(receiver.db,
    digest({ direction: "device_workspace_seed", device: client.deviceId, task: job.task_id, assignment: job.assignment_digest, workspace }),
    manifest, ref.manifest_digest, allowed, run => { assertCurrent(); const result = run(); assertCurrent(); return result; });
  inbox.begin();
  for (const file of inbox.status().files) {
    if (file.complete) continue;
    let offset = file.received;
    do {
      assertCurrent();
      const chunk = await client.command("seed_read", { ...args(), path: file.path, offset }, undefined, signal);
      assertCurrent();
      const expected = manifest.files.find(item => item.path === file.path)!;
      requireThat(object(chunk) && chunk.path === file.path && chunk.sha256 === expected.sha256 && chunk.size === file.size
        && chunk.offset === offset && typeof chunk.content_base64 === "string" && chunk.content_base64.length <= 43692, "workspace_seed_chunk_invalid");
      const bytes = Buffer.from(chunk.content_base64, "base64");
      requireThat(bytes.toString("base64") === chunk.content_base64 && chunk.next_offset === offset + bytes.length, "workspace_seed_chunk_invalid");
      offset = inbox.put(file.path, offset, bytes).next_offset;
    } while (offset < file.size);
  }
  assertCurrent(); inbox.prepare(receiver.state_root, workspace); assertCurrent(); inbox.promote(); assertCurrent();
}
