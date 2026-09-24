"""Cross-source reconciliation: compare two staged datasets draw by draw."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from src.validation.findings import Finding
from src.validation.known_issues import KnownIssue, apply_known_issue

COMPARE_COLS = ["draw_date", "n1", "n2", "n3", "n4", "n5", "n6", "special_number"]
MIRROR_LAG_WARN_THRESHOLD = 3


@dataclass
class ReconcileReport:
    left: str
    right: str
    matched: int
    only_left: list[str]
    only_right: list[str]
    mismatches: pd.DataFrame
    left_ids: set = field(default_factory=set)
    right_ids: set = field(default_factory=set)

    @property
    def ok(self) -> bool:
        return self.mismatches.empty

    def summary(self) -> dict:
        return {
            "left": self.left,
            "right": self.right,
            "matched": self.matched,
            "only_left": len(self.only_left),
            "only_right": len(self.only_right),
            "mismatched_draws": int(self.mismatches["draw_id"].nunique()) if not self.mismatches.empty else 0,
            "ok": self.ok,
        }


def reconcile(left: pd.DataFrame, right: pd.DataFrame, left_name: str, right_name: str) -> ReconcileReport:
    l = left.set_index("draw_id")[COMPARE_COLS].astype(str)
    r = right.set_index("draw_id")[COMPARE_COLS].astype(str)
    common = l.index.intersection(r.index)
    rows = []
    for col in COMPARE_COLS:
        diff = l.loc[common, col] != r.loc[common, col]
        for draw_id in common[diff.to_numpy()]:
            rows.append({"draw_id": draw_id, "field": col, left_name: l.at[draw_id, col], right_name: r.at[draw_id, col]})
    mismatches = pd.DataFrame(rows, columns=["draw_id", "field", left_name, right_name])
    mismatched_ids = set(mismatches["draw_id"])
    return ReconcileReport(
        left=left_name,
        right=right_name,
        matched=len([d for d in common if d not in mismatched_ids]),
        only_left=sorted(set(l.index) - set(r.index)),
        only_right=sorted(set(r.index) - set(l.index)),
        mismatches=mismatches,
        left_ids=set(l.index),
        right_ids=set(r.index),
    )


@dataclass
class ReconcileAssessment:
    status: str
    findings: list[Finding]
    unaccepted_mismatch_ids: set
    mirror_lag_draws: int
    blocking_ids: set


def assess_reconcile(
    rep: ReconcileReport,
    issues: list[KnownIssue],
    as_of: datetime,
    published_ids: set,
) -> ReconcileAssessment:
    """Turn a ReconcileReport (left=official, right=mirror) into findings + a status.

    Used identically by the report and (in M2-T3) by refresh, so they cannot disagree.
    """
    findings: list[Finding] = []
    mirror_max = max((int(i) for i in rep.right_ids), default=None)

    by_draw: dict[str, list] = {}
    for row in rep.mismatches.itertuples(index=False):
        by_draw.setdefault(row.draw_id, []).append(row)
    unaccepted_mismatch_ids: set = set()
    for draw_id, rows in by_draw.items():
        observed = {r.field: {rep.left: getattr(r, rep.left), rep.right: getattr(r, rep.right)} for r in rows}
        f = Finding(rep.right, draw_id, None, "reconcile.field_mismatch", "FAIL",
                    f"draw {draw_id} disagrees on {sorted(observed)}", observed=observed)
        apply_known_issue(f, issues, as_of)
        findings.append(f)
        if not f.accepted:
            unaccepted_mismatch_ids.add(draw_id)

    mirror_lag_draws = 0
    for draw_id in rep.only_left:
        if mirror_max is not None and int(draw_id) <= mirror_max:
            f = Finding(rep.right, draw_id, None, "reconcile.only_left", "WARN",
                        f"draw {draw_id} is in {rep.left} but not in {rep.right}")
        else:
            mirror_lag_draws += 1
            lag = mirror_lag_draws
            level = "INFO" if lag <= MIRROR_LAG_WARN_THRESHOLD else "WARN"
            f = Finding(rep.right, draw_id, None, "reconcile.mirror_lag", level,
                        f"draw {draw_id} not yet received by {rep.right} (lag {lag})")
        apply_known_issue(f, issues, as_of)
        findings.append(f)

    for draw_id in rep.only_right:
        f = Finding(rep.left, draw_id, None, "reconcile.only_right", "WARN",
                    f"draw {draw_id} is in {rep.right} but not in {rep.left}")
        apply_known_issue(f, issues, as_of)
        findings.append(f)

    # "the set about to be published": official ids not yet in curated (D2). A mismatch on an
    # id that is *already* published does not block (see M2-T3 §2.2's realistic-mismatch case).
    about_to_be_published = rep.left_ids - set(published_ids or set())
    blocking_ids = unaccepted_mismatch_ids & about_to_be_published

    levels = {f.level for f in findings if not f.accepted}
    if "FAIL" in levels:
        status = "FAIL"
    elif "WARN" in levels:
        status = "WARN"
    else:
        status = "PASS"

    return ReconcileAssessment(
        status=status,
        findings=sorted(findings, key=lambda f: f.sort_key()),
        unaccepted_mismatch_ids=unaccepted_mismatch_ids,
        mirror_lag_draws=mirror_lag_draws,
        blocking_ids=blocking_ids,
    )
