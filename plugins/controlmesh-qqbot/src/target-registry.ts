import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";

import type { OneBotSendTarget } from "./onebot";

interface RegistryEntry extends OneBotSendTarget {
  chatId: number;
  threadId?: number;
  updatedAt: string;
}

interface RegistryFile {
  entries: RegistryEntry[];
}

function storageKey(chatId: number, threadId?: number): string {
  return threadId ? `${chatId}:${threadId}` : `${chatId}`;
}

export class MissingTargetError extends Error {
  public constructor(chatId: number, threadId?: number) {
    super(
      threadId
        ? `No QQ target mapping found for chatId=${chatId} threadId=${threadId}`
        : `No QQ target mapping found for chatId=${chatId}`,
    );
    this.name = "MissingTargetError";
  }
}

export class AmbiguousTargetError extends Error {
  public constructor(chatId: number) {
    super(`Ambiguous QQ group target for chatId=${chatId}; explicit threadId/userId is required`);
    this.name = "AmbiguousTargetError";
  }
}

export class TargetRegistry {
  private readonly path: string;
  private readonly entries = new Map<string, RegistryEntry>();

  private constructor(path: string) {
    this.path = resolve(path);
  }

  public static async create(path: string): Promise<TargetRegistry> {
    const registry = new TargetRegistry(path);
    await registry.load();
    return registry;
  }

  public remember(target: OneBotSendTarget & { chatId: number; threadId?: number }): void {
    this.entries.set(storageKey(target.chatId, target.threadId), {
      ...target,
      updatedAt: new Date().toISOString(),
    });
    void this.persist();
  }

  public resolve(chatId: number, threadId?: number): OneBotSendTarget {
    const exact = this.entries.get(storageKey(chatId, threadId));
    if (exact) {
      return this.toTarget(exact);
    }
    if (threadId) {
      return {
        scene: "group",
        groupId: String(chatId),
        userId: String(threadId),
      };
    }

    const matches = [...this.entries.values()]
      .filter((entry) => entry.chatId === chatId)
      .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
    if (matches.length === 1) {
      return this.toTarget(matches[0]);
    }
    if (matches.length > 1) {
      throw new AmbiguousTargetError(chatId);
    }
    throw new MissingTargetError(chatId);
  }

  public allTargets(): OneBotSendTarget[] {
    const deduped = new Map<string, OneBotSendTarget>();
    for (const entry of this.entries.values()) {
      const target = this.toTarget(entry);
      const key =
        target.scene === "private"
          ? `private:${target.userId}`
          : `group:${target.groupId}:${target.userId || ""}`;
      deduped.set(key, target);
    }
    return [...deduped.values()];
  }

  private toTarget(entry: RegistryEntry): OneBotSendTarget {
    return {
      scene: entry.scene,
      userId: entry.userId,
      groupId: entry.groupId,
    };
  }

  private async load(): Promise<void> {
    try {
      const raw = await readFile(this.path, "utf8");
      const parsed = JSON.parse(raw) as RegistryFile;
      for (const entry of parsed.entries || []) {
        this.entries.set(storageKey(entry.chatId, entry.threadId), entry);
      }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
        throw error;
      }
    }
  }

  private async persist(): Promise<void> {
    await mkdir(dirname(this.path), { recursive: true });
    await writeFile(
      this.path,
      `${JSON.stringify({ entries: [...this.entries.values()] }, null, 2)}\n`,
      "utf8",
    );
  }
}
