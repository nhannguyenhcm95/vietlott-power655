import json
from datetime import date, datetime, timezone

import pytest

from src.api.base import ParseError
from src.api.models import RawPage
from src.api.registry import get_source
from src.api.sources.github_mirror import GithubMirrorSource
from src.api.sources.vietlott_official import VietlottOfficialSource
from tests.conftest import FIXTURES, FakeResponse, RoutingSession, ajax_json, make_client, official_html

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


def page(content: str, source="vietlott_official", idx=0) -> RawPage:
    return RawPage(source, idx, "http://x", {}, 200, content, "application/json", NOW)


# ---------------------------------------------------------------- official parser
def test_parse_real_official_page_snapshot():
    content = (FIXTURES / "official_page0.json").read_text(encoding="utf-8")
    records = VietlottOfficialSource(client=object()).parse(page(content))
    assert len(records) == 8
    first = records[0]
    assert first.draw_id == "01401"
    assert first.draw_date == date(2026, 9, 22)
    assert first.main_numbers == (1, 3, 9, 11, 41, 46)
    assert first.special_number == 10
    assert [r.draw_no for r in records] == list(range(1401, 1393, -1))


def test_parse_row_without_special():
    html = official_html([("01/08/2017", "00001", [5, 10, 14, 23, 24, 38], None)])
    (r,) = VietlottOfficialSource(client=object()).parse(page(ajax_json(html)))
    assert r.special_number is None and r.main_numbers == (5, 10, 14, 23, 24, 38)


def test_parse_empty_page_returns_no_records():
    assert VietlottOfficialSource(client=object()).parse(page(ajax_json(""))) == []


@pytest.mark.parametrize("content", ["not json", json.dumps({"x": 1}), ajax_json("<p>maintenance</p>"), ajax_json("", error=True)])
def test_parse_rejects_unexpected_payloads(content):
    with pytest.raises(ParseError):
        VietlottOfficialSource(client=object()).parse(page(content))


def test_parse_rejects_bad_date():
    html = official_html([("2017-08-01", "00001", [1, 2, 3, 4, 5, 6], 7)])
    with pytest.raises(ParseError, match="bad date"):
        VietlottOfficialSource(client=object()).parse(page(ajax_json(html)))


# ---------------------------------------------------------------- official pagination (mocked HTTP)
def draws(first_no: int, last_no: int):
    """Descending synthetic draws, one per 2 days ending 2026-09-22."""
    out = []
    for no in range(first_no, last_no - 1, -1):
        d = date.fromordinal(date(2026, 9, 22).toordinal() - 2 * (first_no - no))
        out.append((d.strftime("%d/%m/%Y"), f"{no:05d}", [1, 2, 3, 4, 5, 6], 7))
    return out


def fake_site(all_rows, per_page=8):
    def handler(method, url, kwargs):
        if url.endswith("winning-number-655"):
            return FakeResponse(200, "x = ServerSideDrawResult(RenderInfo, 'abc123', GameDrawId")
        if kwargs["headers"]["X-AjaxPro-Method"] == "ServerSideFrontEndCreateRenderInfo":
            return FakeResponse(200, json.dumps({"value": {"SiteId": "main.frontend.vi"}}))
        body = json.loads(kwargs["data"])
        i = body["PageIndex"]
        assert body["Key"] == "abc123"
        return FakeResponse(200, ajax_json(official_html(all_rows[i * per_page:(i + 1) * per_page])))
    return RoutingSession(handler)


def page_requests(session):
    return [json.loads(k["data"])["PageIndex"] for m, u, k in session.calls if "Game655" in u]


def test_full_pagination_stops_on_empty_page():
    session = fake_site(draws(20, 1))
    src = VietlottOfficialSource(client=make_client(session)[0])
    records = src.fetch()
    assert sorted(r.draw_no for r in records) == list(range(1, 21))
    assert page_requests(session) == [0, 1, 2, 3]  # page 3 is empty


def test_incremental_stops_at_known_draw():
    session = fake_site(draws(20, 1))
    src = VietlottOfficialSource(client=make_client(session)[0])
    pages = list(src.iter_raw_pages(stop_at_draw_id="00015"))
    assert page_requests(session) == [0]  # page 0 covers 20..13, which reaches 15
    assert len(pages) == 1


def test_start_date_stops_pagination_and_filters():
    rows = draws(20, 1)
    session = fake_site(rows)
    src = VietlottOfficialSource(client=make_client(session)[0])
    start = date(2026, 9, 10)
    records = src.fetch(start_date=start)
    assert all(r.draw_date >= start for r in records)
    assert page_requests(session) == [0]


# ---------------------------------------------------------------- github mirror
def test_github_mirror_parse():
    content = '{"date":"2017-08-01","id":"00001","result":[5,10,14,23,24,38,35],"process_time":"x"}\n\n' \
              '{"date":"2017-08-03","id":"2","result":[4,9,24,25,27,45,40]}\n'
    records = GithubMirrorSource(client=object()).parse(page(content, "github_mirror"))
    assert [r.draw_id for r in records] == ["00001", "00002"]
    assert records[0].main_numbers == (5, 10, 14, 23, 24, 38) and records[0].special_number == 35


def test_github_mirror_bad_line_raises():
    with pytest.raises(ParseError, match="line 1"):
        GithubMirrorSource(client=object()).parse(page('{"date":"bad"}', "github_mirror"))


def test_registry_unknown_source():
    with pytest.raises(ValueError, match="unknown source"):
        get_source("nope")
