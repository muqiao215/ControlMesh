/** A monotonic deadline only has meaning within the issuing Linux boot. */
export function containerLeaseCurrent(lease: unknown, boot: string, now: number): boolean {
  if (!lease || typeof lease !== "object" || Array.isArray(lease)) return false;
  const record = lease as Record<string, unknown>;
  return record.boot_id === boot && typeof record.expires_ms === "number" && Number.isFinite(record.expires_ms)
    && Number.isFinite(now) && record.expires_ms > now;
}
