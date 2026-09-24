from datetime import date

import pytest

from src.validation.rules import dedupe_exact, validate_dataset, validate_record
from tests.conftest import rec

TODAY = date(2026, 9, 24)


def rules(record, severity="error"):
    return {q.rule for q in validate_record(record, today=TODAY) if q.severity == severity}


def test_valid_record_has_no_issues():
    assert validate_record(rec(), today=TODAY) == []


@pytest.mark.parametrize("main,rule", [
    ((1, 2, 3, 4, 5), "main_count"),
    ((1, 2, 3, 4, 5, 6, 7), "main_count"),
    ((0, 2, 3, 4, 5, 6), "main_range"),
    ((1, 2, 3, 4, 5, 56), "main_range"),
    ((1, 2, 3, 4, 5, 5), "main_unique"),
    ((1, 2, 3, 4, 5, 6.0), "main_integer"),
    ((1, 2, 3, 4, 5, True), "main_integer"),
])
def test_main_number_rules(main, rule):
    assert rule in rules(rec(main=main, special=40))


def test_unsorted_main_is_warning_only():
    r = rec(main=(38, 5, 10, 14, 23, 24))
    assert rules(r) == set()
    assert "main_sorted" in rules(r, "warning")


@pytest.mark.parametrize("special,rule", [(0, "special_range"), (56, "special_range"), (10, "special_not_in_main")])
def test_special_number_rules(special, rule):
    assert rule in rules(rec(special=special))


def test_missing_special_is_warning():
    assert "special_present" in rules(rec(special=None), "warning")


def test_future_date_rejected():
    assert "not_future_dated" in rules(rec(d=date(2026, 9, 26)))


def test_non_draw_weekday_is_warning():
    assert "draw_weekday" in rules(rec(d=date(2017, 8, 2)), "warning")  # Wednesday


@pytest.mark.parametrize("draw_id", ["1", "000001", "abcde", ""])
def test_draw_id_format(draw_id):
    assert "draw_id_format" in rules(rec(draw_id=draw_id))


def test_dataset_conflicting_duplicate_ids():
    issues = validate_dataset([rec(), rec(special=40)])
    assert any(q.rule == "draw_id_unique" and q.severity == "error" for q in issues)


def test_dataset_chronology_and_continuity():
    issues = validate_dataset([
        rec("00001", date(2017, 8, 1)),
        rec("00002", date(2017, 8, 1)),   # same date as previous -> error
        rec("00004", date(2017, 8, 8)),   # gap -> warning
    ])
    by_rule = {q.rule: q for q in issues}
    assert by_rule["chronological_order"].draw_id == "00002"
    assert by_rule["draw_id_continuity"].severity == "warning"


def test_dedupe_exact_keeps_conflicts():
    a, b, c = rec(), rec(), rec(special=40)
    assert dedupe_exact([a, b, c]) == [a, c]
