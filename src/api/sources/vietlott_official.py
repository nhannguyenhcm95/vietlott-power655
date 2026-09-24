"""Official vietlott.vn source (AjaxPro endpoint behind the 'winning-number-655' page).

The endpoint returns JSON whose `value.HtmlContent` is an HTML table with 8 draws per
page, newest first. PageIndex starts at 0; a page with no rows marks the end.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timezone
from typing import Iterator

from bs4 import BeautifulSoup

from src.api.base import DrawSource, ParseError
from src.api.http_client import HttpClient
from src.api.models import DrawRecord, RawPage
from src.config import VIETLOTT_655_DRAW_KEY, VIETLOTT_BASE_URL

log = logging.getLogger(__name__)

RENDER_INFO_PATH = "/ajaxpro/Vietlott.Utility.WebEnvironments,Vietlott.Utility.ashx"
DRAW_RESULT_PATH = "/ajaxpro/Vietlott.PlugIn.WebParts.Game655CompareWebPart,Vietlott.PlugIn.WebParts.ashx"
LIST_PAGE_PATH = "/vi/trung-thuong/ket-qua-trung-thuong/winning-number-655"
SITE_ID = "main.frontend.vi"
KEY_PATTERN = re.compile(r"ServerSideDrawResult\(\s*RenderInfo\s*,\s*'([0-9a-fA-F]+)'")
MAX_PAGES = 2000


class VietlottOfficialSource(DrawSource):
    name = "vietlott_official"

    def __init__(self, client: HttpClient | None = None, base_url: str = VIETLOTT_BASE_URL, default_key: str = VIETLOTT_655_DRAW_KEY):
        self.client = client or HttpClient()
        self.base_url = base_url.rstrip("/")
        self.default_key = default_key
        self._render_info: dict | None = None
        self._key: str | None = None

    # --- session bootstrap -------------------------------------------------
    def _discover_key(self) -> str:
        try:
            html = self.client.get(self.base_url + LIST_PAGE_PATH).text
        except Exception as exc:  # key discovery is best-effort
            log.warning("draw_key_discovery_failed", extra={"error": str(exc)})
            return self.default_key
        match = KEY_PATTERN.search(html)
        if not match:
            log.warning("draw_key_not_found_using_default", extra={"default_key": self.default_key})
            return self.default_key
        return match.group(1)

    def _bootstrap(self) -> None:
        if self._render_info is not None:
            return
        self._key = self._discover_key()
        resp = self.client.post(
            self.base_url + RENDER_INFO_PATH,
            headers={"X-AjaxPro-Method": "ServerSideFrontEndCreateRenderInfo", "Content-Type": "text/plain; charset=utf-8"},
            data=json.dumps({"SiteId": SITE_ID}),
        )
        try:
            self._render_info = resp.json()["value"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ParseError(f"unexpected RenderInfo response: {resp.text[:200]}") from exc

    # --- I/O ---------------------------------------------------------------
    def fetch_page(self, page_index: int) -> RawPage:
        self._bootstrap()
        params = {
            "Key": self._key,
            "GameDrawId": "",
            "ArrayNumbers": [["" for _ in range(18)] for _ in range(5)],
            "CheckMulti": False,
            "PageIndex": page_index,
        }
        body = {"ORenderInfo": self._render_info, **params}
        url = self.base_url + DRAW_RESULT_PATH
        resp = self.client.post(
            url,
            headers={
                "X-AjaxPro-Method": "ServerSideDrawResult",
                "Content-Type": "text/plain; charset=utf-8",
                "Referer": self.base_url + LIST_PAGE_PATH,
            },
            data=json.dumps(body),
        )
        return RawPage(
            source=self.name,
            page_index=page_index,
            url=url,
            request_params={"PageIndex": page_index, "Key": self._key},
            status_code=resp.status_code,
            content=resp.text,
            content_type=resp.headers.get("Content-Type", "application/json"),
            retrieved_at=datetime.now(timezone.utc),
        )

    def iter_raw_pages(self, start_date: date | None = None, end_date: date | None = None, stop_at_draw_id: str | None = None) -> Iterator[RawPage]:
        for page_index in range(MAX_PAGES):
            page = self.fetch_page(page_index)
            records = self.parse(page)
            if not records:
                log.info("pagination_end", extra={"source": self.name, "page_index": page_index})
                return
            yield page
            oldest = min(records, key=lambda r: r.draw_no)
            if start_date is not None and oldest.draw_date < start_date:
                return
            if stop_at_draw_id is not None and oldest.draw_no <= int(stop_at_draw_id):
                return
        raise RuntimeError(f"pagination exceeded {MAX_PAGES} pages; aborting")

    # --- parsing -----------------------------------------------------------
    def parse(self, page: RawPage) -> list[DrawRecord]:
        try:
            value = json.loads(page.content)["value"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ParseError(f"page {page.page_index}: response is not AjaxPro JSON") from exc
        if value.get("Error"):
            raise ParseError(f"page {page.page_index}: endpoint reported Error=true: {value.get('InfoMessage')}")
        html = value.get("HtmlContent") or ""
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")
        if table is None:
            if html.strip():
                raise ParseError(f"page {page.page_index}: no result table in HtmlContent")
            return []
        body = table.find("tbody") or table
        records = []
        for tr in body.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 3:
                continue
            records.append(self._parse_row(tds, page))
        return records

    def _parse_row(self, tds, page: RawPage) -> DrawRecord:
        date_text = tds[0].get_text(strip=True)
        draw_id = tds[1].get_text(strip=True)
        try:
            draw_date = datetime.strptime(date_text, "%d/%m/%Y").date()
        except ValueError as exc:
            raise ParseError(f"page {page.page_index}: bad date {date_text!r} for draw {draw_id!r}") from exc
        if not draw_id.isdigit():
            raise ParseError(f"page {page.page_index}: bad draw id {draw_id!r}")
        main: list[int] = []
        special: list[int] = []
        seen_separator = False
        for span in tds[2].find_all("span"):
            classes = span.get("class") or []
            if "bong_tron-sperator" in classes:
                seen_separator = True
                continue
            if "bong_tron" not in classes:
                continue
            text = span.get_text(strip=True)
            if not text.isdigit():
                raise ParseError(f"page {page.page_index}: non-numeric ball {text!r} in draw {draw_id}")
            (special if seen_separator else main).append(int(text))
        if len(special) > 1:
            raise ParseError(f"page {page.page_index}: {len(special)} special numbers in draw {draw_id}")
        return DrawRecord(
            draw_id=draw_id.zfill(5),
            draw_date=draw_date,
            main_numbers=tuple(main),
            special_number=special[0] if special else None,
            source=self.name,
            retrieved_at=page.retrieved_at,
        )
