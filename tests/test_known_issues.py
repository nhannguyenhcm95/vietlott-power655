import json
from datetime import date, datetime, timezone, timedelta

import pytest

from src.config import LOCAL_TZ
from src.validation.findings import Finding
from src.validation.known_issues import (
    KnownIssuesError,
    NEVER_ACCEPTABLE,
    RULES,
    apply_known_issue,
    issue_state,
    load_known_issues,
    match_known_issue,
)

AS_OF = datetime(2026, 9, 24, 12, 0, tzinfo=LOCAL_TZ)


def base_entry(**over):
    e = {
        "id": "KI-001", "source": "github_mirror", "draw_id": "00944",
        "rules": ["chronological_order"], "pins": {},
        "reason": "r", "evidence": "e",
        "approved_by": "project-lead (human)", "approved_on": "2026-09-24",
        "approval_ref": "TASKBOARD Decisions 2026-09-24", "review_by": "2027-03-31",
    }
    e.update(over)
    return e


def write_ki(tmp_path, *entries):
    path = tmp_path / "known_issues.json"
    path.write_text(json.dumps({"schema_version": "1.0", "issues": list(entries)}), encoding="utf-8")
    return path


# ------------------------------------------------------------- absent / malformed
def test_absent_file_returns_empty_list(tmp_path):
    assert load_known_issues(tmp_path / "nope.json") == []


def test_malformed_json_raises(tmp_path):
    path = tmp_path / "known_issues.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(KnownIssuesError):
        load_known_issues(path)


def test_missing_schema_version_raises(tmp_path):
    path = tmp_path / "known_issues.json"
    path.write_text(json.dumps({"issues": []}), encoding="utf-8")
    with pytest.raises(KnownIssuesError):
        load_known_issues(path)


# ------------------------------------------------------------- allowlist violations
@pytest.mark.parametrize("bad", [
    {"source": "*"},
    {"source": "not_a_source"},
    {"draw_id": "1"},
    {"draw_id": "abcde"},
    {"rules": ["not_a_real_rule"]},
    {"unknown_key": "x"},
])
def test_ki_allowlist_violations_fail(tmp_path, bad):
    e = base_entry(**{k: v for k, v in bad.items() if k != "unknown_key"})
    if "unknown_key" in bad:
        e["unknown_key"] = "x"
    path = write_ki(tmp_path, e)
    with pytest.raises(KnownIssuesError):
        load_known_issues(path)


def test_ki_duplicate_id_fails(tmp_path):
    path = write_ki(tmp_path, base_entry(), base_entry())
    with pytest.raises(KnownIssuesError):
        load_known_issues(path)


def test_ki_malformed_fail_absent_info(tmp_path):
    """A malformed file raises (-> known_issues_file FAIL); an absent file returns [] (-> INFO)."""
    absent = tmp_path / "absent.json"
    assert load_known_issues(absent) == []
    malformed = write_ki(tmp_path, base_entry(source="*"))
    with pytest.raises(KnownIssuesError):
        load_known_issues(malformed)


@pytest.mark.parametrize("rule", sorted(NEVER_ACCEPTABLE - {"known_issues_file"}))
def test_ki_cannot_accept_integrity_rule(tmp_path, rule):
    spec = RULES[rule]
    e = base_entry(rules=[rule])
    if spec.date_range_only:
        e = base_entry(rules=[rule])
        del e["draw_id"]
        e["draw_date_from"], e["draw_date_to"] = "2026-01-01", "2026-01-31"
    if spec.needs_pin:
        e["pins"] = {rule: {"x": "1"}}
    path = write_ki(tmp_path, e)
    with pytest.raises(KnownIssuesError):
        load_known_issues(path)


# ------------------------------------------------------------- date ranges
def test_ki_range_over_60_days_fail(tmp_path):
    e = base_entry(rules=["freshness"], source="vietlott_official", draw_date_from="2026-01-01", draw_date_to="2026-04-01")
    del e["draw_id"]
    path = write_ki(tmp_path, e)
    with pytest.raises(KnownIssuesError):
        load_known_issues(path)


def test_ki_range_beyond_review_by_fail(tmp_path):
    e = base_entry(rules=["freshness"], source="vietlott_official", draw_date_from="2026-01-01",
                    draw_date_to="2026-02-01", review_by="2026-01-15")
    del e["draw_id"]
    path = write_ki(tmp_path, e)
    with pytest.raises(KnownIssuesError):
        load_known_issues(path)


def test_ki_range_does_not_cover_later_missed_dates(tmp_path):
    e = base_entry(rules=["freshness"], source="vietlott_official", draw_date_from="2026-01-01", draw_date_to="2026-01-31")
    del e["draw_id"]
    path = write_ki(tmp_path, e)
    (ki,) = load_known_issues(path)
    in_range = Finding("vietlott_official", None, "2026-01-15", "freshness", "WARN", "d")
    out_of_range = Finding("vietlott_official", None, "2026-02-15", "freshness", "WARN", "d")
    assert match_known_issue(in_range, [ki], AS_OF) is ki
    assert match_known_issue(out_of_range, [ki], AS_OF) is None


