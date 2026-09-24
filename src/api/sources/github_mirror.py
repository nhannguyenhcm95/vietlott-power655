"""Community mirror: github.com/vietvudanh/vietlott-data (daily scrape of vietlott.vn).

Format: JSON lines {"date": "YYYY-MM-DD", "id": "00001", "result": [n1..n6, special], ...}.
Used as a secondary source for cross-checking the official source.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Iterator

from src.api.base import DrawSource, ParseError
from src.api.http_client import HttpClient
from src.api.models import DrawRecord, RawPage
from src.config import GITHUB_MIRROR_URL


class GithubMirrorSource(DrawSource):
    name = "github_mirror"

    def __init__(self, client: HttpClient | None = None, url: str = GITHUB_MIRROR_URL):
        self.client = client or HttpClient()
        self.url = url

    def iter_raw_pages(self, start_date: date | None = None, end_date: date | None = None, stop_at_draw_id: str | None = None) -> Iterator[RawPage]:
        # Single file, no pagination.
        resp = self.client.get(self.url)
        yield RawPage(
            source=self.name,
            page_index=0,
            url=self.url,
            request_params={},
            status_code=resp.status_code,
            content=resp.text,
            content_type=resp.headers.get("Content-Type", "text/plain"),
            retrieved_at=datetime.now(timezone.utc),
        )

    def parse(self, page: RawPage) -> list[DrawRecord]:
        records = []
        for line_no, line in enumerate(page.content.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                draw_date = date.fromisoformat(row["date"])
                result = [int(x) for x in row["result"]]
                draw_id = str(row["id"]).zfill(5)
            except (ValueError, KeyError, TypeError) as exc:
                raise ParseError(f"line {line_no}: {exc}") from exc
            records.append(
                DrawRecord(
                    draw_id=draw_id,
                    draw_date=draw_date,
                    main_numbers=tuple(result[:6]),
                    special_number=result[6] if len(result) > 6 else None,
                    source=self.name,
                    retrieved_at=page.retrieved_at,
                )
            )
        return records
