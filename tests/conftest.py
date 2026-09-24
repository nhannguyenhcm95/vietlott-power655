from __future__ import annotations

import json
from datetime import date, datetime, time, timezone
from pathlib import Path

import pytest

from src.api.http_client import HttpClient
from src.api.models import DrawRecord
from src.api.sources.github_mirror import GithubMirrorSource
from src.api.sources.vietlott_official import VietlottOfficialSource
from src.config import LOCAL_TZ, HttpSettings, Paths
from src.ingestion.loader import build_curated, run_ingestion

FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parent.parent


def _snapshot(root: Path) -> dict:
    """Relative path -> (size, mtime_ns) for every file under `root`, recursively (R3 N3)."""
    if not root.exists():
        return {}
    return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()}


@pytest.fixture(scope="session", autouse=True)
def _guard_real_data_and_reports_untouched():
    """No test may write under the real data/ or reports/ directories."""
    before = {"data": _snapshot(REPO_ROOT / "data"), "reports": _snapshot(REPO_ROOT / "reports")}
    yield
    after = {"data": _snapshot(REPO_ROOT / "data"), "reports": _snapshot(REPO_ROOT / "reports")}
    assert after == before, "a test modified the real data/ or reports/ directory"


class FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "", headers: dict | None = None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

    def json(self):
        return json.loads(self.text)


class FakeSession:
    """Returns scripted responses (or raises scripted exceptions) in order."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict]] = []
        self.headers: dict = {}

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError(f"unexpected request {method} {url}")
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class RoutingSession(FakeSession):
    """Dispatches every request to `handler(method, url, kwargs)`."""

    def __init__(self, handler):
        super().__init__([])
        self.handler = handler

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.handler(method, url, kwargs)


def make_client(session, **overrides) -> tuple[HttpClient, list[float]]:
    sleeps: list[float] = []
    settings = HttpSettings(**{"timeout_seconds": 5, "max_retries": 3, "backoff_base_seconds": 1, "backoff_max_seconds": 30,
                               "min_interval_seconds": 0, "user_agent": "test", **overrides})
    return HttpClient(settings, session=session, sleep=sleeps.append, jitter=lambda: 0.0), sleeps


def official_html(rows: list[tuple[str, str, list[int], int | None]]) -> str:
    """rows: (dd/mm/yyyy, draw_id, main numbers, special)."""
    trs = []
    for d, draw_id, main, special in rows:
        balls = "".join(f'<span class="bong_tron ">{n:02d}</span>' for n in main)
        if special is not None:
            balls += f' <span class="bong_tron-sperator">|</span><span class="bong_tron no-margin-right">{special:02d}</span>'
        trs.append(f'<tr><td>{d}</td><td><a href="/x?id={draw_id}">{draw_id}</a></td>'
                   f'<td><div class="day_so_ket_qua_v2">{balls}</div></td></tr>')
    if not trs:
        return ""
    return '<div><table class="table"><thead><tr><th>Ngày</th><th>Kỳ</th><th>Bộ số</th></tr></thead><tbody>' + "".join(trs) + "</tbody></table></div>"


def ajax_json(html: str, error: bool = False) -> str:
    return json.dumps({"value": {"HtmlContent": html, "Error": error, "InfoMessage": None}})


@pytest.fixture
def paths(tmp_path) -> Paths:
    return Paths(root=tmp_path, data=tmp_path / "data")


def rec(draw_id="00001", d=date(2017, 8, 1), main=(5, 10, 14, 23, 24, 38), special=35, source="test") -> DrawRecord:
    return DrawRecord(draw_id, d, tuple(main), special, source, datetime(2026, 1, 1, tzinfo=timezone.utc))


def official_site_session(rows, per_page=8):
    """A RoutingSession that serves the official AjaxPro endpoint. `rows`: (dd/mm/yyyy, draw_id, main, special), newest first."""
    def handler(method, url, kwargs):
        if url.endswith("winning-number-655"):
            return FakeResponse(200, "x = ServerSideDrawResult(RenderInfo, 'abc123', GameDrawId")
        if kwargs["headers"]["X-AjaxPro-Method"] == "ServerSideFrontEndCreateRenderInfo":
            return FakeResponse(200, json.dumps({"value": {"SiteId": "main.frontend.vi"}}))
        body = json.loads(kwargs["data"])
        i = body["PageIndex"]
        return FakeResponse(200, ajax_json(official_html(rows[i * per_page:(i + 1) * per_page])))
    return RoutingSession(handler)


def mirror_session(rows):
    """A FakeSession serving one jsonl file. `rows`: (draw_id, iso_date, main, special)."""
    lines = []
    for draw_id, d, main, special in rows:
        result = list(main) + ([special] if special is not None else [])
        lines.append(json.dumps({"date": d, "id": draw_id, "result": result}))
    text = "\n".join(lines) + ("\n" if lines else "")
    return FakeSession([FakeResponse(200, text, {"Content-Type": "text/plain"})])


@pytest.fixture
def frozen(monkeypatch):
    """freeze(paths): patches FROZEN_LAST_DRAW/FROZEN_VERSION to the fixture's current curated prefix."""
    from src.transformation import tables
    from src.validation import lineage

    def _freeze(paths: Paths):
        fact = tables.read_fact_draw(paths.curated)
        last_id = fact["draw_id"].iloc[-1]
        version = tables.dataset_version(fact)
        monkeypatch.setattr(lineage, "FROZEN_LAST_DRAW", last_id)
        monkeypatch.setattr(lineage, "FROZEN_VERSION", version)
        return last_id, version

    return _freeze


