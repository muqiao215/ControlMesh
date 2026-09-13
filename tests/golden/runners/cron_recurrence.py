"""Production-Python oracle for cron recurrence: cronsim grammar + zoneinfo DST resolution.

The TypeScript owner (`packages/controlmesh-runtime-core/src/cron-schedule.ts`) is diffed
against this matrix. `expected_ms` is the zone-resolved instant under the documented TS
policy (first-fold civil slots strictly after the reference; fold=1 skipped, gap shifted
forward). `py_announced_ms` is what `observer._schedule_job` logs (fold=0 attach) and
`py_fire_ms` is the instant it actually fires at, because the asyncio delay is a naive
wall-clock subtraction. The two differ exactly when the reference and the target sit on
different UTC offsets.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from cronsim import CronSim, CronSimError

SCHEMA_VERSION = "controlmesh.cron_recurrence_golden.v1"
# Production passes naive civil time to CronSim; an aware value would test a different path.
BASE_NAIVE = datetime(2026, 1, 1, 0, 0, 0)  # noqa: DTZ001

GRAMMAR_EXPRESSIONS = (
    "* * * * *", "0 9 * * *", "30 2 * * *", "0 0 1 1 *", "0 0 29 2 *", "0 0 31 * *",
    "0 0 L * *", "0 0 LW * *", "0 0 * * 5L", "0 0 * * 1L", "0 0 * * MON#3",
    "0 0 * * SUN", "0 0 * * 0", "0 0 * * 7", "0 0 * * SUN-FRI", "0 0 * * 1-5",
    "*/15 9-17 * * MON-FRI", "0 0 * JAN,DEC *", "0 0 * mar-apr *", "5-55/10 * * * *",
    "0 0 15 * *", "0 0 15 * SUN", "0 0 * * FRI", "0 0 L * MON", "0 0 1-31/10 * *",
    "0,15,30,45 0 * * *", "0 0 29 2 SUN", "0 0 30 2 *", "0 0 31 2 *", "0 0 -1 * *",
    "0 0 60 * *", "0 0 * 13 *", "0 0 * * 8", "0 0 * * MON#6", "*/0 * * * *",
    "* * * *", "0 9 * * * *", "@daily", "0 12 * * ?", "0 12 ? * *", "",
)

ERROR_CASES = ("0 0 30 2 *", "0 0 31 2 *", "0 0 31 4,6,9,11 *", "* * * *", "0 9 * * * *", "@daily")
NONE_CASES = ("0 0 * 2 MON#5", "0 0 30 2 *")

ZONES = ("UTC", "Asia/Shanghai", "America/New_York", "Europe/London", "Australia/Lord_Howe")

ORDINARY_CASES = (
    ("utc.quarter", "*/15 * * * *", "UTC", "2026-01-01T00:00:00Z"),
    ("utc.daily.ms_before", "0 9 * * *", "UTC", "2026-01-01T08:59:59.998Z"),
    ("utc.daily.ms_after", "0 9 * * *", "UTC", "2026-01-01T09:00:00.500Z"),
    ("utc.daily.at_slot", "0 9 * * *", "UTC", "2026-01-01T09:00:00.000Z"),
    ("utc.last_day", "0 0 L * *", "UTC", "2026-01-31T00:00:00Z"),
    ("utc.last_weekday", "0 0 LW * *", "UTC", "2026-01-01T00:00:00Z"),
    ("utc.leap_day", "0 0 29 2 *", "UTC", "2026-01-01T00:00:00Z"),
    ("utc.month_names", "0 0 * JAN,DEC *", "UTC", "2026-06-01T00:00:00Z"),
    ("utc.dow_sunday_name", "0 0 * * SUN", "UTC", "2026-01-01T00:00:00Z"),
    ("utc.dow_sunday_zero", "0 0 * * 0", "UTC", "2026-01-01T00:00:00Z"),
    ("utc.dow_sunday_seven", "0 0 * * 7", "UTC", "2026-01-01T00:00:00Z"),
    ("utc.dow_nth", "0 0 * * MON#3", "UTC", "2026-01-01T00:00:00Z"),
    ("utc.dow_last_friday", "0 0 * * 5L", "UTC", "2026-01-01T00:00:00Z"),
    ("utc.dom_or_dow", "0 0 15 * SUN", "UTC", "2026-01-01T00:00:00Z"),
    ("utc.dom_and_dow", "0 0 15 * *", "UTC", "2026-01-01T00:00:00Z"),
    ("utc.stepped_range", "0 0 1-31/10 * *", "UTC", "2026-01-01T00:00:00Z"),
    ("shanghai.morning", "30 9 * * *", "Asia/Shanghai", "2026-06-01T00:00:00Z"),
    ("shanghai.hourly", "0 * * * *", "Asia/Shanghai", "2026-06-01T13:20:00Z"),
    ("newyork.winter", "0 9 * * *", "America/New_York", "2026-01-15T13:00:00Z"),
    ("newyork.summer", "*/15 * * * *", "America/New_York", "2026-07-04T16:07:00Z"),
    ("london.weekdays", "0 7 * * MON-FRI", "Europe/London", "2026-02-02T09:00:00Z"),
    ("lordhowe.noon", "0 12 * * *", "Australia/Lord_Howe", "2026-06-01T02:00:00Z"),
    ("utc.five_minute", "5-55/10 * * * *", "UTC", "2026-01-01T00:00:00Z"),
)

TRANSITION_SCHEDULES = ("45 1 * * *", "0 * * * *", "30 2 * * *", "*/20 * * * *")
TRANSITION_OFFSETS_MIN = (-150, -45, -5, 20, 50, 110)


def _ms(text: str) -> int:
    parsed = datetime.fromisoformat(text)
    return int(parsed.timestamp() * 1000)


def _local(ref_ms: int, tz: ZoneInfo) -> datetime:
    base = datetime.fromtimestamp(ref_ms // 1000, tz)
    return base + timedelta(microseconds=(ref_ms % 1000) * 1000)


def _slots(schedule: str, ref_naive: datetime, count: int = 3) -> list[datetime]:
    iterator = CronSim(schedule, ref_naive)
    return [next(iterator) for _ in range(count)]


def _instants_for(slot: datetime, tz: ZoneInfo) -> tuple[list[int], bool]:
    """Real instants displaying `slot` (oldest first); empty window means a gap."""
    found: list[int] = []
    for fold in (0, 1):
        aware = slot.replace(tzinfo=tz, fold=fold)
        if aware == aware.astimezone(UTC).astimezone(tz):
            found.append(int(aware.timestamp() * 1000))
    instants = sorted(set(found))
    if instants:
        return instants, False
    gap_aware = slot.replace(tzinfo=tz, fold=0)
    return [int(gap_aware.timestamp() * 1000)], True


def _expected(schedule: str, ref_naive: datetime, tz: ZoneInfo, ref_ms: int):
    iterator = CronSim(schedule, ref_naive)
    for _ in range(2881):
        slot = next(iterator)
        instants, gap = _instants_for(slot, tz)
        # The no-replay policy binds each repeated civil slot to its first fold.
        # This intentionally differs from choosing a later fold after restart.
        for index, instant in enumerate(instants[:1]):
            if instant > ref_ms:
                return instant, slot, index, gap, len(instants) > 1
    return None, None, 0, False, False


def _transitions(tz: ZoneInfo, start: datetime, end: datetime) -> list[int]:
    found: list[int] = []
    step = timedelta(minutes=15)
    previous = start.astimezone(tz).utcoffset()
    cursor = start
    while cursor < end:
        cursor += step
        current = cursor.astimezone(tz).utcoffset()
        if current != previous:
            found.append(int(cursor.timestamp() * 1000))
            previous = current
    return found


def _case(case_id: str, schedule: str, tzname: str, ref_ms: int, slop_ms: float = 0.0) -> dict:
    tz = ZoneInfo(tzname)
    now_local = _local(ref_ms, tz)
    now_naive = now_local.replace(tzinfo=None)
    try:
        wall_slots = _slots(schedule, now_naive)
    except (CronSimError, StopIteration):
        return {"id": case_id, "schedule": schedule, "timezone": tzname, "ref_ms": ref_ms, "error": "no_slot"}
    announced = wall_slots[0].replace(tzinfo=tz)
    now2 = _local(ref_ms + slop_ms, tz) if slop_ms else now_local
    delay = (announced - now2).total_seconds()
    py_skipped = delay < 0
    if py_skipped:
        announced = wall_slots[1].replace(tzinfo=tz) if len(wall_slots) > 1 else announced
        delay = (announced - now2).total_seconds()
    expected_ms, expected_slot, fold, gap, ambiguous = _expected(schedule, now_naive, tz, ref_ms)
    py_fire = ref_ms + slop_ms + round(delay * 1000)
    kind = "gap" if gap else "ambiguous" if ambiguous else "ordinary"
    if ref_ms % 1000:
        kind = f"{kind}.millisecond"
    return {
        "id": case_id, "schedule": schedule, "timezone": tzname, "ref_ms": ref_ms, "slop_ms": slop_ms,
        "kind": kind,
        "wall_slots": [slot.isoformat() for slot in wall_slots],
        "py_announced_ms": int(announced.timestamp() * 1000),
        "py_fire_ms": py_fire,
        "py_skipped": py_skipped,
        "expected_ms": expected_ms,
        "expected_wall": expected_slot.isoformat() if expected_slot else None,
        "expected_fold": fold,
        "expected_gap": gap,
        "py_fire_delta_ms": None if expected_ms is None else expected_ms - py_fire,
    }


def _grammar() -> list[dict]:
    rows: list[dict] = []
    for expression in GRAMMAR_EXPRESSIONS:
        try:
            rows.append({"expression": expression, "ok": True,
                         "slots": [slot.isoformat() for slot in _slots(expression, BASE_NAIVE)]})
        except (CronSimError, StopIteration) as exc:
            rows.append({"expression": expression, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
    return rows


def _errors() -> list[dict]:
    rows: list[dict] = []
    for expression in ERROR_CASES:
        try:
            _slots(expression, BASE_NAIVE, count=1)
            rows.append({"expression": expression, "ok": True, "error": None})
        except (CronSimError, StopIteration) as exc:
            rows.append({"expression": expression, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
    for expression in NONE_CASES:
        try:
            _slots(expression, BASE_NAIVE, count=1)
            rows.append({"expression": expression, "none": False})
        except StopIteration:
            rows.append({"expression": expression, "none": True})
        except CronSimError as exc:
            rows.append({"expression": expression, "none": True, "error": f"{type(exc).__name__}: {exc}"})
    return rows


def generate_matrix() -> dict:
    cases: list[dict] = []
    for case_id, schedule, tzname, ref_text in ORDINARY_CASES:
        cases.append(_case(case_id, schedule, tzname, _ms(ref_text)))
    cases.append(_case("utc.daily.slop", "0 9 * * *", "UTC", _ms("2026-01-01T08:59:59.998Z"), 3.0))

    window_start = datetime(2026, 1, 1, tzinfo=UTC)
    window_end = datetime(2027, 1, 1, tzinfo=UTC)
    for tzname in ZONES:
        if tzname == "UTC":
            continue
        tz = ZoneInfo(tzname)
        for index, at_ms in enumerate(_transitions(tz, window_start, window_end)):
            for schedule in TRANSITION_SCHEDULES:
                for offset in TRANSITION_OFFSETS_MIN:
                    ref_ms = at_ms + offset * 60_000
                    cases.append(_case(
                        f"dst.{tzname.lower().replace('/', '_')}.{index}.{schedule.replace(' ', '_').replace('*', 'a').replace('/', 's')}.{offset}",
                        schedule, tzname, ref_ms))
    for tzname in ("Asia/Shanghai",):
        for offset in TRANSITION_OFFSETS_MIN[:2]:
            cases.extend(_case(f"dst.shanghai_stable.{schedule.replace(' ', '_')}.{offset}",
                               schedule, tzname, _ms("2026-06-01T00:00:00Z") + offset * 60_000)
                         for schedule in TRANSITION_SCHEDULES[:2])
    return {"schema_version": SCHEMA_VERSION, "cases": cases, "grammar": _grammar(), "errors": _errors()}
