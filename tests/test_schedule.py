from datetime import date, datetime

import pytest

from src.config import LOCAL_TZ
from src.validation.schedule import expected_latest_draw_date, missed_scheduled_draws, scheduled_draw_dates


def ict(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=LOCAL_TZ)


def test_scheduled_draw_dates_tue_thu_sat_only():
    dates = scheduled_draw_dates(date(2026, 9, 21), date(2026, 9, 27))  # Mon..Sun
    assert dates == [date(2026, 9, 22), date(2026, 9, 24), date(2026, 9, 26)]


@pytest.mark.parametrize("when,expected", [
    (ict(2026, 9, 22, 17, 59), date(2026, 9, 19)),   # Tue before deadline -> previous Sat
    (ict(2026, 9, 22, 21, 0), date(2026, 9, 22)),    # Tue at the deadline -> that Tue
    (ict(2026, 9, 23, 8, 30), date(2026, 9, 22)),    # Wed retry -> Tue
    (ict(2026, 9, 27, 8, 30), date(2026, 9, 26)),    # Sun -> previous Sat
])
def test_expected_latest_draw_date(when, expected):
    assert expected_latest_draw_date(when) == expected


def test_expected_latest_draw_date_sat_then_tue():
    sat = ict(2026, 9, 26, 22, 0)
    assert expected_latest_draw_date(sat) == date(2026, 9, 26)
    tue = ict(2026, 9, 29, 21, 0)
    assert expected_latest_draw_date(tue) == date(2026, 9, 29)


def test_missed_scheduled_draws_none_when_up_to_date():
    assert missed_scheduled_draws(date(2026, 9, 22), ict(2026, 9, 22, 21, 0)) == []


def test_missed_scheduled_draws_one_tet_style_gap():
    missed = missed_scheduled_draws(date(2026, 9, 22), ict(2026, 9, 26, 22, 0))
    assert missed == [date(2026, 9, 24), date(2026, 9, 26)]
