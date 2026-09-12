import { createHash } from "node:crypto";
import { closeSync, constants, fstatSync, openSync, readSync } from "node:fs";
import { join } from "node:path";
import type { DeviceJob } from "./device-coordinator";
import { artifactChunkBytes, type ArtifactChunk } from "./device-artifacts";
import { snapshotReads } from "./providers/native-manifest";
import { decodeTaskCompletion, verifyDeviceCompletion, type DeviceCompletion } from "./task-completion";
import { digest, object, requireThat } from "./value";

/** Sends retained, completion-bound bytes only; never executes or resumes a provider. */
export async function uploadDeviceArtifacts(job: DeviceJob, workspace: string, effectId: string, proof: unknown,
  current: () => void, send: (chunk: ArtifactChunk, requestId: string) => Promise<unknown>): Promise<void> {
  current();
  const contract = decodeTaskCompletion(job.execution?.completion_requirements);
  requireThat(job.artifact_transfer === true && contract, "device_artifact_contract_required");
  verifyDeviceCompletion(contract, proof);
  const paths = contract.files.map(file => join(workspace, file.path)), snapshots = snapshotReads(workspace, paths);
  let requests = 0;
  for (const [index, file] of contract.files.entries()) {
    current(); const path = paths[index]!, source = snapshots.find(item => item.path === path)!;
    requireThat(source && source.sha256 === (proof as DeviceCompletion).sha256[index], "device_artifact_source_changed");
    const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
    let content: Buffer;
    try {
      const stat = fstatSync(fd, { bigint: true });
      requireThat(stat.isFile() && String(stat.dev) === source.device && String(stat.ino) === source.inode
        && String(stat.size) === source.size, "device_artifact_source_changed");
      content = Buffer.alloc(Number(source.size)); let offset = 0;
      while (offset < content.length) {
        const count = readSync(fd, content, offset, content.length - offset, offset);
        requireThat(count > 0, "device_artifact_source_changed"); offset += count;
      }
      requireThat(createHash("sha256").update(content).digest("hex") === source.sha256, "device_artifact_source_changed");
    } finally { closeSync(fd); }
    for (let offset = 0; offset === 0 || offset < content.length; offset += artifactChunkBytes) {
      // Keep sequential transfers below the private port's global per-device admission rate.
      if (requests++ > 0) await new Promise(resolve => setTimeout(resolve, 25));
      current();
      const end = Math.min(content.length, offset + artifactChunkBytes), chunk = { path: file.path,
        sha256: source.sha256, size: content.length, offset, content_base64: content.subarray(offset, end).toString("base64") };
      const receipt = await send(chunk, `artifact-${digest([effectId, file.path, offset])}`);
      current();
      requireThat(object(receipt) && receipt.path === file.path && receipt.sha256 === source.sha256
        && receipt.size === content.length && receipt.next_offset === end, "device_artifact_receipt_unproven");
    }
  }
  current(); requireThat(digest(snapshotReads(workspace, paths)) === digest(snapshots), "device_artifact_source_changed");
}
