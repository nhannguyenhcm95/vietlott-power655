"""Data contracts shared by all draw sources."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class DrawRecord:
    """One Power 6/55 draw as returned by a source adapter (not yet validated)."""

    draw_id: str
    draw_date: date
    main_numbers: tuple[int, ...]
    special_number: int | None
    source: str
    retrieved_at: datetime

    @property
    def draw_no(self) -> int:
        return int(self.draw_id)


@dataclass(frozen=True)
class RawPage:
    """A raw response exactly as received, archived before any parsing."""

    source: str
    page_index: int
    url: str
    request_params: dict[str, Any]
    status_code: int
    content: str
    content_type: str
    retrieved_at: datetime
    extra: dict[str, Any] = field(default_factory=dict)
