"""Runtime settings. Values come from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCAL_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value not in (None, "") else default


@dataclass(frozen=True)
class HttpSettings:
    timeout_seconds: float = field(default_factory=lambda: _env_float("HTTP_TIMEOUT_SECONDS", 30.0))
    max_retries: int = field(default_factory=lambda: _env_int("HTTP_MAX_RETRIES", 4))
    backoff_base_seconds: float = field(default_factory=lambda: _env_float("HTTP_BACKOFF_BASE_SECONDS", 1.0))
    backoff_max_seconds: float = field(default_factory=lambda: _env_float("HTTP_BACKOFF_MAX_SECONDS", 60.0))
    min_interval_seconds: float = field(default_factory=lambda: _env_float("HTTP_MIN_INTERVAL_SECONDS", 1.0))
    user_agent: str = field(
        default_factory=lambda: os.getenv(
            "HTTP_USER_AGENT", "Mozilla/5.0 (power655-research; historical data collection)"
        )
    )


@dataclass(frozen=True)
class Paths:
    root: Path = PROJECT_ROOT
    data: Path = PROJECT_ROOT / "data"

    @property
    def raw(self) -> Path:
        return self.data / "raw"

    @property
    def staging(self) -> Path:
        return self.data / "staging"

    @property
    def curated(self) -> Path:
        return self.data / "curated"

    @property
    def logs(self) -> Path:
        return self.data / "logs"

    @property
    def config(self) -> Path:
        return self.root / "configs"

    @property
    def reports(self) -> Path:
        return self.root / "reports"


VIETLOTT_BASE_URL = os.getenv("VIETLOTT_BASE_URL", "https://vietlott.vn")
VIETLOTT_655_DRAW_KEY = os.getenv("VIETLOTT_655_DRAW_KEY", "d9f032a7")
GITHUB_MIRROR_URL = os.getenv(
    "GITHUB_MIRROR_URL",
    "https://raw.githubusercontent.com/vietvudanh/vietlott-data/master/data/power655.jsonl",
)
