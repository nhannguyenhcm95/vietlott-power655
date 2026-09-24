"""The Tue/Thu/Sat 18:00 ICT draw schedule and its 21:00 ICT publication deadline."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from src.config import LOCAL_TZ

DRAW_TIME_LOCAL = time(18, 0)
PUBLICATION_DEADLINE_LOCAL = time(21, 0)
DRAW_WEEKDAYS = {1, 3, 5}  # Mon=0 .. Sun=6: Tue, Thu, Sat


def scheduled_draw_dates(start: date, end: date) -> list[date]:
    """Every Tue/Thu/Sat in [start, end]."""
    out: list[date] = []
    d = start
    while d <= end:
        if d.weekday() in DRAW_WEEKDAYS:
            out.append(d)
        d += timedelta(days=1)
    return out


def expected_latest_draw_date(as_of: datetime) -> date:
    """The latest Tue/Thu/Sat d such that d at 21:00 ICT <= as_of."""
    as_of_ict = as_of.astimezone(LOCAL_TZ)
    d = as_of_ict.date()
    for _ in range(14):
        if d.weekday() in DRAW_WEEKDAYS:
            deadline = datetime.combine(d, PUBLICATION_DEADLINE_LOCAL, tzinfo=LOCAL_TZ)
            if deadline <= as_of_ict:
                return d
        d -= timedelta(days=1)
    raise RuntimeError("no scheduled draw date found in the last 14 days")


def missed_scheduled_draws(last_draw_date: date, as_of: datetime) -> list[date]:
    """Scheduled dates strictly after `last_draw_date` whose publication deadline has passed."""
    latest_expected = expected_latest_draw_date(as_of)
    if latest_expected <= last_draw_date:
        return []
    return scheduled_draw_dates(last_draw_date + timedelta(days=1), latest_expected)
