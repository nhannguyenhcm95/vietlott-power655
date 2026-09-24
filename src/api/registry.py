"""Source lookup by name, so the loader/CLI never import a concrete source directly."""
from __future__ import annotations

from src.api.base import DrawSource
from src.api.http_client import HttpClient
from src.api.sources.github_mirror import GithubMirrorSource
from src.api.sources.vietlott_official import VietlottOfficialSource

SOURCES: dict[str, type[DrawSource]] = {
    VietlottOfficialSource.name: VietlottOfficialSource,
    GithubMirrorSource.name: GithubMirrorSource,
}


def get_source(name: str, client: HttpClient | None = None) -> DrawSource:
    try:
        cls = SOURCES[name]
    except KeyError:
        raise ValueError(f"unknown source {name!r}; available: {sorted(SOURCES)}") from None
    return cls(client=client)
