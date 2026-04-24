import { access, mkdir, writeFile } from "node:fs/promises";
import { basename, join, resolve } from "node:path";

import type { QqBotConfig } from "./config";
import type { ControlMeshFileRef } from "./onebot";

export interface MaterializedOutboundFile {
  path: string;
  name: string;
  isImage: boolean;
}

async function exists(path: string): Promise<boolean> {
  try {
    await access(path);
    return true;
  } catch {
    return false;
  }
}

function sanitizeName(name: string): string {
  return name.replace(/[^A-Za-z0-9._-]+/g, "_") || "attachment.bin";
}

function isLikelyImage(file: ControlMeshFileRef): boolean {
  if (file.is_image) {
    return true;
  }
  return /\.(png|jpe?g|gif|webp|bmp|svg)$/i.test(file.name || file.path);
}

function filesBaseUrl(wsUrl: string): string {
  const url = new URL(wsUrl);
  url.protocol = url.protocol === "wss:" ? "https:" : "http:";
  url.pathname = "/files";
  url.search = "";
  url.hash = "";
  return url.toString();
}

export async function materializeOutboundFile(
  file: ControlMeshFileRef,
  config: QqBotConfig,
): Promise<MaterializedOutboundFile> {
  const directPath = resolve(file.path);
  if (await exists(directPath)) {
    return {
      path: directPath,
      name: file.name || basename(directPath),
      isImage: isLikelyImage(file),
    };
  }

  const response = await fetch(
    `${filesBaseUrl(config.controlmeshWsUrl)}?path=${encodeURIComponent(file.path)}`,
    {
      headers: {
        Authorization: `Bearer ${config.controlmeshToken}`,
      },
    },
  );
  if (!response.ok) {
    throw new Error(`ControlMesh file download failed: HTTP ${response.status}`);
  }

  await mkdir(config.outboundTempDir, { recursive: true });
  const targetName = sanitizeName(file.name || basename(file.path));
  const targetPath = join(config.outboundTempDir, `${Date.now()}-${targetName}`);
  await writeFile(targetPath, new Uint8Array(await response.arrayBuffer()));

  return {
    path: resolve(targetPath),
    name: file.name || targetName,
    isImage: isLikelyImage(file),
  };
}
