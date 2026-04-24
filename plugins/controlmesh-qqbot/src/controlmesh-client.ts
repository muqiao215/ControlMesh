import WebSocket from "ws";
import nacl from "tweetnacl";
import util from "tweetnacl-util";

export interface ControlMeshResultFrame {
  type: "result";
  text: string;
  stream_fallback: boolean;
  files: Array<{ path: string; name: string; is_image?: boolean }>;
}

interface AuthOkFrame {
  type: "auth_ok";
  chat_id: number;
  channel_id?: number;
  e2e_pk: string;
}

type ControlMeshFrame =
  | { type: "text_delta"; data: string }
  | { type: "tool_activity"; data: string }
  | { type: "system_status"; data: string | null }
  | ControlMeshResultFrame
  | { type: "error"; code: string; message: string };

function encodePayload(sharedKey: Uint8Array, payload: object): string {
  const nonce = nacl.randomBytes(nacl.box.nonceLength);
  const message = util.decodeUTF8(JSON.stringify(payload));
  const cipher = nacl.box.after(message, nonce, sharedKey);
  const merged = new Uint8Array(nonce.length + cipher.length);
  merged.set(nonce);
  merged.set(cipher, nonce.length);
  return util.encodeBase64(merged);
}

function decodePayload(sharedKey: Uint8Array, encoded: string): ControlMeshFrame {
  const bytes = util.decodeBase64(encoded);
  const nonce = bytes.slice(0, nacl.box.nonceLength);
  const cipher = bytes.slice(nacl.box.nonceLength);
  const plain = nacl.box.open.after(cipher, nonce, sharedKey);
  if (!plain) {
    throw new Error("Failed to decrypt ControlMesh payload");
  }
  return JSON.parse(util.encodeUTF8(plain)) as ControlMeshFrame;
}

export interface SendTurnInput {
  wsUrl: string;
  token: string;
  chatId: number;
  channelId?: number;
  transport?: string;
  text: string;
}

export async function sendTurn(input: SendTurnInput): Promise<ControlMeshResultFrame> {
  return await new Promise<ControlMeshResultFrame>((resolve, reject) => {
    const keyPair = nacl.box.keyPair();
    const ws = new WebSocket(input.wsUrl);
    let sharedKey: Uint8Array | null = null;

    ws.on("open", () => {
      const authPayload: Record<string, unknown> = {
        type: "auth",
        token: input.token,
        e2e_pk: util.encodeBase64(keyPair.publicKey),
        chat_id: input.chatId,
      };
      if (input.channelId) {
        authPayload.channel_id = input.channelId;
      }
      if (input.transport) {
        authPayload.transport = input.transport;
      }
      ws.send(JSON.stringify(authPayload));
    });

    ws.on("message", (raw) => {
      try {
        const text = raw.toString();
        if (!sharedKey) {
          const authOk = JSON.parse(text) as AuthOkFrame;
          if (authOk.type !== "auth_ok") {
            throw new Error(`Unexpected auth response: ${text}`);
          }
          const remoteKey = util.decodeBase64(authOk.e2e_pk);
          sharedKey = nacl.box.before(remoteKey, keyPair.secretKey);
          ws.send(encodePayload(sharedKey, { type: "message", text: input.text }));
          return;
        }

        const frame = decodePayload(sharedKey, text);
        if (frame.type === "result") {
          ws.close();
          resolve(frame);
          return;
        }
        if (frame.type === "error") {
          ws.close();
          reject(new Error(`${frame.code}: ${frame.message}`));
        }
      } catch (error) {
        ws.close();
        reject(error instanceof Error ? error : new Error(String(error)));
      }
    });

    ws.on("error", (error) => {
      reject(error);
    });

    ws.on("close", () => {
      if (!sharedKey) {
        reject(new Error("ControlMesh closed before auth completed"));
      }
    });
  });
}