def test_ki_elapsed_range_is_info(tmp_path):
    e = base_entry(rules=["freshness"], source="vietlott_official", draw_date_from="2026-01-01", draw_date_to="2026-01-31")
    del e["draw_id"]
    path = write_ki(tmp_path, e)
    (ki,) = load_known_issues(path)
    assert issue_state(ki, datetime(2026, 10, 5, tzinfo=LOCAL_TZ)) == "active"  # still active; "elapsed" affects report-level annotation only


# ------------------------------------------------------------- state
def test_ki_proposed_when_approval_fields_empty(tmp_path):
    e = base_entry(approved_by="", approved_on="", approval_ref="")
    path = write_ki(tmp_path, e)
    (ki,) = load_known_issues(path)
    assert issue_state(ki, AS_OF) == "proposed"


def test_ki_future_approved_on_is_proposed(tmp_path):
    e = base_entry(approved_on="2099-01-01")
    path = write_ki(tmp_path, e)
    (ki,) = load_known_issues(path)
    assert issue_state(ki, AS_OF) == "proposed"


def test_ki_expired_stops_accepting(tmp_path):
    e = base_entry(review_by="2020-01-01")
    path = write_ki(tmp_path, e)
    (ki,) = load_known_issues(path)
    assert issue_state(ki, AS_OF) == "expired"
    f = Finding("github_mirror", "00944", None, "chronological_order", "WARN", "d")
    apply_known_issue(f, [ki], AS_OF)
    assert f.accepted is False
    assert f.known_issue_id == "KI-001" and f.known_issue_state == "expired"


def test_ki_active_accepts():
    from src.validation.known_issues import KnownIssue
    ki = KnownIssue("KI-001", "github_mirror", ("chronological_order",), "00944", None, None, {},
                     "r", "e", "a", "2026-09-24", "ref", "2027-01-01")
    f = Finding("github_mirror", "00944", None, "chronological_order", "WARN", "d")
    apply_known_issue(f, [ki], AS_OF)
    assert f.accepted is True


# ------------------------------------------------------------- pins
def test_ki_mismatch_pinned_accepted(tmp_path):
    e = base_entry(rules=["reconcile.field_mismatch"], pins={"reconcile.field_mismatch": {"special_number": "10"}})
    path = write_ki(tmp_path, e)
    (ki,) = load_known_issues(path)
    f = Finding("github_mirror", "00944", None, "reconcile.field_mismatch", "FAIL", "d", observed={"special_number": "10"})
    apply_known_issue(f, [ki], AS_OF)
    assert f.accepted is True


def test_ki_mismatch_pin_mismatch_not_accepted(tmp_path):
    e = base_entry(rules=["reconcile.field_mismatch"], pins={"reconcile.field_mismatch": {"special_number": "10"}})
    path = write_ki(tmp_path, e)
    (ki,) = load_known_issues(path)
    f = Finding("github_mirror", "00944", None, "reconcile.field_mismatch", "FAIL", "d", observed={"special_number": "11"})
    apply_known_issue(f, [ki], AS_OF)
    assert f.accepted is False
    assert "pin_mismatch" in f.detail


def test_ki_pin_integer_not_accepted(tmp_path):
    e = base_entry(rules=["reconcile.field_mismatch"], pins={"reconcile.field_mismatch": {"special_number": "10"}})
    path = write_ki(tmp_path, e)
    (ki,) = load_known_issues(path)
    f = Finding("github_mirror", "00944", None, "reconcile.field_mismatch", "FAIL", "d", observed={"special_number": 10})
    apply_known_issue(f, [ki], AS_OF)
    assert f.accepted is False


def test_ki_pins_required_for_pin_rule(tmp_path):
    e = base_entry(rules=["reconcile.field_mismatch"], pins={})
    path = write_ki(tmp_path, e)
    with pytest.raises(KnownIssuesError):
        load_known_issues(path)


# ------------------------------------------------------------- matched / unused (via apply_known_issue bookkeeping)
def test_ki_matched_per_rule(tmp_path):
    e = base_entry(rules=["chronological_order", "reconcile.only_left"])
    path = write_ki(tmp_path, e)
    (ki,) = load_known_issues(path)
    matched: dict = {}
    for f in [
        Finding("github_mirror", "00944", None, "chronological_order", "WARN", "d"),
        Finding("github_mirror", "00944", None, "reconcile.only_left", "WARN", "d"),
    ]:
        apply_known_issue(f, [ki], AS_OF)
        matched.setdefault(f.known_issue_id, {}).setdefault(f.rule, 0)
        matched[f.known_issue_id][f.rule] += 1
    assert matched == {"KI-001": {"chronological_order": 1, "reconcile.only_left": 1}}
