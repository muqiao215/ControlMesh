import { requireThat, RuntimeConflict } from "./value";

/** Only a validated negative transport response may issue this; timeouts never qualify. */
export class DeliveryRetryAfter extends RuntimeConflict {
  constructor(readonly delay_ms: number) {
    super("delivery_rate_limited");
    requireThat(Number.isSafeInteger(delay_ms) && delay_ms > 0 && delay_ms <= 86400000, "delivery_retry_delay_invalid");
  }
}