class BrokenSource:
    """A DrawSource stand-in whose `iter_raw_pages` always raises (simulates a source being down)."""

    def __init__(self, name: str, exc: BaseException | None = None):
        self.name = name
        self._exc = exc or ConnectionError(f"{name} is down")

    def iter_raw_pages(self, *a, **k):
        raise self._exc
        yield  # pragma: no cover - never reached, keeps this a generator function

    def parse(self, page):
        return []


def make_official_source(rows) -> VietlottOfficialSource:
    """rows: iterable of (draw_id, date, main_tuple, special), any order."""
    official_rows = [
        (d.strftime("%d/%m/%Y"), draw_id, list(main), special)
        for draw_id, d, main, special in sorted(rows, key=lambda r: r[0], reverse=True)
    ]
    client, _ = make_client(official_site_session(official_rows))
    return VietlottOfficialSource(client=client)


def make_mirror_source(rows) -> GithubMirrorSource:
    """rows: iterable of (draw_id, date, main_tuple, special), any order."""
    mirror_rows = [(draw_id, d.isoformat(), main, special) for draw_id, d, main, special in rows]
    client, _ = make_client(mirror_session(mirror_rows))
    return GithubMirrorSource(client=client)


def refresh_source_factory(official=None, mirror=None):
    """Build a `source_factory(name)` for `run_refresh`/tests.

    `official`/`mirror`: a list of (draw_id, date, main_tuple, special) rows, the string "down"
    (source raises), or None (an empty response: an official "empty fetch", a mirror single
    empty file).
    """
    def factory(name: str):
        spec = official if name == "vietlott_official" else mirror
        if spec == "down":
            return BrokenSource(name)
        rows = spec or []
        return make_official_source(rows) if name == "vietlott_official" else make_mirror_source(rows)
    return factory


def build_fixture(paths: Paths, draws, mirror_draws=None, today: date | None = None) -> datetime:
    """Build staging + curated fixtures through real ingestion (FakeSession, no network).

    `draws` / `mirror_draws`: iterables of (draw_id, date, main_tuple, special). `mirror_draws`
    defaults to `draws`. Returns `as_of`: 21:30 ICT on the date of the last official draw.
    """
    draws = list(draws)
    mirror_draws = list(draws if mirror_draws is None else mirror_draws)
    last_date = max(d for _, d, _, _ in draws)
    today = today or last_date

    official_rows = [
        (d.strftime("%d/%m/%Y"), draw_id, list(main), special)
        for draw_id, d, main, special in sorted(draws, key=lambda r: r[0], reverse=True)
    ]
    official_client, _ = make_client(official_site_session(official_rows))
    run_ingestion(VietlottOfficialSource(client=official_client), paths, mode="full", today=today)

    mirror_rows = [(draw_id, d.isoformat(), main, special) for draw_id, d, main, special in mirror_draws]
    mirror_client, _ = make_client(mirror_session(mirror_rows))
    run_ingestion(GithubMirrorSource(client=mirror_client), paths, mode="full", today=today)

    build_curated(paths, "vietlott_official")

    return datetime.combine(last_date, time(21, 30), tzinfo=LOCAL_TZ)
