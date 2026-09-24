"""Record <-> DataFrame conversion and curated tables (PROJECT_STEPS.md section 5)."""
from __future__ import annotations

import hashlib
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from src.api.models import DrawRecord

MAIN_COLS = ["n1", "n2", "n3", "n4", "n5", "n6"]
STAGING_COLS = ["draw_id", "draw_date", *MAIN_COLS, "special_number", "source", "retrieved_at", "raw_run_id"]
CONTENT_COLS = ["draw_id", "draw_date", *MAIN_COLS, "special_number"]


def records_to_frame(records: list[DrawRecord], raw_run_id: str) -> pd.DataFrame:
    rows = []
    for r in records:
        nums = sorted(r.main_numbers)  # canonical ascending representation
        rows.append({
            "draw_id": r.draw_id,
            "draw_date": r.draw_date.isoformat(),
            **dict(zip(MAIN_COLS, nums)),
            "special_number": r.special_number,
            "source": r.source,
            "retrieved_at": r.retrieved_at.isoformat(),
            "raw_run_id": raw_run_id,
        })
    df = pd.DataFrame(rows, columns=STAGING_COLS)
    return normalize_staging(df)


def normalize_staging(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["draw_id"] = df["draw_id"].astype(str).str.zfill(5)
    df["draw_date"] = df["draw_date"].astype(str)
    for c in MAIN_COLS:
        df[c] = df[c].astype("int64")
    df["special_number"] = df["special_number"].astype("Int64")
    return df.sort_values("draw_id").reset_index(drop=True)


def frame_to_records(df: pd.DataFrame) -> list[DrawRecord]:
    return [
        DrawRecord(
            draw_id=row.draw_id,
            draw_date=date.fromisoformat(row.draw_date),
            main_numbers=tuple(int(getattr(row, c)) for c in MAIN_COLS),
            special_number=None if pd.isna(row.special_number) else int(row.special_number),
            source=row.source,
            retrieved_at=datetime.fromisoformat(row.retrieved_at),
        )
        for row in df.itertuples(index=False)
    ]


def dataset_version(df: pd.DataFrame) -> str:
    """Content hash of the draw data only, so identical data always gets the same version."""
    canonical = df[CONTENT_COLS].sort_values("draw_id").to_csv(index=False, lineterminator="\n")
    return "ds_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def build_fact_draw(staging: pd.DataFrame, version: str) -> pd.DataFrame:
    df = staging[["draw_id", "draw_date", *MAIN_COLS, "special_number", "source", "retrieved_at"]].copy()
    df["dataset_version"] = version
    return df


def build_fact_draw_number(fact_draw: pd.DataFrame) -> pd.DataFrame:
    main = fact_draw.melt(id_vars=["draw_id", "draw_date"], value_vars=MAIN_COLS, var_name="col", value_name="number")
    main["position"] = main["col"].str[1].astype(int)
    main["is_special"] = False
    special = fact_draw.loc[fact_draw["special_number"].notna(), ["draw_id", "draw_date", "special_number"]].rename(columns={"special_number": "number"})
    special["position"] = 7
    special["is_special"] = True
    out = pd.concat([main.drop(columns="col"), special], ignore_index=True)
    out["number"] = out["number"].astype("int64")
    return out[["draw_id", "draw_date", "position", "number", "is_special"]].sort_values(["draw_id", "position"]).reset_index(drop=True)


def read_fact_draw(path: Path) -> pd.DataFrame:
    """Read curated fact_draw.csv with explicit dtypes. `path` is the curated directory.

    The only reader of curated fact_draw, so every caller (report, frozen_prefix, refresh)
    agrees on dtypes. Raises FileNotFoundError if the file is absent.
    """
    fact_path = Path(path) / "fact_draw.csv" if not str(path).endswith(".csv") else Path(path)
    return pd.read_csv(fact_path, dtype={"draw_id": str, "draw_date": str, "special_number": "Int64"})


def build_dim_number() -> pd.DataFrame:
    numbers = range(1, 56)
    return pd.DataFrame({
        "number": list(numbers),
        "parity": ["even" if n % 2 == 0 else "odd" for n in numbers],
        "band": ["low" if n <= 27 else "high" for n in numbers],  # 1..27 low, 28..55 high
        "decade_group": [f"{(n // 10) * 10:02d}-{(n // 10) * 10 + 9:02d}" for n in numbers],
    })
