from datetime import date

from src.transformation import tables
from src.validation.reconcile import reconcile
from tests.conftest import rec


def staging(records):
    return tables.records_to_frame(records, "run")


def test_records_are_canonicalized_ascending():
    df = staging([rec(main=(38, 5, 24, 10, 23, 14))])
    assert df.loc[0, tables.MAIN_COLS].tolist() == [5, 10, 14, 23, 24, 38]


def test_roundtrip_frame_records():
    r = rec()
    (back,) = tables.frame_to_records(staging([r]))
    assert (back.draw_id, back.draw_date, back.main_numbers, back.special_number) == (r.draw_id, r.draw_date, r.main_numbers, r.special_number)


def test_dataset_version_depends_on_content_only():
    a = staging([rec()])
    b = staging([rec()])
    b["retrieved_at"] = "2030-01-01T00:00:00+00:00"
    assert tables.dataset_version(a) == tables.dataset_version(b)
    assert tables.dataset_version(a) != tables.dataset_version(staging([rec(special=40)]))


def test_fact_draw_number_long_format():
    fd = tables.build_fact_draw(staging([rec(), rec("00002", date(2017, 8, 3), special=None)]), "v")
    long = tables.build_fact_draw_number(fd)
    assert len(long) == 6 + 1 + 6
    first = long[long.draw_id == "00001"]
    assert first["position"].tolist() == [1, 2, 3, 4, 5, 6, 7]
    assert first["is_special"].tolist() == [False] * 6 + [True]
    assert first["number"].tolist() == [5, 10, 14, 23, 24, 38, 35]


def test_dim_number():
    dim = tables.build_dim_number()
    assert dim["number"].tolist() == list(range(1, 56))
    assert (dim["parity"] == "odd").sum() == 28
    assert dim.set_index("number").loc[27, "band"] == "low" and dim.set_index("number").loc[28, "band"] == "high"


def test_reconcile_detects_mismatch_and_missing():
    left = staging([rec(), rec("00002", date(2017, 8, 3))])
    right = staging([rec(special=40), rec("00003", date(2017, 8, 5))])
    report = reconcile(left, right, "a", "b")
    assert report.only_left == ["00002"] and report.only_right == ["00003"]
    assert report.mismatches.to_dict("records") == [{"draw_id": "00001", "field": "special_number", "a": "35", "b": "40"}]
    assert not report.ok and report.matched == 0
