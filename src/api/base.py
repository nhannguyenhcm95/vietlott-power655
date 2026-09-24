"""Replaceable source-adapter interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Iterator

from src.api.models import DrawRecord, RawPage


class ParseError(ValueError):
    """The raw payload does not have the structure the parser expects."""


class DrawSource(ABC):
    """A source of Power 6/55 draw results.

    Sources are split into two steps so raw payloads can be archived before parsing:
    `iter_raw_pages` performs I/O, `parse` is a pure function of one raw page.
    """

    name: str

    @abstractmethod
    def iter_raw_pages(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        stop_at_draw_id: str | None = None,
    ) -> Iterator[RawPage]:
        """Yield raw pages covering [start_date, end_date].

        `stop_at_draw_id` lets incremental loads stop paginating once a page reaches a
        draw that is already stored (sources may still yield that last page).
        """

    @abstractmethod
    def parse(self, page: RawPage) -> list[DrawRecord]:
        """Parse one raw page into draw records (no semantic validation)."""

    def fetch(self, start_date: date | None = None, end_date: date | None = None) -> list[DrawRecord]:
        records: list[DrawRecord] = []
        for page in self.iter_raw_pages(start_date, end_date):
            records.extend(self.parse(page))
        return filter_by_date(records, start_date, end_date)


def filter_by_date(records: list[DrawRecord], start_date: date | None, end_date: date | None) -> list[DrawRecord]:
    return [
        r
        for r in records
        if (start_date is None or r.draw_date >= start_date) and (end_date is None or r.draw_date <= end_date)
    ]
