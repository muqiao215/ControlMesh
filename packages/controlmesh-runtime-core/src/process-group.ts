import { readFileSync } from "node:fs";
import { requireThat } from "./value";

export interface ProcessIdentity { pid: number; group: number; session: number; started: string }

export function processIdentity(pid: number): ProcessIdentity {
  requireThat(process.platform === "linux", "process_supervision_platform_unverified");
  requireThat(Number.isSafeInteger(pid) && pid >= 1, "unsafe_process_id");
  const stat = readFileSync(`/proc/${pid}/stat`, "utf8");
  const fields = stat.slice(stat.lastIndexOf(")") + 2).split(" ");
  return { pid, group: Number(fields[2]), session: Number(fields[3]), started: fields[19] };
}

/** Only a still-live group leader created as an anchor may authorize group signals. */
export function signalAnchoredGroup(anchor: ProcessIdentity, signal: "SIGTERM" | "SIGKILL"): void {
  requireThat(Number.isSafeInteger(anchor.pid) && anchor.pid > 1, "unsafe_process_id");
  requireThat(anchor.pid !== process.pid, "cannot_signal_controller_group");
  const current = processIdentity(anchor.pid);
  const self = processIdentity(process.pid);
  requireThat(current.started === anchor.started && current.group === anchor.pid && current.session === anchor.pid, "process_identity_changed");
  requireThat(current.group !== self.group && current.session !== self.session, "unsafe_process_group");
  process.kill(-anchor.pid, signal);
}

/** Used only inside the detached anchor when its controller disappears. */
export function stopOwnAnchor(): never {
  const self = processIdentity(process.pid);
  requireThat(self.pid > 1 && self.group === self.pid && self.session === self.pid, "not_a_detached_anchor");
  process.kill(-self.pid, "SIGKILL");
  throw new Error("anchor kill unexpectedly returned");
}
