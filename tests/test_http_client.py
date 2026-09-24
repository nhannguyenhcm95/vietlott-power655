import pytest
import requests

from src.api.http_client import HttpError
from tests.conftest import FakeResponse, FakeSession, make_client


def test_returns_first_success_and_passes_timeout():
    session = FakeSession([FakeResponse(200, "ok")])
    client, sleeps = make_client(session)
    assert client.get("http://x").text == "ok"
    assert session.calls[0][2]["timeout"] == 5
    assert sleeps == []


def test_retries_5xx_with_exponential_backoff():
    session = FakeSession([FakeResponse(503), FakeResponse(500), FakeResponse(200, "ok")])
    client, sleeps = make_client(session)
    assert client.get("http://x").text == "ok"
    assert sleeps == [1, 2]


def test_retries_transport_errors():
    session = FakeSession([requests.Timeout("slow"), requests.ConnectionError("reset"), FakeResponse(200, "ok")])
    client, sleeps = make_client(session)
    assert client.get("http://x").text == "ok"
    assert len(session.calls) == 3


def test_429_honours_retry_after_header():
    session = FakeSession([FakeResponse(429, headers={"Retry-After": "7"}), FakeResponse(200, "ok")])
    client, sleeps = make_client(session)
    client.get("http://x")
    assert sleeps == [7.0]


def test_retry_after_is_capped_by_backoff_max():
    session = FakeSession([FakeResponse(429, headers={"Retry-After": "9999"}), FakeResponse(200, "ok")])
    client, sleeps = make_client(session)
    client.get("http://x")
    assert sleeps == [30]


def test_gives_up_after_bounded_retries():
    session = FakeSession([FakeResponse(500)] * 4)
    client, sleeps = make_client(session)
    with pytest.raises(HttpError, match="after 4 attempts"):
        client.get("http://x")
    assert len(session.calls) == 4
    assert sleeps == [1, 2, 4]  # no sleep after the final attempt


def test_non_retryable_4xx_fails_immediately():
    session = FakeSession([FakeResponse(404)])
    client, _ = make_client(session)
    with pytest.raises(HttpError) as exc:
        client.get("http://x")
    assert exc.value.status_code == 404
    assert len(session.calls) == 1


def test_min_interval_rate_limit_between_requests():
    session = FakeSession([FakeResponse(200), FakeResponse(200)])
    client, sleeps = make_client(session, min_interval_seconds=1.5)
    client._clock = lambda: 100.0  # no time passes between calls
    client.get("http://x")
    client.get("http://x")
    assert sleeps == [1.5]
