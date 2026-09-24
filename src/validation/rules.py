"""Data-quality rules for Power 6/55 draws (PROJECT_STEPS.md section 6).

Severity "error" rejects the record from the curated layer; "warning" is logged only.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime

from src.api.models import DrawRecord
from src.config import LOCAL_TZ

MAIN_COUNT = 6
NUMBER_MIN, NUMBER_MAX = 1, 55
DRAW_WEEKDAYS = {1, 3, 5}  # Tue, Thu, Sat
DRAW_ID_RE = re.compile(r"^\d{5}$")


@dataclass(frozen=True)
class QualityIssue:
    rule: str
    severity: str  # "error" | "warning"
    draw_id: str | None
    detail: str


def _is_int(x: object) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def today_local() -> date:
    return datetime.now(LOCAL_TZ).date()


def validate_record(r: DrawRecord, today: date | None = None) -> list[QualityIssue]:
    today = today or today_local()
    issues: list[QualityIssue] = []

    def add(rule: str, detail: str, severity: str = "error") -> None:
        issues.append(QualityIssue(rule, severity, r.draw_id, detail))

    if not DRAW_ID_RE.match(r.draw_id or ""):
        add("draw_id_format", f"draw_id {r.draw_id!r} is not 5 digits")
    if not isinstance(r.draw_date, date):
        add("draw_date_parseable", f"draw_date {r.draw_date!r} is not a date")
    elif r.draw_date > today:
        add("not_future_dated", f"draw_date {r.draw_date} is after today {today}")
    elif r.draw_date.weekday() not in DRAW_WEEKDAYS:
        add("draw_weekday", f"draw_date {r.draw_date} is a {r.draw_date:%A}, not Tue/Thu/Sat", "warning")

    nums = list(r.main_numbers)
    if len(nums) != MAIN_COUNT:
        add("main_count", f"expected {MAIN_COUNT} main numbers, got {len(nums)}")
    if not all(_is_int(n) for n in nums):
        add("main_integer", f"non-integer main numbers {nums!r}")
    else:
        out = [n for n in nums if not NUMBER_MIN <= n <= NUMBER_MAX]
        if out:
            add("main_range", f"main numbers out of {NUMBER_MIN}..{NUMBER_MAX}: {out}")
        if len(set(nums)) != len(nums):
            add("main_unique", f"duplicate main numbers {nums}")
        elif nums != sorted(nums):
            add("main_sorted", f"main numbers not ascending {nums} (will be canonicalized)", "warning")

    s = r.special_number
    if s is None:
        add("special_present", "special number missing", "warning")
    elif not _is_int(s) or not NUMBER_MIN <= s <= NUMBER_MAX:
        add("special_range", f"special number {s!r} not an integer in {NUMBER_MIN}..{NUMBER_MAX}")
    elif s in nums:
        add("special_not_in_main", f"special number {s} also appears in main numbers")
    return issues


def _content(r: DrawRecord) -> tuple:
    return (r.draw_date, tuple(sorted(r.main_numbers)), r.special_number)


def validate_dataset(records: list[DrawRecord]) -> list[QualityIssue]:
    """Cross-record rules. Expects records already de-duplicated by content."""
    issues: list[QualityIssue] = []
    by_id: dict[str, list[DrawRecord]] = defaultdict(list)
    for r in records:
        by_id[r.draw_id].append(r)
    for draw_id, group in by_id.items():
        if len({_content(r) for r in group}) > 1:
            issues.append(QualityIssue("draw_id_unique", "error", draw_id, f"{len(group)} conflicting rows for one draw_id"))

    ordered = sorted({r.draw_id: r for r in records}.values(), key=lambda r: r.draw_no)

    seen_content: dict[tuple, str] = {}
    for r in ordered:
        key = (tuple(sorted(r.main_numbers)), r.special_number)
        earlier = seen_content.get(key)
        if earlier is not None:
            issues.append(QualityIssue("duplicate_content", "warning", r.draw_id,
                                       f"draw {r.draw_id} shares main numbers and special with earlier draw {earlier}"))
        else:
            seen_content[key] = r.draw_id

    for prev, cur in zip(ordered, ordered[1:]):
        if cur.draw_date <= prev.draw_date:
            issues.append(QualityIssue("chronological_order", "error", cur.draw_id,
                                       f"draw {cur.draw_id} dated {cur.draw_date} not after draw {prev.draw_id} dated {prev.draw_date}"))
        if cur.draw_no != prev.draw_no + 1:
            issues.append(QualityIssue("draw_id_continuity", "warning", cur.draw_id,
                                       f"gap: draw {prev.draw_id} is followed by {cur.draw_id}"))
    return issues


def dedupe_exact(records: list[DrawRecord]) -> list[DrawRecord]:
    """Drop rows that repeat an already-seen (draw_id, content); keeps the first occurrence."""
    seen: set[tuple] = set()
    out = []
    for r in records:
        key = (r.draw_id, *_content(r))
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out
