"""Curated/staging integrity: the frozen history prefix and raw-data lineage.

`raw_lineage` and `received_ids` re-parse archived raw pages offline (no network) to
verify that staging/curated content matches what was actually retrieved.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.api.registry import get_source
from src.config import Paths
from src.ingestion.raw_archive import RawArchive
from src.transformation import tables
from src.validation.findings import Finding

FROZEN_LAST_DRAW = "01401"
FROZEN_VERSION = "ds_cbdf3834368e"

_SOURCE_LABEL = {"vietlott_official": "off", "github_mirror": "mir"}


def _level_for(source: str, fail_level: str = "FAIL", warn_level: str = "WARN") -> str:
    return fail_level if source == "vietlott_official" else warn_level


def check_frozen_prefix(df: pd.DataFrame) -> list[Finding]:
    """Draws up to and including FROZEN_LAST_DRAW must always hash to FROZEN_VERSION.

    `df` must contain `tables.CONTENT_COLS`. Always source="vietlott_official"; FAIL, never acceptable.
    """
    prefix = df[df["draw_id"].astype(str) <= FROZEN_LAST_DRAW]
    n = len(prefix)
    if n == 0:
        return [Finding("vietlott_official", None, None, "frozen_prefix", "FAIL",
                         f"no rows with draw_id <= {FROZEN_LAST_DRAW}")]
    version = tables.dataset_version(prefix)
    expected_n = int(FROZEN_LAST_DRAW)
    if n != expected_n or version != FROZEN_VERSION:
        return [Finding("vietlott_official", None, None, "frozen_prefix", "FAIL",
                         f"prefix has {n} rows (expected {expected_n}) and hashes to {version} (expected {FROZEN_VERSION})",
                         observed={"rows": str(n), "dataset_version": version})]
    return []


def received_ids(paths: Paths, source: str, run_id: str) -> set[str]:
    """draw_ids parsed offline (no network) from one raw run."""
    archive = RawArchive(paths.raw)
    pages = archive.read_pages(source, run_id)
    src = get_source(source)
    ids: set[str] = set()
    for page in pages:
        ids.update(r.draw_id for r in src.parse(page))
    return ids


def _content_tuple(draw_id: str, draw_date: str, main: tuple[int, ...], special) -> tuple:
    return (draw_id, draw_date, tuple(sorted(main)), None if pd.isna(special) else int(special))


def check_raw_lineage(staging: pd.DataFrame, paths: Paths, source: str) -> list[Finding]:
    """Every staging row must equal a record parsed offline from its raw_run_id."""
    findings: list[Finding] = []
    level = _level_for(source)
    if staging.empty:
        return findings
    archive = RawArchive(paths.raw)
    src = get_source(source)
    cache: dict[str, set[tuple] | None] = {}
    for row in staging.itertuples(index=False):
        run_id = row.raw_run_id
        if run_id not in cache:
            try:
                pages = archive.read_pages(source, run_id)
                cache[run_id] = {
                    _content_tuple(r.draw_id, r.draw_date.isoformat(), r.main_numbers, r.special_number)
                    for r in (rec for page in pages for rec in src.parse(page))
                }
            except Exception:
                cache[run_id] = None
        parsed = cache[run_id]
        if parsed is None:
            findings.append(Finding(source, row.draw_id, row.draw_date, "raw_lineage", level,
                                     f"raw run {run_id} referenced by draw {row.draw_id} is missing"))
            continue
        main = tuple(getattr(row, c) for c in tables.MAIN_COLS)
        key = _content_tuple(row.draw_id, row.draw_date, main, row.special_number)
        if key not in parsed:
            findings.append(Finding(source, row.draw_id, row.draw_date, "raw_lineage", level,
                                     f"draw {row.draw_id} in staging does not match any record parsed from raw run {run_id}"))
    return findings
