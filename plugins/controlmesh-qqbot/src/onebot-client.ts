import WebSocket from "ws";

import {
  buildFileUploadAction,
  buildSendAction,
  type OneBotFileUploadRequest,
  type OneBotMessageEvent,
  type OneBotSendRequest,
} from "./onebot";

interface OneBotActionResponse {
  status?: string;
  retcode?: number;
  echo?: string;
  action?: string;
  message?: string;
  wording?: string;
  data?: unknown;
}

interface PendingAction {
  resolve: (payload: OneBotActionResponse) => void;
  reject: (error: Error) => void;
  timer: ReturnType<typeof setTimeout>;
  action: string;
}

export class OneBotClient {
  private readonly ws: WebSocket;
  private readonly pending = new Map<string, PendingAction>();

  public constructor(
    url: string,
    token: string,
    onMessage: (event: OneBotMessageEvent) => Promise<void>,
  ) {
    this.ws = new WebSocket(url, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    });

    this.ws.on("message", (raw) => {
      const payload = JSON.parse(raw.toString()) as OneBotMessageEvent | OneBotActionResponse;
      if ("post_type" in payload && payload.post_type === "message") {
        void onMessage(payload);
        return;
      }
      if ("echo" in payload && payload.echo) {
        const waiter = this.pending.get(payload.echo);
        if (!waiter) {
          return;
        }
        this.pending.delete(payload.echo);
        clearTimeout(waiter.timer);
        if (payload.status === "ok" && payload.retcode === 0) {
          waiter.resolve(payload);
          return;
        }
        const reason = payload.wording || payload.message || "unknown error";
        waiter.reject(
          new Error(
            `OneBot action '${waiter.action}' failed: retcode=${payload.retcode ?? "unknown"} ${reason}`,
          ),
        );
      }
    });
  }

  public async waitUntilOpen(): Promise<void> {
    if (this.ws.readyState === WebSocket.OPEN) {
      return;
    }
    await new Promise<void>((resolve, reject) => {
      this.ws.once("open", () => resolve());
      this.ws.once("error", (error) => reject(error));
    });
  }

  public async sendMessage(request: OneBotSendRequest): Promise<void> {
    const { action, params } = buildSendAction(request);
    await this.callAction(action, params);
  }

  public async uploadFile(request: OneBotFileUploadRequest): Promise<void> {
    const { action, params } = buildFileUploadAction(request);
    await this.callAction(action, params);
  }

  private async callAction(
    action: string,
    params: Record<string, unknown>,
    timeoutMs = 15_000,
  ): Promise<OneBotActionResponse> {
    const echo = `${action}:${Date.now()}:${Math.random().toString(36).slice(2)}`;
    return await new Promise<OneBotActionResponse>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(echo);
        reject(new Error(`OneBot action '${action}' timed out after ${timeoutMs}ms`));
      }, timeoutMs);
      this.pending.set(echo, { resolve, reject, timer, action });
      this.ws.send(JSON.stringify({ action, params, echo }), (error) => {
        if (!error) {
          return;
        }
        clearTimeout(timer);
        this.pending.delete(echo);
        reject(error instanceof Error ? error : new Error(String(error)));
      });
    });
  }
}
