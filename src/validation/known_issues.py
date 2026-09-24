"""Known-issue registry (`configs/known_issues.json`): accept findings visibly, never suppress.

See docs/design/M2-data-quality-and-refresh.md sections 1.4 and 1.5.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from src.api.registry import SOURCES as DATA_SOURCES
from src.config import LOCAL_TZ

ISSUE_SOURCES = frozenset(DATA_SOURCES)  # vietlott_official, github_mirror
ID_RE = re.compile(r"^KI-\d{3}$")
DRAW_ID_RE = re.compile(r"^\d{5}$")
MAX_RANGE_DAYS = 60

REQUIRED_KEYS = {
    "id", "source", "rules", "pins", "reason", "evidence",
    "approved_by", "approved_on", "approval_ref", "review_by",
}
OPTIONAL_KEYS = {"draw_id", "draw_date_from", "draw_date_to"}
ALLOWED_KEYS = REQUIRED_KEYS | OPTIONAL_KEYS


class KnownIssuesError(ValueError):
    """The known_issues.json file is missing, unparsable, or violates the allowlist."""


@dataclass(frozen=True)
class RuleSpec:
    check_id: str
    acceptable_sources: frozenset[str] = frozenset()
    needs_pin: bool = False
    date_range_only: bool = False  # only `freshness` accepts a draw_date range instead of draw_id


RULES: dict[str, RuleSpec] = {
    "known_issues_file": RuleSpec("known_issues.file"),
    "known_issue_proposed": RuleSpec("known_issues.file"),
    "known_issue_expired": RuleSpec("known_issues.file"),
    "known_issue_unused": RuleSpec("known_issues.file"),
    "known_issue_rule_unused": RuleSpec("known_issues.file"),
    "known_issues_absent": RuleSpec("known_issues.file"),
    "input_missing": RuleSpec("input_missing"),
    "curated_schema": RuleSpec("curated.schema"),
    "curated_matches_staging": RuleSpec("curated.lineage"),
    "manifest_consistency": RuleSpec("curated.lineage"),
    "frozen_prefix": RuleSpec("curated.lineage"),
    "raw_lineage": RuleSpec("curated.lineage"),
    "null_required": RuleSpec("curated.missing"),
    "special_present": RuleSpec("curated.missing", ISSUE_SOURCES),
    "draw_id_unique": RuleSpec("curated.duplicates", frozenset({"github_mirror"})),
    "draw_date_unique": RuleSpec("curated.duplicates", frozenset({"github_mirror"})),
    "position_unique": RuleSpec("curated.duplicates"),
    "duplicate_content": RuleSpec("curated.duplicates", ISSUE_SOURCES),
    "draw_id_format": RuleSpec("curated.ranges", frozenset({"github_mirror"})),
    "draw_date_parseable": RuleSpec("curated.ranges", frozenset({"github_mirror"})),
    "not_future_dated": RuleSpec("curated.ranges", frozenset({"github_mirror"})),
    "main_count": RuleSpec("curated.ranges", frozenset({"github_mirror"})),
    "main_integer": RuleSpec("curated.ranges", frozenset({"github_mirror"})),
    "main_range": RuleSpec("curated.ranges", frozenset({"github_mirror"})),
    "main_unique": RuleSpec("curated.ranges", frozenset({"github_mirror"})),
    "special_range": RuleSpec("curated.ranges", frozenset({"github_mirror"})),
    "special_not_in_main": RuleSpec("curated.ranges", frozenset({"github_mirror"})),
    "chronological_order": RuleSpec("curated.ranges", frozenset({"github_mirror"})),
    "draw_weekday": RuleSpec("curated.ranges", ISSUE_SOURCES),
    "main_sorted": RuleSpec("curated.ranges", ISSUE_SOURCES),
    "draw_id_continuity": RuleSpec("curated.ranges", ISSUE_SOURCES),
    "retrieved_after_draw": RuleSpec("curated.ranges"),
    "first_draw": RuleSpec("coverage.gaps"),
    "draw_cadence": RuleSpec("coverage.gaps"),
    "freshness": RuleSpec("coverage.freshness", frozenset({"vietlott_official"}), date_range_only=True),
    "freshness_pending": RuleSpec("coverage.freshness"),
    "staging_schema": RuleSpec("staging.schema"),
    "run_failed": RuleSpec("ingestion.runs"),
    "run_partial": RuleSpec("ingestion.runs"),
    "incremental_empty_fetch": RuleSpec("ingestion.runs"),
    "mirror_shrink": RuleSpec("ingestion.runs"),
    "log_integrity": RuleSpec("ingestion.runs"),
    "stored_row_conflict": RuleSpec("quality_log.open", frozenset({"github_mirror"})),
    "reconcile.field_mismatch": RuleSpec("reconcile.sources", frozenset({"github_mirror"}), needs_pin=True),
    "reconcile.only_left": RuleSpec("reconcile.sources", frozenset({"github_mirror"})),
    "reconcile.only_right": RuleSpec("reconcile.sources", frozenset({"vietlott_official"})),
    "reconcile.mirror_lag": RuleSpec("reconcile.sources"),
    "reconcile.not_run": RuleSpec("reconcile.sources"),
    "raw_checksum": RuleSpec("raw.checksums"),
    "raw_manifest_missing": RuleSpec("raw.checksums"),
    "refresh_history": RuleSpec("refresh.history"),
}

NEVER_ACCEPTABLE = frozenset(rule for rule, spec in RULES.items() if not spec.acceptable_sources)


@dataclass(frozen=True)
class KnownIssue:
    id: str
    source: str
    rules: tuple[str, ...]
    draw_id: str | None
    draw_date_from: date | None
    draw_date_to: date | None
    pins: dict
    reason: str
    evidence: str
    approved_by: str
    approved_on: str
    approval_ref: str
    review_by: str


def _fail(msg: str) -> None:
    raise KnownIssuesError(msg)


def _all_leaves_are_strings(obj) -> bool:
    if isinstance(obj, dict):
        return bool(obj) and all(_all_leaves_are_strings(v) for v in obj.values())
    return isinstance(obj, str)


def _parse_entry(raw: dict, seen_ids: set[str]) -> KnownIssue:
    if not isinstance(raw, dict):
        _fail("each issue must be a JSON object")
    extra = set(raw) - ALLOWED_KEYS
    if extra:
        _fail(f"unknown key(s) {sorted(extra)}")
    missing = REQUIRED_KEYS - set(raw)
    if missing:
        _fail(f"missing key(s) {sorted(missing)}")

    id_ = raw["id"]
    if not isinstance(id_, str) or not ID_RE.match(id_):
        _fail(f"id {id_!r} must match ^KI-\\d{{3}}$")
    if id_ in seen_ids:
        _fail(f"duplicate id {id_!r}")
    seen_ids.add(id_)

    source = raw["source"]
    if source not in ISSUE_SOURCES:
        _fail(f"source {source!r} must be one of {sorted(ISSUE_SOURCES)}")

    rules = raw["rules"]
    if not isinstance(rules, list) or not rules or not all(isinstance(r, str) for r in rules):
        _fail(f"{id_}: rules must be a non-empty list of strings")
    rules = tuple(rules)
    for rule in rules:
        spec = RULES.get(rule)
        if spec is None:
            _fail(f"{id_}: unknown rule {rule!r}")
        if source not in spec.acceptable_sources:
            _fail(f"{id_}: rule {rule!r} can never be accepted for source {source!r}")

    has_draw_id = "draw_id" in raw
    has_range = "draw_date_from" in raw or "draw_date_to" in raw
    if has_draw_id == has_range:
        _fail(f"{id_}: exactly one of draw_id or draw_date_from+draw_date_to is required")

    draw_id = draw_date_from = draw_date_to = None
    if has_draw_id:
        draw_id = raw["draw_id"]
        if not isinstance(draw_id, str) or not DRAW_ID_RE.match(draw_id):
            _fail(f"{id_}: draw_id {draw_id!r} must match ^\\d{{5}}$")
    else:
        if "draw_date_from" not in raw or "draw_date_to" not in raw:
            _fail(f"{id_}: a date range needs both draw_date_from and draw_date_to")
        if list(rules) != ["freshness"]:
            _fail(f"{id_}: a date range is allowed only when rules == ['freshness']")
        try:
            draw_date_from = date.fromisoformat(raw["draw_date_from"])
            draw_date_to = date.fromisoformat(raw["draw_date_to"])
        except (TypeError, ValueError):
            _fail(f"{id_}: draw_date_from/draw_date_to must be ISO dates")
        if draw_date_to < draw_date_from:
            _fail(f"{id_}: draw_date_to must not precede draw_date_from")
        if (draw_date_to - draw_date_from).days > MAX_RANGE_DAYS:
            _fail(f"{id_}: date range exceeds {MAX_RANGE_DAYS} days")
        try:
            review_by = date.fromisoformat(raw["review_by"])
        except (TypeError, ValueError):
            _fail(f"{id_}: review_by must be an ISO date")
        if draw_date_to > review_by:
            _fail(f"{id_}: draw_date_to must not be after review_by")

    pins = raw["pins"]
    if not isinstance(pins, dict):
        _fail(f"{id_}: pins must be an object")
    for rule in rules:
        if RULES[rule].needs_pin:
            pin = pins.get(rule)
            if not isinstance(pin, dict) or not pin or not _all_leaves_are_strings(pin):
                _fail(f"{id_}: rule {rule!r} needs pins[{rule!r}] as a non-empty object with only string values")

    for key in ("reason", "evidence", "review_by"):
        if not isinstance(raw[key], str) or not raw[key]:
            _fail(f"{id_}: {key} must be a non-empty string")
    if not isinstance(raw["review_by"], str):
        _fail(f"{id_}: review_by must be an ISO date string")
    try:
        date.fromisoformat(raw["review_by"])
    except ValueError:
        _fail(f"{id_}: review_by must be an ISO date")

    for key in ("approved_by", "approved_on", "approval_ref"):
        if not isinstance(raw[key], str):
            _fail(f"{id_}: {key} must be a string")
    if raw["approved_on"]:
        try:
            date.fromisoformat(raw["approved_on"])
        except ValueError:
            _fail(f"{id_}: approved_on must be an ISO date")

    return KnownIssue(
        id=id_, source=source, rules=rules, draw_id=draw_id,
        draw_date_from=draw_date_from, draw_date_to=draw_date_to,
        pins=pins, reason=raw["reason"], evidence=raw["evidence"],
        approved_by=raw["approved_by"], approved_on=raw["approved_on"],
        approval_ref=raw["approval_ref"], review_by=raw["review_by"],
    )


def load_known_issues(path: Path) -> list[KnownIssue]:
    """Parse `configs/known_issues.json`. Returns [] if absent, raises on a malformed file."""
    path = Path(path)
    if not path.exists():
        return []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise KnownIssuesError(f"invalid JSON: {exc}") from exc
    if not isinstance(doc, dict) or doc.get("schema_version") != "1.0":
        raise KnownIssuesError("expected an object with schema_version '1.0'")
    issues = doc.get("issues")
    if not isinstance(issues, list):
        raise KnownIssuesError("'issues' must be a list")
    seen_ids: set[str] = set()
    return [_parse_entry(raw, seen_ids) for raw in issues]


def issue_state(ki: KnownIssue, as_of: datetime) -> str:
    """"active" | "proposed" | "expired", per section 1.5-2."""
    as_of_date = as_of.astimezone(LOCAL_TZ).date()
    if not ki.approved_by or not ki.approved_on or not ki.approval_ref:
        return "proposed"
    if date.fromisoformat(ki.approved_on) > as_of_date:
        return "proposed"
    if date.fromisoformat(ki.review_by) < as_of_date:
        return "expired"
    return "active"


def _finding_source(finding) -> str:
    return finding.source


def match_known_issue(finding, issues: list[KnownIssue], as_of: datetime) -> KnownIssue | None:
    """Return the (any-state) known issue whose scope covers `finding`, if any."""
    for ki in issues:
        if ki.source != finding.source or finding.rule not in ki.rules:
            continue
        if ki.draw_id is not None:
            if finding.draw_id != ki.draw_id:
                continue
        else:
            if not finding.draw_date:
                continue
            d = finding.draw_date if isinstance(finding.draw_date, date) else date.fromisoformat(finding.draw_date)
            if not (ki.draw_date_from <= d <= ki.draw_date_to):
                continue
        return ki
    return None


def apply_known_issue(finding, issues: list[KnownIssue], as_of: datetime) -> KnownIssue | None:
    """Match `finding` against `issues` and annotate it in place (accepted / known_issue_id / state).

    Returns the matched KnownIssue (any state) for matched-count bookkeeping, or None.
    """
    ki = match_known_issue(finding, issues, as_of)
    if ki is None:
        return None
    state = issue_state(ki, as_of)
    finding.known_issue_id = ki.id
    finding.known_issue_state = state
    if state != "active":
        return ki
    spec = RULES.get(finding.rule)
    if spec is not None and spec.needs_pin:
        pin = ki.pins.get(finding.rule)
        if json.dumps(pin, sort_keys=True) != json.dumps(finding.observed, sort_keys=True):
            finding.detail = f"{finding.detail} [pin_mismatch]"
            return ki
    finding.accepted = True
    return ki
