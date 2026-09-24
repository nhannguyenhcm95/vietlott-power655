"""HTTP client with timeout, bounded retry, exponential backoff and rate limiting."""
from __future__ import annotations

import logging
import random
import time
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from typing import Any, Callable

import requests

from src.config import HttpSettings

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class HttpError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class HttpClient:
    def __init__(
        self,
        settings: HttpSettings | None = None,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        jitter: Callable[[], float] = random.random,
    ):
        self.settings = settings or HttpSettings()
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", self.settings.user_agent)
        self._sleep = sleep
        self._clock = clock
        self._jitter = jitter
        self._last_request_at: float | None = None

    def _respect_rate_limit(self) -> None:
        if self._last_request_at is None:
            return
        wait = self.settings.min_interval_seconds - (self._clock() - self._last_request_at)
        if wait > 0:
            self._sleep(wait)

    def _backoff(self, attempt: int) -> float:
        base = self.settings.backoff_base_seconds * (2 ** attempt)
        return min(self.settings.backoff_max_seconds, base * (1 + 0.25 * self._jitter()))

    @staticmethod
    def _retry_after(response: requests.Response) -> float | None:
        value = response.headers.get("Retry-After")
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                when = parsedate_to_datetime(value)
                return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError):
                return None

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", self.settings.timeout_seconds)
        attempts = self.settings.max_retries + 1
        last_error: str = ""
        for attempt in range(attempts):
            self._respect_rate_limit()
            self._last_request_at = self._clock()
            try:
                response = self.session.request(method, url, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                delay = self._backoff(attempt)
                log.warning("http_transport_error", extra={"url": url, "attempt": attempt + 1, "error": last_error, "retry_in": delay})
            else:
                if response.status_code < 400:
                    log.debug("http_ok", extra={"url": url, "status": response.status_code, "attempt": attempt + 1})
                    return response
                if response.status_code not in RETRYABLE_STATUS:
                    raise HttpError(f"{method} {url} -> HTTP {response.status_code}", response.status_code)
                last_error = f"HTTP {response.status_code}"
                retry_after = self._retry_after(response) if response.status_code == 429 else None
                delay = retry_after if retry_after is not None else self._backoff(attempt)
                delay = min(delay, self.settings.backoff_max_seconds)
                log.warning("http_retryable_status", extra={"url": url, "status": response.status_code, "attempt": attempt + 1, "retry_in": delay})
            if attempt < attempts - 1:
                self._sleep(delay)
        raise HttpError(f"{method} {url} failed after {attempts} attempts: {last_error}")

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("POST", url, **kwargs)
