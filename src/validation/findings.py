"""The `Finding` type shared by the validation modules and the quality report.

Kept separate from `src.reporting.data_quality` (which re-exports it) so that
`lineage.py` and `reconcile.py` can build findings without importing the report module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Finding:
    source: str
    draw_id: str | None
    draw_date: str | None
    rule: str
    level: str  # "FAIL" | "WARN" | "INFO"
    detail: str
    observed: Any = None
    accepted: bool = False
    known_issue_id: str | None = None
    known_issue_state: str | None = None

    def sort_key(self) -> tuple:
        return (self.source, self.draw_id or "", self.rule, self.draw_date or "", self.detail)

    def to_dict(self) -> dict:
        return {
            "source": self.source, "draw_id": self.draw_id, "draw_date": self.draw_date,
            "rule": self.rule, "level": self.level, "detail": self.detail, "observed": self.observed,
            "accepted": self.accepted, "known_issue_id": self.known_issue_id,
            "known_issue_state": self.known_issue_state,
        }
