import { openDeviceRuntime, type DeviceRuntime } from "./device-runtime-config";
import { listenRuntimeControl } from "./runtime-control-socket";
import { requireThat, RuntimeConflict } from "./value";

/** Reconnectable local management for a coordinator/worker; its existing owner schedules work. */
export async function startDeviceRuntimeService(config: string, socket: string, daemon = false) {
  let owned: DeviceRuntime | undefined, closing: Promise<void> | undefined;
  const listener = await listenRuntimeControl(socket, { async handle(request) {
    requireThat(owned, "device_service_starting"); return owned.control.handle(request);
  } }, async () => { await owned?.stop(); });
  let timer: ReturnType<typeof setInterval> | undefined, checking = false;
  let fail!: (error: unknown) => void;
  const failure = new Promise<never>((_resolve, reject) => { fail = reject; }); void failure.catch(() => {});
  const close = () => closing ??= (async () => {
    if (timer) clearInterval(timer);
    try { await listener.close(); } finally { await owned?.close(); }
  })();
  try {
    owned = openDeviceRuntime(config);
    if (daemon) owned.startDaemon();
    const check = async () => {
      if (closing || checking) return;
      checking = true;
      try {
        listener.assertCurrent();
        const status = await owned!.control.handle({ id: "device-service-health", op: "status" });
        if (!status.ok) throw new RuntimeConflict(typeof status.error === "string" ? status.error : "device_service_unavailable");
      } catch (error) { if (!closing) { fail(error); void close().catch(() => {}); } }
      finally { checking = false; }
    };
    timer = setInterval(() => { void check(); }, 1000);
    return { socket: listener.path, failure, close };
  } catch (error) { await close(); throw error; }
}
