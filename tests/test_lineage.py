from datetime import date

from src.config import Paths
from src.transformation import tables
from src.validation.lineage import check_frozen_prefix, check_raw_lineage, received_ids
from tests.conftest import build_fixture

DRAWS = [
    ("00001", date(2017, 8, 1), (1, 2, 3, 4, 5, 6), 7),
    ("00002", date(2017, 8, 3), (2, 3, 4, 5, 6, 7), 8),
    ("00003", date(2017, 8, 5), (3, 4, 5, 6, 7, 8), 9),
]


def test_frozen_prefix_passes_when_frozen(paths, frozen):
    build_fixture(paths, DRAWS)
    frozen(paths)
    fact = tables.read_fact_draw(paths.curated)
    assert check_frozen_prefix(fact) == []


def test_frozen_prefix_fail(paths, frozen):
    build_fixture(paths, DRAWS)
    frozen(paths)
    fact = tables.read_fact_draw(paths.curated)
    tampered = fact.copy()
    tampered.loc[0, "special_number"] = 99  # alter a frozen row
    findings = check_frozen_prefix(tampered)
    assert findings and findings[0].rule == "frozen_prefix" and findings[0].level == "FAIL"


def test_staging_row_not_in_raw_fail(paths):
    build_fixture(paths, DRAWS)
    staging = tables.normalize_staging(
        __import__("pandas").read_csv(paths.staging / "vietlott_official" / "draws.csv", dtype={"draw_id": str, "draw_date": str})
    )
    tampered = staging.copy()
    tampered.loc[0, "n1"] = 55  # no longer matches what was archived
    findings = check_raw_lineage(tampered, paths, "vietlott_official")
    assert any(f.rule == "raw_lineage" and f.level == "FAIL" for f in findings)


def test_missing_raw_run_fail(paths):
    build_fixture(paths, DRAWS)
    staging = tables.normalize_staging(
        __import__("pandas").read_csv(paths.staging / "vietlott_official" / "draws.csv", dtype={"draw_id": str, "draw_date": str})
    )
    tampered = staging.copy()
    tampered.loc[0, "raw_run_id"] = "does-not-exist"
    findings = check_raw_lineage(tampered, paths, "vietlott_official")
    assert any(f.rule == "raw_lineage" and "missing" in f.detail for f in findings)


def test_raw_lineage_clean_passes(paths):
    build_fixture(paths, DRAWS)
    staging = tables.normalize_staging(
        __import__("pandas").read_csv(paths.staging / "vietlott_official" / "draws.csv", dtype={"draw_id": str, "draw_date": str})
    )
    assert check_raw_lineage(staging, paths, "vietlott_official") == []


def test_received_ids(paths):
    build_fixture(paths, DRAWS)
    import pandas as pd
    log = pd.read_csv(paths.logs / "ingestion_log.csv", dtype=str)
    run_id = log[log["source"] == "vietlott_official"].iloc[-1]["run_id"]
    assert received_ids(paths, "vietlott_official", run_id) == {"00001", "00002", "00003"}
