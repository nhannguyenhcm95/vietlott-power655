"""M5 development fold builder and dev-range guard (`docs/experiments/EXP-001.md` r2 section 3;
SPECIFICATION section 8.3). Restricted to draws 00001-01190 only.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

DEV_MAX_DRAW = 1190
VALIDATION_START = 981
VALIDATION_END = 1190


class DevRangeViolation(Exception):
    """Raised when a draw_id above the M5 development ceiling (01190) is passed in."""


def assert_dev_only(draw_ids) -> None:
    for d in draw_ids:
        di = int(d)
        if di > DEV_MAX_DRAW:
            raise DevRangeViolation(f"draw_id {di:05d} exceeds the M5 development ceiling {DEV_MAX_DRAW:05d}")


@dataclass(frozen=True)
class Fold:
    fold: int
    fit_start: int
    fit_end: int
    inner_train_start: int
    inner_train_end: int
    inner_val_start: int
    inner_val_end: int
    scored_start: int
    scored_end: int

    @property
    def n(self) -> int:
        return self.scored_end - self.scored_start + 1


def build_folds() -> list[Fold]:
    """Section 3: folds 1-13 (whole, 50 draws each) plus fold 14 (partial, 40 draws)."""
    folds: list[Fold] = []
    for i in range(1, 14):
        fit_end = 500 + 50 * (i - 1)
        scored_start = fit_end + 1
        scored_end = scored_start + 49
        inner_val_end = fit_end
        inner_val_start = inner_val_end - 99
        inner_train_end = inner_val_start - 1
        folds.append(Fold(i, 1, fit_end, 1, inner_train_end, inner_val_start, inner_val_end, scored_start, scored_end))

    fit_end = 1150
    scored_start = 1151
    scored_end = 1190
    inner_val_end = fit_end
    inner_val_start = inner_val_end - 99
    inner_train_end = inner_val_start - 1
    folds.append(Fold(14, 1, fit_end, 1, inner_train_end, inner_val_start, inner_val_end, scored_start, scored_end))

    assert_dev_only([f.scored_end for f in folds])
    assert_dev_only([f.fit_end for f in folds])
    return folds


def fold_table(folds: list[Fold] | None = None) -> pd.DataFrame:
    folds = folds if folds is not None else build_folds()
    rows = [{
        "fold": f.fold, "fit_start": f.fit_start, "fit_end": f.fit_end,
        "inner_train_start": f.inner_train_start, "inner_train_end": f.inner_train_end,
        "inner_val_start": f.inner_val_start, "inner_val_end": f.inner_val_end,
        "scored_start": f.scored_start, "scored_end": f.scored_end, "n": f.n,
    } for f in folds]
    return pd.DataFrame(rows)


def scored_draw_table(folds: list[Fold] | None = None) -> pd.DataFrame:
    """One row per scored draw_id (int, 501..1190) with its fold and in_validation flag."""
    folds = folds if folds is not None else build_folds()
    scored_ids: list[int] = []
    for f in folds:
        assert_dev_only(range(f.scored_start, f.scored_end + 1))
        scored_ids.extend(range(f.scored_start, f.scored_end + 1))
    assert_dev_only(scored_ids)

    fold_of: dict[int, int] = {}
    for f in folds:
        for d in range(f.scored_start, f.scored_end + 1):
            fold_of[d] = f.fold

    rows = [{
        "draw_id": d, "fold": fold_of[d],
        "in_validation": VALIDATION_START <= d <= VALIDATION_END,
    } for d in scored_ids]
    return pd.DataFrame(rows).sort_values("draw_id").reset_index(drop=True)
