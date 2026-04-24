export interface SessionScope {
  scene: "private" | "group";
  userId: string;
  groupId?: string;
}

export interface ControlMeshSessionTarget {
  chatId: number;
  channelId?: number;
}

function toPositiveInt(raw: string): number {
  const digits = raw.replace(/\D+/g, "");
  if (!digits) {
    throw new Error(`Cannot derive positive integer from identifier: ${raw}`);
  }
  const value = Number(digits.slice(-9));
  return value > 0 ? value : 1;
}

export function buildSessionTarget(scope: SessionScope): ControlMeshSessionTarget {
  if (scope.scene === "private") {
    return { chatId: toPositiveInt(scope.userId) };
  }
  if (!scope.groupId) {
    throw new Error("groupId is required for group session scopes");
  }
  return {
    chatId: toPositiveInt(scope.groupId),
    channelId: toPositiveInt(scope.userId),
  };
}

export function formatScope(scope: SessionScope): string {
  if (scope.scene === "private") {
    return `private:${scope.userId}`;
  }
  return `group:${scope.groupId}:${scope.userId}`;
}
