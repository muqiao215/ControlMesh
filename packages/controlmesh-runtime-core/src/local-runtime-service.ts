import { openLocalRuntime } from "./local-runtime-config";
import { LocalRuntimeControl } from "./local-runtime-control";
import { listenRuntimeControl } from "./runtime-control-socket";
import { requireThat } from "./value";

/** The service owns queue execution; a terminal/client owns only its connection and draft. */
export async function startLocalRuntimeService(config: string, socket: string) {
  let owned: ReturnType<typeof openLocalRuntime> | undefined, control: LocalRuntimeControl | undefined;
  let pump = () => {};
  // Acquire the listener before opening a profile that may auto-start a topology scheduler.
  const listener = await listenRuntimeControl(socket, { async handle(request) {
    requireThat(control, "local_service_starting"); const reply = await control.handle(request);
    if (reply.ok) pump(); return reply;
  } }, async () => { await owned?.stop(); });
  let timer: ReturnType<typeof setInterval> | undefined, closing: Promise<void> | undefined;
  let fail!: (error: unknown) => void;
  const failure = new Promise<never>((_resolve, reject) => { fail = reject; }); void failure.catch(() => {});
  const close = () => closing ??= (async () => {
    if (timer) clearInterval(timer);
    try { await listener.close(); } finally { await owned?.close(); }
  })();
  try {
    owned = openLocalRuntime(config);
    control = new LocalRuntimeControl(owned.runtime, owned.deliveries, owned.submissionIdentity, owned.inbound,
      owned.specmesh, owned.recovery, owned.history, owned.scheduler);
    let pumping: Promise<void> | undefined;
    pump = () => {
      if (closing || pumping) return;
      try {
        listener.assertCurrent();
        pumping = owned!.runtime.drain().then(() => closing ? undefined : owned!.deliveries?.drain()).then(() => {})
          .catch(error => { if (!closing) { fail(error); void close().catch(() => {}); } }).finally(() => { pumping = undefined; });
      } catch (error) { fail(error); void close().catch(() => {}); }
    };
    pump(); timer = setInterval(pump, 1000);
    return { socket: listener.path, failure, close };
  } catch (error) { await close(); throw error; }
}
