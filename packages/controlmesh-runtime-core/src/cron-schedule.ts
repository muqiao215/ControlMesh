/** Wall-clock cron recurrence for scheduled work: deterministic, pure, no timers, I/O or state.
 * CronSim 2.7 grammar/calendar adaptation; see ../THIRD_PARTY_NOTICES.md (BSD-3-Clause).
 *
 * Grammar is the five-field CronSim dialect used by Python `controlmesh/cron/observer.py`
 * (minute hour day-of-month month day-of-week) including ranges, steps, month/day names and
 * the special day forms `L`, `LW`, `<dow>L`, `<dow>#<n>`. Six-field expressions, `@` macros
 * and `?` are rejected explicitly. CronSim accepts six fields; that remains an explicit
 * migration difference to resolve before accepting every existing registry.
 *
 * Occurrence identity is the zone-resolved epoch instant (`scheduledAtMs`). It never depends
 * on a coordinator incarnation, a lease or a monotonic clock: replanning from the same
 * reference yields the same occurrence.
 */

const MINUTE_MS = 60_000;
const HOUR_MS = 3_600_000;
const DAY_MS = 86_400_000;
/** Bound on the wall-clock slot search (~54 years of day steps), mirroring cronsim's 50-year give-up. */
const MAX_DAY_STEPS = 20_000;
const MAX_YEAR_SPAN = 50;
const MAX_OCCURRENCES = 100;

export type CronField = "minute" | "hour" | "day-of-month" | "month" | "day-of-week";

