export interface OneBotSender {
  user_id: number;
  nickname?: string;
  card?: string;
}

export interface OneBotSegment {
  type: string;
  data?: Record<string, string | number | undefined>;
}

export interface ControlMeshFileRef {
  path: string;
  name: string;
  is_image?: boolean;
}

export interface OneBotMessageEvent {
  post_type: "message";
  message_type: "private" | "group";
  user_id: number;
  group_id?: number;
  message_id: number;
  message?: OneBotSegment[];
  raw_message?: string;
  sender?: OneBotSender;
}

export interface NormalizedInboundMessage {
  scene: "private" | "group";
  userId: string;
  groupId?: string;
  messageId: string;
  text: string;
}

export interface OneBotSendTarget {
  scene: "private" | "group";
  userId?: string;
  groupId?: string;
}

export interface OneBotSendRequest extends OneBotSendTarget {
  text: string;
  imagePath?: string;
}

export interface OneBotFileUploadRequest extends OneBotSendTarget {
  filePath: string;
  name?: string;
}

function formatSegment(segment: OneBotSegment): string {
  const data = segment.data || {};
  const summary = String(
    data.name || data.title || data.file || data.url || data.id || data.qq || "",
  ).trim();
  switch (segment.type) {
    case "text":
      return String(data.text || "");
    case "image":
      return `[IMAGE] ${summary}`.trim();
    case "file":
      return `[FILE] ${summary}`.trim();
    case "record":
      return `[VOICE] ${summary}`.trim();
    case "video":
      return `[VIDEO] ${summary}`.trim();
    case "reply":
      return summary ? `[REPLY] ${summary}` : "";
    case "at":
      return "";
    default:
      return `[${segment.type.toUpperCase()}]`;
  }
}

export function normalizeMessageEvent(event: OneBotMessageEvent): NormalizedInboundMessage {
  const text =
    event.message
      ?.map(formatSegment)
      .filter(Boolean)
      .join("\n")
      .replace(/\n{3,}/g, "\n\n")
      .trim() ||
    event.raw_message?.trim() ||
    "";
  return {
    scene: event.message_type,
    userId: String(event.user_id),
    groupId: event.group_id ? String(event.group_id) : undefined,
    messageId: String(event.message_id),
    text,
  };
}

function buildMessagePayload(request: OneBotSendRequest): string | OneBotSegment[] {
  const segments: OneBotSegment[] = [];
  if (request.scene === "group" && request.userId) {
    segments.push({ type: "at", data: { qq: Number(request.userId) } });
  }
  if (request.text) {
    segments.push({
      type: "text",
      data: { text: segments.length ? ` ${request.text}` : request.text },
    });
  }
  if (request.imagePath) {
    segments.push({ type: "image", data: { file: request.imagePath } });
  }
  if (!segments.length) {
    return "";
  }
  if (segments.length === 1 && segments[0]?.type === "text") {
    return String(segments[0].data?.text || "");
  }
  return segments;
}

export function buildSendAction(request: OneBotSendRequest): {
  action: "send_private_msg" | "send_group_msg";
  params: Record<string, number | string | OneBotSegment[]>;
} {
  if (request.scene === "private") {
    if (!request.userId) {
      throw new Error("userId is required for private replies");
    }
    return {
      action: "send_private_msg",
      params: {
        user_id: Number(request.userId),
        message: buildMessagePayload(request),
      },
    };
  }
  if (!request.groupId) {
    throw new Error("groupId is required for group replies");
  }
  return {
    action: "send_group_msg",
    params: {
      group_id: Number(request.groupId),
      message: buildMessagePayload(request),
    },
  };
}

export function buildFileUploadAction(request: OneBotFileUploadRequest): {
  action: "upload_private_file" | "upload_group_file";
  params: Record<string, number | string>;
} {
  if (request.scene === "private") {
    if (!request.userId) {
      throw new Error("userId is required for private file uploads");
    }
    return {
      action: "upload_private_file",
      params: {
        user_id: Number(request.userId),
        file: request.filePath,
        name: request.name || "",
      },
    };
  }
  if (!request.groupId) {
    throw new Error("groupId is required for group file uploads");
  }
  return {
    action: "upload_group_file",
    params: {
      group_id: Number(request.groupId),
      file: request.filePath,
      name: request.name || "",
    },
  };
}

export function renderControlMeshResult(text: string, files: ControlMeshFileRef[]): string {
  const clean = text.trim();
  if (!files.length) {
    return clean;
  }
  const attachmentLines = files.map((file) => `[ATTACHMENT] ${file.name}: ${file.path}`);
  return [clean, ...attachmentLines].filter(Boolean).join("\n\n");
}
