import { readFileSync } from "node:fs";
import { requireThat } from "./value";

/** Linux uptime includes suspend, unlike CLOCK_MONOTONIC/performance.now(). No wall-clock agreement is required. */
export function elapsedMs(): number {
  requireThat(process.platform === "linux", "elapsed_clock_platform_unverified");
  const value = Number(readFileSync("/proc/uptime", "utf8").split(" ", 1)[0]) * 1000;
  requireThat(Number.isFinite(value) && value >= 0, "elapsed_clock_unavailable");
  return value;
}
