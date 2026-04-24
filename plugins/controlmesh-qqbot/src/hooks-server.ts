import type { OneBotClient } from "./onebot-client";
import type { OneBotSendTarget } from "./onebot";
import {
  AmbiguousTargetError,
  MissingTargetError,
  type TargetRegistry,
} from "./target-registry";

interface HookTarget {
  scene?: "private" | "group";
  userId?: string;
  groupId?: string;
  chatId?: number;
  threadId?: number;
}

interface NotifyPayload extends HookTarget {
  text: string;
}

interface TaskQuestionPayload extends HookTarget {
  taskId: string;
  question: string;
  promptPreview: string;
}

interface TaskResultPayload extends HookTarget {
  taskId: string;
  name: string;
  status: string;
  elapsedSeconds: number;
  provider: string;
  model: string;
  error?: string;
  resultText?: string;
}

function unauthorized(): Response {
  return new Response("unauthorized", { status: 401 });
}

function parseBearer(request: Request): string {
  const header = request.headers.get("authorization") || "";
  return header.replace(/^Bearer\s+/i, "").trim();
}

function resolveTarget(payload: HookTarget, targets: TargetRegistry): OneBotSendTarget | null {
  if (payload.scene === "group" && payload.groupId) {
    return { scene: "group", groupId: payload.groupId, userId: payload.userId };
  }
  if (payload.scene === "private" && payload.userId) {
    return { scene: "private", userId: payload.userId };
  }
  if (typeof payload.chatId === "number") {
    return targets.resolve(payload.chatId, payload.threadId);
  }
  return null;
}

export function startHookServer(
  client: OneBotClient,
  targets: TargetRegistry,
  options: { host: string; port: number; token: string },
): ReturnType<typeof Bun.serve> {
  const sendResolved = async (payload: HookTarget & { text: string }): Promise<void> => {
    const target = resolveTarget(payload, targets);
    if (!target) {
      throw new Error("No QQ target found for hook payload");
    }
    await client.sendMessage({
      ...target,
      text: payload.text,
    });
  };

  return Bun.serve({
    hostname: options.host,
    port: options.port,
    fetch: async (request) => {
      if (parseBearer(request) !== options.token) {
        return unauthorized();
      }

      const url = new URL(request.url);
      if (request.method !== "POST") {
        return new Response("method not allowed", { status: 405 });
      }

      if (url.pathname === "/notify") {
        const payload = (await request.json()) as NotifyPayload;
        try {
          await sendResolved(payload);
        } catch (error) {
          if (error instanceof AmbiguousTargetError) {
            return Response.json({ ok: false, error: error.message }, { status: 409 });
          }
          if (error instanceof MissingTargetError) {
            return Response.json({ ok: false, error: error.message }, { status: 404 });
          }
          throw error;
        }
        return Response.json({ ok: true });
      }

      if (url.pathname === "/notify-all") {
        const payload = (await request.json()) as { text: string };
        for (const target of targets.allTargets()) {
          await client.sendMessage({
            ...target,
            text: payload.text,
          });
        }
        return Response.json({ ok: true });
      }

      if (url.pathname === "/task-question") {
        const payload = (await request.json()) as TaskQuestionPayload;
        const text = `Task ${payload.taskId} has a question:\n${payload.question}\n\n${payload.promptPreview}`;
        try {
          await sendResolved({ ...payload, text });
        } catch (error) {
          if (error instanceof AmbiguousTargetError) {
            return Response.json({ ok: false, error: error.message }, { status: 409 });
          }
          if (error instanceof MissingTargetError) {
            return Response.json({ ok: false, error: error.message }, { status: 404 });
          }
          throw error;
        }
        return Response.json({ ok: true });
      }

      if (url.pathname === "/task-result") {
        const payload = (await request.json()) as TaskResultPayload;
        const details = `${payload.provider}/${payload.model} | ${Math.round(payload.elapsedSeconds)}s`;
        const header =
          payload.status === "done"
            ? `Task ${payload.name} completed (${details})`
            : payload.status === "failed"
              ? `Task ${payload.name} failed (${details})`
              : `Task ${payload.name} ${payload.status} (${details})`;
        const text = [header, payload.error, payload.resultText].filter(Boolean).join("\n\n");
        try {
          await sendResolved({ ...payload, text });
        } catch (error) {
          if (error instanceof AmbiguousTargetError) {
            return Response.json({ ok: false, error: error.message }, { status: 409 });
          }
          if (error instanceof MissingTargetError) {
            return Response.json({ ok: false, error: error.message }, { status: 404 });
          }
          throw error;
        }
        return Response.json({ ok: true });
      }

      return new Response("not found", { status: 404 });
    },
  });
}