const FIELD_RANGES: Record<CronField, readonly [number, number]> = {
  minute: [0, 59],
  hour: [0, 23],
  "day-of-month": [1, 31],
  month: [1, 12],
  "day-of-week": [0, 7],
};
const MONTH_NAMES = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
const DAY_NAMES = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
const DAYS_IN_MONTH = [-1, 31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

export class CronScheduleError extends Error {
  readonly field?: CronField;
  constructor(readonly code: string, field?: CronField) {
    super(field === undefined ? code : `${code}:${field}`);
    this.name = "CronScheduleError";
    this.field = field;
  }
}

type FieldItem =
  | { kind: "value"; value: number }
  | { kind: "lastDay" }
  | { kind: "lastWeekday" }
  | { kind: "nthDow"; dow: number; nth: number }
  | { kind: "lastDow"; dow: number };

interface FieldSet {
  values: Set<number>;
  items: FieldItem[];
}

export interface CronExpression {
  readonly expression: string;
  readonly minutes: ReadonlySet<number>;
  readonly hours: ReadonlySet<number>;
  readonly months: ReadonlySet<number>;
  readonly days: ReadonlySet<number>;
  readonly lastDay: boolean;
  readonly lastWeekday: boolean;
  readonly weekdays: ReadonlySet<number>;
  readonly nthWeekdays: readonly { dow: number; nth: number }[];
  readonly lastWeekdays: readonly number[];
  /** Debian cron rule: when either day field starts with `*` the two day fields are ANDed, else ORed. */
  readonly dayAnd: boolean;
  readonly minuteList: readonly number[];
  readonly hourList: readonly number[];
}

function bad(field: CronField): CronScheduleError {
  return new CronScheduleError(`bad_${field.replace(/-/g, "_")}`, field);
}

function fieldInt(field: CronField, text: string): number {
  if (field === "month" && MONTH_NAMES.includes(text)) return MONTH_NAMES.indexOf(text) + 1;
  if (field === "day-of-week" && DAY_NAMES.includes(text)) return DAY_NAMES.indexOf(text);
  if (text === "" || !/^[0-9]+$/.test(text)) throw bad(field);
  const value = Number(text);
  const [min, max] = FIELD_RANGES[field];
  if (value < min || value > max) throw bad(field);
  return value;
}

function itemKey(item: FieldItem): string {
  return item.kind === "value" ? `v${item.value}`
    : item.kind === "nthDow" ? `n${item.dow}.${item.nth}`
      : item.kind === "lastDow" ? `l${item.dow}` : item.kind;
}

function setOf(items: readonly FieldItem[]): FieldSet {
  const values = new Set<number>();
  for (const item of items) if (item.kind === "value") values.add(item.value);
  return { values, items: [...items] };
}

/** Parse one comma-free term, mirroring cronsim's `Field.parse` precedence. */
function parseTerm(field: CronField, term: string): FieldItem[] {
  if (term === "*") {
    const [min, max] = FIELD_RANGES[field];
    const values: number[] = [];
    for (let value = min; value <= max; value += 1) values.push(value);
    return values.map(value => ({ kind: "value" as const, value }));
  }

  if (field === "day-of-week" && term.includes("L")) {
    const head = term.slice(0, -1);
    if (term[term.length - 1] !== "L" || head === "" || !/^[0-9]+$/.test(head)) throw bad(field);
    return [{ kind: "lastDow", dow: fieldInt(field, head) }];
  }

  if (field === "day-of-week" && term.includes("#")) {
    const [head, nthText, ...rest] = term.split("#");
    if (rest.length > 0) throw bad(field);
    const nth = /^[0-9]+$/.test(nthText) ? Number(nthText) : Number.NaN;
    if (!Number.isInteger(nth) || nth < 1 || nth > 5) throw bad(field);
    return [{ kind: "nthDow", dow: fieldInt(field, head), nth }];
  }

  if (term.includes("/")) {
    const [head, stepText, ...rest] = term.split("/");
    if (rest.length > 0) throw bad(field);
    const step = /^[0-9]+$/.test(stepText) ? Number(stepText) : Number.NaN;
    if (!Number.isInteger(step) || step === 0) throw bad(field);
    const items = parseTerm(field, head);
    // cronsim leaves the special day forms untouched when a step is applied to them.
    if (items.some(item => item.kind !== "value")) return items;
    if (items.length > 1) return items.filter((_, index) => index % step === 0);
    if (!items[0] || items[0].kind !== "value") throw bad(field);
    const [min, max] = FIELD_RANGES[field];
    const start = items[0].value;
    const values: number[] = [];
    for (let value = start; value <= max; value += step) values.push(value);
    if (values.length === 0) throw bad(field);
    return values.filter(value => value >= min).map(value => ({ kind: "value" as const, value }));
  }

  if (term.includes("-")) {
    const [startText, endText, ...rest] = term.split("-");
    if (rest.length > 0) throw bad(field);
    const start = fieldInt(field, startText);
    const end = fieldInt(field, endText);
    if (end < start) throw bad(field);
    const values: number[] = [];
    for (let value = start; value <= end; value += 1) values.push(value);
    return values.map(value => ({ kind: "value" as const, value }));
  }

  if (field === "day-of-month" && term === "LW") return [{ kind: "lastWeekday" }];
  if (field === "day-of-month" && term === "L") return [{ kind: "lastDay" }];
  return [{ kind: "value", value: fieldInt(field, term) }];
}

function parseField(field: CronField, text: string): FieldSet {
  const collected = new Map<string, FieldItem>();
  for (const term of text.split(",")) {
    if (term === "") throw bad(field);
    for (const item of parseTerm(field, term)) collected.set(itemKey(item), item);
  }
  return setOf([...collected.values()]);
}

export function parseCronExpression(expression: string): CronExpression {
  const parts = expression.trim().toUpperCase().split(/\s+/);
  if (parts.length !== 5) throw new CronScheduleError("wrong_number_of_fields");
  const [minuteText, hourText, dayText, monthText, dowText] = parts;
  const minutes = parseField("minute", minuteText);
  const hours = parseField("hour", hourText);
  const days = parseField("day-of-month", dayText);
  const months = parseField("month", monthText);
  const weekdays = parseField("day-of-week", dowText);

  if (days.values.size > 0) {
    const smallest = Math.min(...days.values);
    if (smallest > 29) {
      const widest = Math.max(...[...months.values].map(month => DAYS_IN_MONTH[month]));
      if (smallest > widest) throw bad("day-of-month");
    }
  }

  const nthWeekdays: { dow: number; nth: number }[] = [];
  const lastWeekdays: number[] = [];
  for (const item of weekdays.items) {
    if (item.kind === "nthDow") nthWeekdays.push({ dow: item.dow, nth: item.nth });
    if (item.kind === "lastDow") lastWeekdays.push(item.dow);
  }
  return {
    expression,
    minutes: minutes.values,
    hours: hours.values,
    months: months.values,
    days: days.values,
    lastDay: days.items.some(item => item.kind === "lastDay"),
    lastWeekday: days.items.some(item => item.kind === "lastWeekday"),
    weekdays: weekdays.values,
    nthWeekdays,
    lastWeekdays,
    dayAnd: dayText.startsWith("*") || dowText.startsWith("*"),
    minuteList: [...minutes.values].sort((a, b) => a - b),
    hourList: [...hours.values].sort((a, b) => a - b),
  };
}

// -- civil (wall-clock) calendar helpers. Wall times are encoded as UTC-ms so the
// arithmetic never observes the runtime's own zone or DST. --

function civilMs(year: number, month: number, day: number, hour = 0, minute = 0): number {
  return Date.UTC(year, month - 1, day, hour, minute, 0);
}
function startOfDay(ms: number): number {
  return ms - (ms % DAY_MS);
}
function lastDayOfMonth(year: number, month: number): number {
  return new Date(Date.UTC(year, month, 0)).getUTCDate();
}
/** Last weekday (Mon-Fri) of a month, matching cronsim's `last_weekday`. */
function lastWeekdayOfMonth(year: number, month: number): number {
  const last = lastDayOfMonth(year, month);
  const firstDowMon0 = (new Date(civilMs(year, month, 1)).getUTCDay() + 6) % 7;
  const lastDowMon0 = (firstDowMon0 + last - 1) % 7;
  if (lastDowMon0 === 6) return last - 2;
  if (lastDowMon0 === 5) return last - 1;
  return last;
}
function nextMonthStart(ms: number, months: ReadonlySet<number>): number | null {
  const date = new Date(ms);
  let year = date.getUTCFullYear();
  let month = date.getUTCMonth() + 1;
  for (let step = 0; step < 12 * (MAX_YEAR_SPAN + 1); step += 1) {
    const candidate = civilMs(year, month, 1);
    if (months.has(month) && candidate >= startOfDay(ms)) return candidate;
    month += 1;
    if (month > 12) {
      month = 1;
      year += 1;
    }
  }
  return null;
}
function firstAtLeast(sorted: readonly number[], value: number): number | null {
  for (const candidate of sorted) if (candidate >= value) return candidate;
  return null;
}

function matchDom(expression: CronExpression, year: number, month: number, day: number): boolean {
  if (expression.days.has(day)) return true;
  if (expression.lastWeekday && day >= 26 && day === lastWeekdayOfMonth(year, month)) return true;
  if (expression.lastDay && day >= 28 && day === lastDayOfMonth(year, month)) return true;
  return false;
}

function matchDow(expression: CronExpression, year: number, month: number, day: number): boolean {
  const pythonDow = ((new Date(civilMs(year, month, day)).getUTCDay() + 6) % 7) + 1;
  const aliases = pythonDow === 7 ? [7, 0] : [pythonDow];
  const named = (dow: number): boolean => aliases.includes(dow);
  for (const dow of expression.weekdays) if (named(dow)) return true;
  if (expression.lastWeekdays.length > 0 || expression.nthWeekdays.length > 0) {
    const last = lastDayOfMonth(year, month);
    if (expression.lastWeekdays.some(named) && day + 7 > last) return true;
    const index = Math.floor((day + 6) / 7);
    if (expression.nthWeekdays.some(entry => named(entry.dow) && entry.nth === index)) return true;
  }
  return false;
}

function matchDay(expression: CronExpression, year: number, month: number, day: number): boolean {
  const dom = matchDom(expression, year, month, day);
  const dow = matchDow(expression, year, month, day);
  return expression.dayAnd ? dom && dow : dom || dow;
}

/** Smallest wall slot (whole minute, second 0) matching the expression at or after `fromMs`. */
function nextWallSlot(expression: CronExpression, fromMs: number): number | null {
  let ms = fromMs - (fromMs % MINUTE_MS);
  if (ms < fromMs) ms += MINUTE_MS;
  const limitYear = new Date(fromMs).getUTCFullYear() + MAX_YEAR_SPAN;
  for (let step = 0; step < MAX_DAY_STEPS; step += 1) {
    const date = new Date(ms);
    const year = date.getUTCFullYear();
    const month = date.getUTCMonth() + 1;
    const day = date.getUTCDate();
    if (year > limitYear) return null;
    if (!expression.months.has(month)) {
      const jumped = nextMonthStart(ms, expression.months);
      if (jumped === null) return null;
      ms = jumped;
      continue;
    }
    if (!matchDay(expression, year, month, day)) {
      ms = startOfDay(ms) + DAY_MS;
      continue;
    }
    const hour = date.getUTCHours();
    if (!expression.hours.has(hour)) {
      const nextHour = firstAtLeast(expression.hourList, hour + 1);
      if (nextHour === null) {
        ms = startOfDay(ms) + DAY_MS;
        continue;
      }
      ms = startOfDay(ms) + nextHour * HOUR_MS + expression.minuteList[0] * MINUTE_MS;
      continue;
    }
    const minute = date.getUTCMinutes();
    if (!expression.minutes.has(minute)) {
      const nextMinute = firstAtLeast(expression.minuteList, minute);
      if (nextMinute !== null) {
        ms = startOfDay(ms) + hour * HOUR_MS + nextMinute * MINUTE_MS;
        continue;
      }
      const nextHour = firstAtLeast(expression.hourList, hour + 1);
      if (nextHour === null) {
        ms = startOfDay(ms) + DAY_MS;
        continue;
      }
      ms = startOfDay(ms) + nextHour * HOUR_MS + expression.minuteList[0] * MINUTE_MS;
      continue;
    }
    return ms;
  }
  return null;
}

// -- timezone plumbing (Intl/ICU is the zone database; no bundled tables) --

const formatters = new Map<string, Intl.DateTimeFormat>();
function formatter(timeZone: string): Intl.DateTimeFormat {
  const cached = formatters.get(timeZone);
  if (cached) return cached;
  let created: Intl.DateTimeFormat;
  try {
    created = new Intl.DateTimeFormat("en-US", {
      timeZone, hourCycle: "h23",
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
  } catch {
    throw new CronScheduleError("unknown_timezone");
  }
  formatters.set(timeZone, created);
  return created;
}

/** Civil wall time (UTC-ms encoding) observed in `timeZone` at the given instant. */
function wallAt(timeZone: string, utcMs: number): number {
  const parts = formatter(timeZone).formatToParts(new Date(utcMs));
  const read = (type: string): number => Number(parts.find(part => part.type === type)?.value ?? "0");
  return civilMs(read("year"), read("month"), read("day"), read("hour"), read("minute")) + read("second") * 1000;
}

/** UTC offset (ms) observed in `timeZone` at the given instant. */
function offsetAt(timeZone: string, utcMs: number): number {
  return wallAt(timeZone, utcMs) - utcMs;
}

function isValidTimeZone(timeZone: string): boolean {
  if (timeZone.trim() === "") return false;
  try {
    formatter(timeZone);
    return true;
  } catch {
    return false;
  }
}

/** Resolve a wall time to the real instants that display it, oldest first.
 *
 * An empty `instants` list is not returned: for a spring-forward gap the single result is the
 * forward-shifted instant, which equals Python's `fold=0` attach of a non-existent time.
 */
interface WallResolution { instants: number[]; gap: boolean }
function resolveWall(timeZone: string, wallMs: number): WallResolution {
  const guessOffset = offsetAt(timeZone, wallMs);
  const guessInstant = wallMs - guessOffset;
  const candidates = new Set<number>([
    offsetAt(timeZone, guessInstant - DAY_MS),
    guessOffset,
    offsetAt(timeZone, guessInstant + DAY_MS),
  ]);
  const instants = [...candidates]
    .map(offset => wallMs - offset)
    .filter(instant => wallAt(timeZone, instant) === wallMs)
    .sort((a, b) => a - b);
  if (instants.length > 0) return { instants, gap: false };
  return { instants: [wallMs - Math.min(...candidates)], gap: true };
}

export interface CronOccurrence {
  /** Zone-resolved epoch instant: the occurrence identity. Strictly after the reference. */
  readonly scheduledAtMs: number;
  /** Local wall time as UTC-ms encoding (for logging and equality checks). */
  readonly wallTimeMs: number;
  /** PEP 495 fold: 0 = first (pre-transition) pass, 1 = second pass of a repeated wall time. */
  readonly fold: 0 | 1;
  /** True when the wall time does not exist and was shifted forward out of the gap. */
  readonly gapShifted: boolean;
  /** Local wall time, `YYYY-MM-DDTHH:MM:SS`, offset-free. */
  readonly wallTime: string;
}

export interface CronScheduleRequest {
  /** Reference instant (epoch ms). The occurrence is always strictly after it. */
  readonly afterMs: number;
  readonly timeZone: string;
}

function wallText(wallMs: number): string {
  return new Date(wallMs).toISOString().slice(0, 19);
}

/** Next occurrence strictly after `afterMs`, or null when the expression has none in 50 years. */
export function nextCronOccurrence(
  expression: string | CronExpression,
  request: CronScheduleRequest,
): CronOccurrence | null {
  const parsed = typeof expression === "string" ? parseCronExpression(expression) : expression;
  const { timeZone, afterMs } = request;
  if (!Number.isFinite(afterMs) || Math.abs(afterMs) > 8.64e15) throw new CronScheduleError("invalid_reference_instant");
  const referenceWall = wallAt(timeZone, afterMs);
  // cronsim truncates the reference to whole seconds and requires the slot to be strictly later.
  let candidateWall = Math.floor(referenceWall / 1000) * 1000 + 1000;
  // Up to two days of minute slots covers historical date-line repeats as well
  // as ordinary one-hour folds, without an unbounded retry scan.
  for (let attempt = 0; attempt < 2881; attempt += 1) {
    const slot = nextWallSlot(parsed, candidateWall);
    if (slot === null) return null;
    const { instants, gap } = resolveWall(timeZone, slot);
    // Always bind a repeated civil slot to fold 0. Selecting fold 1 merely
    // because it is still in the future replays fixed jobs after a restart.
    for (let index = 0; index < Math.min(1, instants.length); index += 1) {
      const instant = instants[index];
      if (instant > afterMs) {
        return {
          scheduledAtMs: instant,
          wallTimeMs: slot,
          fold: index === 0 ? 0 : 1,
          gapShifted: gap,
          wallTime: wallText(slot),
        };
      }
    }
    candidateWall = slot + 1000;
  }
  return null;
}

/** Bounded sequence of successive occurrences, each strictly after the previous one. */
export function nextCronOccurrences(
  expression: string | CronExpression,
  request: CronScheduleRequest & { count: number },
): CronOccurrence[] {
  const count = request.count;
  if (!Number.isSafeInteger(count) || count < 1 || count > MAX_OCCURRENCES) {
    throw new CronScheduleError("invalid_occurrence_count");
  }
  const parsed = typeof expression === "string" ? parseCronExpression(expression) : expression;
  const result: CronOccurrence[] = [];
  let afterMs = request.afterMs;
  for (let index = 0; index < count; index += 1) {
    const occurrence = nextCronOccurrence(parsed, { afterMs, timeZone: request.timeZone });
    if (occurrence === null) return result;
    result.push(occurrence);
    afterMs = occurrence.scheduledAtMs;
  }
  return result;
}

export interface CronDueSlot {
  readonly occurrence: CronOccurrence;
  /** Nonnegative duration from the sampled reference. The timer owner must use a monotonic clock. */
  readonly waitMs: number;
}

/** Deterministic due-slot plan: wall-clock recurrence separated from monotonic waiting. */
export function planCronDueSlot(
  expression: string | CronExpression,
  request: CronScheduleRequest,
): CronDueSlot | null {
  const occurrence = nextCronOccurrence(expression, request);
  if (occurrence === null) return null;
  return { occurrence, waitMs: Math.max(0, occurrence.scheduledAtMs - request.afterMs) };
}

/** Stable occurrence identity: replaying the same slot after a restart yields the same value. */
export function cronOccurrenceId(jobId: string, scheduledAtMs: number): string {
  if (jobId.trim() === "" || !Number.isSafeInteger(scheduledAtMs)) {
    throw new CronScheduleError("invalid_occurrence_identity");
  }
  return `cron_occ:${jobId}:${scheduledAtMs}`;
}

export interface CronTimezoneInput {
  readonly jobTimezone?: string | null;
  readonly configuredTimezone?: string | null;
  readonly hostTimezone?: string | null;
}

/** Job timezone -> configured user timezone -> supplied host timezone -> UTC. */
export function resolveCronTimezone(input: CronTimezoneInput = {}): string {
  const chain = [input.jobTimezone, input.configuredTimezone, input.hostTimezone];
  for (const candidate of chain) {
    if (typeof candidate === "string" && isValidTimeZone(candidate)) return candidate;
  }
  return "UTC";
}
