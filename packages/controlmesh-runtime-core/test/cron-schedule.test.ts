import { expect, test } from "bun:test";
import matrix from "../../../tests/golden/fixtures/runtime/cron-recurrence.matrix.json";
import { nextCronOccurrence, nextCronOccurrences, parseCronExpression, resolveCronTimezone } from "../src/cron-schedule";

for (const row of matrix.cases) {
  test(`Python zoneinfo oracle: ${row.id}`, () => {
    const actual = nextCronOccurrence(row.schedule, { afterMs: row.ref_ms, timeZone: row.timezone });
    expect(actual?.scheduledAtMs ?? null).toBe(row.expected_ms);
    if (actual) {
      expect(actual.scheduledAtMs).toBeGreaterThan(row.ref_ms);
      expect(actual.wallTime).toBe(row.expected_wall);
      expect<number>(actual.fold).toBe(row.expected_fold);
      expect(actual.gapShifted).toBe(row.expected_gap);
    }
  });
}

for (const row of matrix.grammar) {
  test(`Python grammar: ${row.expression}`, () => {
    // This candidate explicitly supports five fields. Six-field support remains
    // a reviewed migration difference, not a claim of complete CronSim parity.
    if (!row.ok || row.expression.trim().split(/\s+/).length !== 5) {
      expect(() => parseCronExpression(row.expression)).toThrow();
      return;
    }
    const actual = nextCronOccurrences(row.expression, {
      afterMs: Date.parse("2026-01-01T00:00:00Z"), timeZone: "UTC", count: 3,
    });
    expect(actual.map(slot => slot.wallTime)).toEqual(row.slots ?? []);
  });
}

test("timezone precedence uses explicit inputs and skips invalid zones", () => {
  expect(resolveCronTimezone({ jobTimezone: "Asia/Shanghai", configuredTimezone: "UTC" })).toBe("Asia/Shanghai");
  expect(resolveCronTimezone({ jobTimezone: "invalid", configuredTimezone: "Europe/London" })).toBe("Europe/London");
  expect(resolveCronTimezone({ hostTimezone: "America/New_York" })).toBe("America/New_York");
  expect(resolveCronTimezone()).toBe("UTC");
});

test("fall-back does not run a fixed daily wall-clock slot twice", () => {
  const slots = nextCronOccurrences("30 1 * * *", {
    afterMs: Date.parse("2026-11-01T04:00:00Z"), timeZone: "America/New_York", count: 3,
  });
  expect(slots.map(slot => new Date(slot.scheduledAtMs).toISOString())).toEqual([
    "2026-11-01T05:30:00.000Z", "2026-11-02T06:30:00.000Z", "2026-11-03T06:30:00.000Z",
  ]);
});

test("restart within the second repeated hour does not re-admit the first daily slot", () => {
  const next = nextCronOccurrence("30 1 * * *", {
    afterMs: Date.parse("2026-11-01T06:05:00Z"), timeZone: "America/New_York",
  });
  expect(new Date(next!.scheduledAtMs).toISOString()).toBe("2026-11-02T06:30:00.000Z");
});

test("invalid counts and nonrepresentable reference dates fail explicitly", () => {
  for (const count of [0, -1, 1.5, 101, NaN, Infinity]) {
    expect(() => nextCronOccurrences("* * * * *", { afterMs: 0, timeZone: "UTC", count })).toThrow("invalid_occurrence_count");
  }
  for (const afterMs of [NaN, Infinity, -Infinity, 8.64e15 + 1]) {
    expect(() => nextCronOccurrence("* * * * *", { afterMs, timeZone: "UTC" })).toThrow("invalid_reference_instant");
  }
});
