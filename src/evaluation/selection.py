"""W selection rule for Baseline 2 (`docs/experiments/EXP-001.md` r2 section 4; SPECIFICATION
section 7). Ties are measured against the minimum only (not chained); reading recorded in
TASKBOARD "M5 records" (audit finding 4).
"""
from __future__ import annotations

import pandas as pd

TIE_TOLERANCE = 1e-12


def select_w(l_w: dict[int, float]) -> tuple[int, pd.DataFrame]:
    """l_w: {W: mean validation log loss}. Returns (W*, table) where table has columns
    W, L_W, L_W_minus_Lstar, in_tie_set, selected."""
    if not l_w:
        raise ValueError("l_w must be non-empty")
    l_star = min(l_w.values())
    tie_set = {w for w, l in l_w.items() if (l - l_star) <= TIE_TOLERANCE}
    w_star = max(tie_set)

    rows = []
    for w in sorted(l_w):
        rows.append({
            "W": w, "L_W": l_w[w], "L_W_minus_Lstar": l_w[w] - l_star,
            "in_tie_set": w in tie_set, "selected": w == w_star,
        })
    return w_star, pd.DataFrame(rows)
