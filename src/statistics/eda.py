"""Draw-level and number-level EDA metrics (M3 spec section 2, 4). Pure functions: DataFrame /
ndarray in, DataFrame out. No I/O, no globals mutated. Callers pass in already-loaded,
already-filtered analysis rows (`t` = 1..n ordinal already attached).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from src.statistics import null_reference as nr
from src.transformation import tables

MAIN_COLS = ["n1", "n2", "n3", "n4", "n5", "n6"]
N_NUMBERS = 55
K_MAIN = 6
P_NUMBER = K_MAIN / N_NUMBERS
Q_PAIR = 1 / 99
MIN_EXPECTED = 5.0
APPROX_EXPECTED_MEAN_GAP = 55 / 6
APPROX_EXPECTED_SD_GAP = math.sqrt(74.86)


# ---------------------------------------------------------------------------
# D1-D6 draw metrics
# ---------------------------------------------------------------------------

def draw_metrics(df: pd.DataFrame) -> pd.DataFrame:
    out = df[["draw_id", "draw_date"] + MAIN_COLS].copy()
    main = out[MAIN_COLS].to_numpy(dtype=np.int64)
    out["sum"] = main.sum(axis=1)
    out["min"] = main[:, 0]
    out["max"] = main[:, -1]
    out["range"] = out["max"] - out["min"]
    odd = (main % 2 != 0).sum(axis=1)
    out["odd_count"] = odd
    out["even_count"] = 6 - odd
    low = (main <= 27).sum(axis=1)
    out["low_count"] = low
    out["high_count"] = 6 - low
    gaps = np.diff(main, axis=1)
    for i in range(5):
        out[f"gap_{i + 1}"] = gaps[:, i]
    out["consecutive_pairs"] = (gaps == 1).sum(axis=1)
    out["max_gap"] = gaps.max(axis=1)
    out["min_gap"] = gaps.min(axis=1)
    return out.sort_values("draw_id").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Tail-pooling helper (spec section 3.1, "Cell pooling")
# ---------------------------------------------------------------------------

def _label_cells(cells: list[dict], n_obs: int) -> list[dict]:
    out = []
    for i, c in enumerate(cells):
        if c["n_units"] == 1:
            label = str(c["lo"]) if c["lo"] == c["hi"] else f"{c['lo']}-{c['hi']}"
        elif i == 0:
            label = f"<={c['hi']}"
        elif i == len(cells) - 1:
            label = f">={c['lo']}"
        else:
            label = f"{c['lo']}-{c['hi']}"
        out.append({"cell": label, "lo": c["lo"], "hi": c["hi"], "null_prob": c["prob"], "expected_count": c["prob"] * n_obs})
    return out


def _pool_cells(units: list[dict], n_obs: int, min_expected: float = MIN_EXPECTED) -> list[dict]:
    """units: [{'lo','hi','prob'}], sorted ascending by lo. Merges tail cells inward, each tail
    handled separately, until every remaining unmerged cell has n_obs * prob >= min_expected -
    both individually (a lone cell must clear the threshold on its own) AND, for a pooled tail,
    as the pool's own aggregate (a tail is not "done" merely because it first reaches an
    individually-adequate neighbor; it must itself reach min_expected, absorbing further inward
    cells - even individually-adequate ones - if it does not). If the two tails meet before both
    reach min_expected, the whole distribution collapses into a single cell. Depends only on the
    null pmf (`units`) and `n_obs`, never on observed data.
    Returns [{'cell','lo','hi','null_prob','expected_count'}]."""
    units_sorted = sorted(units, key=lambda u: u["lo"])
    m = len(units_sorted)
    if m == 0:
        return []

    probs = [u["prob"] for u in units_sorted]
    prefix = [0.0] * (m + 1)
    for i, p in enumerate(probs):
        prefix[i + 1] = prefix[i] + p

    def rng_prob(a: int, b: int) -> float:
        return prefix[b] - prefix[a]

    # Pass 1: individual-cell boundary scan (a lone cell must itself clear the threshold).
    lo_cut = 0
    while lo_cut < m - 1 and probs[lo_cut] * n_obs < min_expected:
        lo_cut += 1
    hi_cut = m - 1
    while hi_cut > lo_cut and probs[hi_cut] * n_obs < min_expected:
        hi_cut -= 1

    # Pass 2: a pooled tail must reach min_expected as a whole, too; absorb further inward
    # (possibly past an individually-adequate cell) until it does, or the tails meet.
    while lo_cut > 0 and rng_prob(0, lo_cut) * n_obs < min_expected and lo_cut < hi_cut:
        lo_cut += 1
    while hi_cut < m - 1 and rng_prob(hi_cut + 1, m) * n_obs < min_expected and hi_cut > lo_cut:
        hi_cut -= 1

    if lo_cut >= hi_cut:
        left_short = lo_cut > 0 and rng_prob(0, lo_cut) * n_obs < min_expected
        right_short = hi_cut < m - 1 and rng_prob(hi_cut + 1, m) * n_obs < min_expected
        if left_short or right_short:
            cells = [{"lo": units_sorted[0]["lo"], "hi": units_sorted[-1]["hi"], "prob": prefix[m], "n_units": m}]
            return _label_cells(cells, n_obs)

    cells = []
    if lo_cut > 0:
        cells.append({"lo": units_sorted[0]["lo"], "hi": units_sorted[lo_cut - 1]["hi"],
                       "prob": rng_prob(0, lo_cut), "n_units": lo_cut})
    for u in units_sorted[lo_cut : hi_cut + 1]:
        cells.append({"lo": u["lo"], "hi": u["hi"], "prob": u["prob"], "n_units": 1})
    if hi_cut < m - 1:
        cells.append({"lo": units_sorted[hi_cut + 1]["lo"], "hi": units_sorted[-1]["hi"],
                       "prob": rng_prob(hi_cut + 1, m), "n_units": m - 1 - hi_cut})

    return _label_cells(cells, n_obs)


def _pmf_to_units(pmf: pd.Series) -> list[dict]:
    return [{"lo": int(v), "hi": int(v), "prob": float(p)} for v, p in pmf.sort_index().items()]


def _sum_bin_units(pmf: pd.Series) -> list[dict]:
    """Fixed width-10 bins 21-30, 31-40, ..., 311-315 (spec section 3.1)."""
    lo_all, hi_all = int(pmf.index.min()), int(pmf.index.max())
    start = (lo_all // 10) * 10 + 1  # 21
    units = []
    b = start
    while b <= hi_all:
        e = min(b + 9, hi_all)
        prob = float(pmf[(pmf.index >= b) & (pmf.index <= e)].sum())
        units.append({"lo": b, "hi": e, "prob": prob})
        b += 10
    return units


def _observed_counts_for_cells(values: np.ndarray, cells: list[dict]) -> tuple[np.ndarray, int]:
    counts = np.array([int(((values >= c["lo"]) & (values <= c["hi"])).sum()) for c in cells])
    return counts, len(values)


def _metric_distribution_rows(metric: str, values: np.ndarray, pmf: pd.Series, n_obs: int,
                               fixed_cells: list[tuple[int, int]] | None = None,
                               sum_binning: bool = False, reference: str = "exact") -> list[dict]:
    """Rows carry an internal `_lo` sort key (dropped before the CSV is written) so the table and
    charts can be ordered numerically: lower pooled tail, then the numeric cells, then the upper
    pooled tail (F2)."""
    if fixed_cells is not None:
        # e.g. consecutive_pairs pools to {0,1,2,>=3} regardless of n*P
        rows = []
        for lo, hi in fixed_cells:
            hi_eff = hi if hi is not None else int(values.max())
            prob = float(pmf[(pmf.index >= lo) & (pmf.index <= hi_eff)].sum()) if hi is not None else float(pmf[pmf.index >= lo].sum())
            label = str(lo) if hi == lo else (f">={lo}" if hi is None else f"{lo}-{hi}")
            obs = int(((values >= lo) & (values <= hi_eff)).sum()) if hi is not None else int((values >= lo).sum())
            null_lo, null_hi = nr.binomial_band(n_obs, prob)
            rows.append({
                "metric": metric, "cell": label, "observed_count": obs,
                "observed_share": obs / n_obs, "null_prob": prob,
                "expected_count": prob * n_obs, "null_lo": null_lo, "null_hi": null_hi,
                "reference": reference, "_lo": lo,
            })
        return rows

    units = _sum_bin_units(pmf) if sum_binning else _pmf_to_units(pmf)
    cells = _pool_cells(units, n_obs)
    counts, _ = _observed_counts_for_cells(values, cells)
    rows = []
    for c, obs in zip(cells, counts):
        null_lo, null_hi = nr.binomial_band(n_obs, c["null_prob"])
        rows.append({
            "metric": metric, "cell": c["cell"], "observed_count": int(obs),
            "observed_share": obs / n_obs, "null_prob": c["null_prob"],
            "expected_count": c["expected_count"], "null_lo": null_lo, "null_hi": null_hi,
            "reference": reference, "_lo": c["lo"],
        })
    return rows


def draw_metric_distribution(metrics_df: pd.DataFrame, n_draws: int) -> pd.DataFrame:
    rows: list[dict] = []
    rows += _metric_distribution_rows("sum", metrics_df["sum"].to_numpy(), nr.sum_pmf(), n_draws, sum_binning=True)
    rows += _metric_distribution_rows("min", metrics_df["min"].to_numpy(), nr.min_pmf(), n_draws)
    rows += _metric_distribution_rows("max", metrics_df["max"].to_numpy(), nr.max_pmf(), n_draws)
    rows += _metric_distribution_rows("range", metrics_df["range"].to_numpy(), nr.range_pmf(), n_draws)
    rows += _metric_distribution_rows("odd_count", metrics_df["odd_count"].to_numpy(), nr.hypergeom_pmf(55, 28, 6), n_draws)
    rows += _metric_distribution_rows("low_count", metrics_df["low_count"].to_numpy(), nr.hypergeom_pmf(55, 27, 6), n_draws)
    rows += _metric_distribution_rows(
        "consecutive_pairs", metrics_df["consecutive_pairs"].to_numpy(), nr.consecutive_pairs_pmf(), n_draws,
        fixed_cells=[(0, 0), (1, 1), (2, 2), (3, None)],
    )
    gap_values = metrics_df[[f"gap_{i}" for i in range(1, 6)]].to_numpy().ravel()
    # F8: the pooled within-draw `gap` metric has an exact pmf/expected count, but its 5
    # spacings per draw are dependent, so its Binomial(5n, P) band is approximate.
    rows += _metric_distribution_rows("gap", gap_values, nr.gap_pmf(), n_draws * 5, reference="exact_pmf_approx_band")
    rows += _metric_distribution_rows("max_gap", metrics_df["max_gap"].to_numpy(), nr.max_gap_pmf(), n_draws)
    rows += _metric_distribution_rows("min_gap", metrics_df["min_gap"].to_numpy(), nr.min_gap_pmf(), n_draws)

    out = pd.DataFrame(rows, columns=["metric", "cell", "observed_count", "observed_share", "null_prob",
                                       "expected_count", "null_lo", "null_hi", "reference", "_lo"])
    order = {"sum": 0, "min": 1, "max": 2, "range": 3, "odd_count": 4, "low_count": 5,
             "consecutive_pairs": 6, "gap": 7, "max_gap": 8, "min_gap": 9}
    out["_o"] = out["metric"].map(order)
    # F2: rows sorted by key (numeric value), not lexicographically by the `cell` label - lower
    # pooled tail first, then the numeric cells in order, then the upper pooled tail.
    out = out.sort_values(["_o", "_lo"], kind="stable").drop(columns=["_o", "_lo"]).reset_index(drop=True)
    return out


def null_pmfs_table() -> pd.DataFrame:
    """Unpooled exact pmfs (null only, no observed data). metric, value, prob."""
    pmfs = {
        "sum": nr.sum_pmf(), "min": nr.min_pmf(), "max": nr.max_pmf(), "range": nr.range_pmf(),
        "odd_count": nr.hypergeom_pmf(55, 28, 6), "low_count": nr.hypergeom_pmf(55, 27, 6),
        "consecutive_pairs": nr.consecutive_pairs_pmf(), "gap": nr.gap_pmf(),
        "max_gap": nr.max_gap_pmf(), "min_gap": nr.min_gap_pmf(),
    }
    rows = []
    for metric, pmf in pmfs.items():
        for v, p in pmf.sort_index().items():
            rows.append({"metric": metric, "value": v, "prob": p})
    return pd.DataFrame(rows, columns=["metric", "value", "prob"])


def _pmf_moments(pmf: pd.Series) -> tuple[float, float]:
    v = pmf.index.to_numpy(dtype=float)
    p = pmf.to_numpy(dtype=float)
    mean = float((v * p).sum())
    var = float(((v - mean) ** 2 * p).sum())
    return mean, math.sqrt(var)


def _pmf_quantile(pmf: pd.Series, q: float) -> float:
    s = pmf.sort_index()
    cdf = s.to_numpy().cumsum()
    idx = np.searchsorted(cdf, q, side="left")
    idx = min(idx, len(s) - 1)
    return float(s.index[idx])


_QUANTILES = [0.05, 0.25, 0.50, 0.75, 0.95]


def draw_metric_summary(metrics_df: pd.DataFrame, n_draws: int) -> pd.DataFrame:
    specs = [
        ("sum", metrics_df["sum"].to_numpy(), nr.sum_pmf()),
        ("min", metrics_df["min"].to_numpy(), nr.min_pmf()),
        ("max", metrics_df["max"].to_numpy(), nr.max_pmf()),
        ("range", metrics_df["range"].to_numpy(), nr.range_pmf()),
        ("odd_count", metrics_df["odd_count"].to_numpy(), nr.hypergeom_pmf(55, 28, 6)),
        ("low_count", metrics_df["low_count"].to_numpy(), nr.hypergeom_pmf(55, 27, 6)),
        ("consecutive_pairs", metrics_df["consecutive_pairs"].to_numpy(), nr.consecutive_pairs_pmf()),
        ("gap", metrics_df[[f"gap_{i}" for i in range(1, 6)]].to_numpy().ravel(), nr.gap_pmf()),
        ("max_gap", metrics_df["max_gap"].to_numpy(), nr.max_gap_pmf()),
        ("min_gap", metrics_df["min_gap"].to_numpy(), nr.min_gap_pmf()),
    ]
    rows = []
    for metric, values, pmf in specs:
        n = len(values)
        null_mean, null_sd = _pmf_moments(pmf)
        row = {
            "metric": metric, "n": n,
            "obs_mean": float(np.mean(values)), "obs_sd": float(np.std(values, ddof=1)) if n > 1 else 0.0,
            "null_mean": null_mean, "null_sd": null_sd,
        }
        for q in _QUANTILES:
            row[f"obs_q{int(q * 100):02d}"] = float(np.quantile(values, q))
            row[f"null_q{int(q * 100):02d}"] = _pmf_quantile(pmf, q)
        rows.append(row)
    cols = ["metric", "n", "obs_mean", "obs_sd"] + [f"obs_q{int(q * 100):02d}" for q in _QUANTILES] + \
           ["null_mean", "null_sd"] + [f"null_q{int(q * 100):02d}" for q in _QUANTILES]
    return pd.DataFrame(rows, columns=cols)


# ---------------------------------------------------------------------------
# N1-N6, S1: number-level metrics
# ---------------------------------------------------------------------------

_DIM_NUMBER = tables.build_dim_number().set_index("number")


def _parity_band(number: int) -> tuple[str, str]:
    row = _DIM_NUMBER.loc[number]
    return row["parity"], row["band"]


def number_frequency(df: pd.DataFrame) -> pd.DataFrame:
    n_draws = len(df)
    main = df[MAIN_COLS].to_numpy(dtype=np.int64)
    counts = np.bincount(main.ravel(), minlength=N_NUMBERS + 1)[1 : N_NUMBERS + 1]
    p = P_NUMBER
    expected = n_draws * p
    sd = math.sqrt(n_draws * p * (1 - p))
    rows = []
    for number in range(1, N_NUMBERS + 1):
        count = int(counts[number - 1])
        parity, band = _parity_band(number)
        wilson_lo, wilson_hi = nr.wilson_ci(count, n_draws)
        null_lo, null_hi = nr.binomial_band(n_draws, p)
        z = (count - expected) / sd if sd > 0 else 0.0
        rows.append({
            "number": number, "parity": parity, "band": band, "count": count, "n_draws": n_draws,
            "rel_freq": count / n_draws, "wilson_lo": wilson_lo, "wilson_hi": wilson_hi,
            "expected": expected, "null_lo": null_lo, "null_hi": null_hi, "z": z,
        })
    return pd.DataFrame(rows)


def _period_labels(dates: pd.Series) -> pd.DataFrame:
    years = dates.dt.year
    quarters = dates.dt.quarter
    return pd.DataFrame({
        "year": years.astype(str),
        "quarter": years.astype(str) + "-Q" + quarters.astype(str),
    })


def _period_partial(period_type: str, period: str, first_date, last_date) -> bool:
    if period_type == "year":
        year = int(period)
        start = pd.Timestamp(year=year, month=1, day=1)
        end = pd.Timestamp(year=year, month=12, day=31)
    else:
        year_s, q_s = period.split("-Q")
        year, q = int(year_s), int(q_s)
        start_month = (q - 1) * 3 + 1
        start = pd.Timestamp(year=year, month=start_month, day=1)
        end = (start + pd.DateOffset(months=3)) - pd.Timedelta(days=1)
    return bool(start < first_date or end > last_date)


def number_frequency_by_period(df: pd.DataFrame) -> pd.DataFrame:
    dates = pd.to_datetime(df["draw_date"])
    first_date, last_date = dates.min(), dates.max()
    labels = _period_labels(dates)
    main = df[MAIN_COLS].to_numpy(dtype=np.int64)
    p = P_NUMBER

    rows = []
    for period_type, col in (("year", "year"), ("quarter", "quarter")):
        periods = labels[col]
        for period, idx in periods.groupby(periods).groups.items():
            mask = periods.index.isin(idx)
            block = main[mask.to_numpy() if hasattr(mask, "to_numpy") else mask]
            n_draws_period = block.shape[0]
            counts = np.bincount(block.ravel(), minlength=N_NUMBERS + 1)[1 : N_NUMBERS + 1]
            partial = _period_partial(period_type, period, first_date, last_date)
            expected = n_draws_period * p
            sd = math.sqrt(n_draws_period * p * (1 - p)) if n_draws_period > 0 else 0.0
            null_lo, null_hi = nr.binomial_band(n_draws_period, p) if n_draws_period > 0 else (0.0, 0.0)
            for number in range(1, N_NUMBERS + 1):
                count = int(counts[number - 1])
                z = (count - expected) / sd if sd > 0 else 0.0
                rows.append({
                    "period_type": period_type, "period": period, "partial": partial,
                    "number": number, "count": count, "n_draws": n_draws_period,
                    "expected": expected, "null_lo": null_lo, "null_hi": null_hi, "z": z,
                })
    out = pd.DataFrame(rows)
    return out.sort_values(["period_type", "period", "number"]).reset_index(drop=True)


def rolling_number_counts(df: pd.DataFrame, window: int) -> pd.DataFrame:
    n_draws = len(df)
    main = df[MAIN_COLS].to_numpy(dtype=np.int64)
    draw_ids = df["draw_id"].to_numpy()
    p = P_NUMBER
    expected = window * p
    sd = math.sqrt(window * p * (1 - p))
    null_lo, null_hi = nr.binomial_band(window, p)

    # cumulative per-number counts, cum[t] = counts through row t (0-indexed row t-1)
    per_row = np.zeros((n_draws, N_NUMBERS + 1), dtype=np.int64)
    for i in range(6):
        np.add.at(per_row, (np.arange(n_draws), main[:, i]), 1)
    cum = np.cumsum(per_row, axis=0)

    rows = []
    for t in range(window, n_draws + 1):  # t is 1-indexed ordinal (window_end)
        start_cum = cum[t - window - 1] if t - window - 1 >= 0 else np.zeros(N_NUMBERS + 1, dtype=np.int64)
        window_counts = cum[t - 1] - start_cum
        draw_id = draw_ids[t - 1]
        for number in range(1, N_NUMBERS + 1):
            count = int(window_counts[number])
            z = (count - expected) / sd if sd > 0 else 0.0
            rows.append({
                "window_end_draw_id": draw_id, "number": number, "count": count,
                "expected": expected, "null_lo": null_lo, "null_hi": null_hi, "z": z,
            })
    return pd.DataFrame(rows)


def rolling_number_extremes(rolling_df: pd.DataFrame) -> pd.DataFrame:
    grouped = rolling_df.groupby("window_end_draw_id")["z"].agg(["max", "min"]).reset_index()
    grouped = grouped.rename(columns={"max": "max_z", "min": "min_z"})
    return grouped.sort_values("window_end_draw_id").reset_index(drop=True)


def interarrival_gaps(df: pd.DataFrame) -> pd.DataFrame:
    n_draws = len(df)
    main = df[MAIN_COLS].to_numpy(dtype=np.int64)
    t = np.arange(1, n_draws + 1)

    all_gaps: list[int] = []
    for number in range(1, N_NUMBERS + 1):
        present = (main == number).any(axis=1)
        ords = t[present]
        if len(ords) >= 2:
            all_gaps.extend(np.diff(ords).tolist())
    gaps_arr = np.array(all_gaps, dtype=np.int64)

    p = P_NUMBER
    g_support = np.arange(1, n_draws)
    E = N_NUMBERS * (n_draws - g_support) * p**2 * (1 - p) ** (g_support - 1)
    E_series = pd.Series(E, index=g_support)
    total_E = float(E_series.sum())

    positive = E_series[E_series >= MIN_EXPECTED]
    g0 = int(positive.index.max()) if len(positive) else 0

    rows = []
    if g0 == 0:
        # nothing meets the threshold; single pooled cell
        obs = int((gaps_arr >= 1).sum())
        rows.append({"cell": ">=1", "observed_count": obs, "expected_count": total_E, "null_share": 1.0 if total_E > 0 else 0.0})
        return pd.DataFrame(rows)

    tail_E = float(E_series[E_series.index > g0].sum())
    tail_obs = int((gaps_arr > g0).sum())

    if tail_E < MIN_EXPECTED and tail_E > 0:
        # merge tail into g0
        for g in range(1, g0):
            obs = int((gaps_arr == g).sum())
            e = float(E_series.loc[g])
            rows.append({"cell": str(g), "observed_count": obs, "expected_count": e, "null_share": e / total_E})
        merged_e = float(E_series.loc[g0]) + tail_E
        merged_obs = int((gaps_arr == g0).sum()) + tail_obs
        rows.append({"cell": f">={g0}", "observed_count": merged_obs, "expected_count": merged_e, "null_share": merged_e / total_E})
    else:
        for g in range(1, g0 + 1):
            obs = int((gaps_arr == g).sum())
            e = float(E_series.loc[g])
            rows.append({"cell": str(g), "observed_count": obs, "expected_count": e, "null_share": e / total_E})
        if tail_E > 0:
            rows.append({"cell": f">={g0 + 1}", "observed_count": tail_obs, "expected_count": tail_E, "null_share": tail_E / total_E})
    return pd.DataFrame(rows)


def appearance_summary(df: pd.DataFrame) -> pd.DataFrame:
    n_draws = len(df)
    main = df[MAIN_COLS].to_numpy(dtype=np.int64)
    draw_ids = df["draw_id"].to_numpy()
    t = np.arange(1, n_draws + 1)

    rows = []
    for number in range(1, N_NUMBERS + 1):
        present = (main == number).any(axis=1)
        ords = t[present]
        if len(ords) == 0:
            rows.append({
                "number": number, "first_draw_id": None, "last_draw_id": None, "n_gaps": 0,
                "mean_gap": None, "sd_gap": None,
                "approx_expected_mean_gap": APPROX_EXPECTED_MEAN_GAP, "approx_expected_sd_gap": APPROX_EXPECTED_SD_GAP,
            })
            continue
        first_draw_id = draw_ids[ords[0] - 1]
        last_draw_id = draw_ids[ords[-1] - 1]
        if len(ords) >= 2:
            gaps = np.diff(ords)
            mean_gap = float(gaps.mean())
            sd_gap = float(gaps.std(ddof=1)) if len(gaps) > 1 else None
        else:
            gaps = np.array([])
            mean_gap = None
            sd_gap = None
        rows.append({
            "number": number, "first_draw_id": first_draw_id, "last_draw_id": last_draw_id,
            "n_gaps": len(gaps), "mean_gap": mean_gap, "sd_gap": sd_gap,
            "approx_expected_mean_gap": APPROX_EXPECTED_MEAN_GAP, "approx_expected_sd_gap": APPROX_EXPECTED_SD_GAP,
        })
    return pd.DataFrame(rows)


def cumulative_counts(df: pd.DataFrame) -> pd.DataFrame:
    n_draws = len(df)
    main = df[MAIN_COLS].to_numpy(dtype=np.int64)
    draw_ids = df["draw_id"].to_numpy()
    p = P_NUMBER

    per_row = np.zeros((n_draws, N_NUMBERS + 1), dtype=np.int64)
    for i in range(6):
        np.add.at(per_row, (np.arange(n_draws), main[:, i]), 1)
    cum = np.cumsum(per_row, axis=0)

    rows = []
    for row_idx in range(n_draws):
        t = row_idx + 1
        draw_id = draw_ids[row_idx]
        expected = t * p
        null_lo, null_hi = nr.binomial_band(t, p)
        for number in range(1, N_NUMBERS + 1):
            rows.append({
                "draw_id": draw_id, "number": number, "cumulative_count": int(cum[row_idx, number]),
                "expected": expected, "null_lo": null_lo, "null_hi": null_hi,
            })
    return pd.DataFrame(rows)


def special_frequency(df: pd.DataFrame) -> pd.DataFrame:
    non_missing = df["special_number"].notna()
    n_nonmissing = int(non_missing.sum())
    n_missing = int((~non_missing).sum())
    special = df.loc[non_missing, "special_number"].astype(np.int64).to_numpy()
    counts = np.bincount(special, minlength=N_NUMBERS + 1)[1 : N_NUMBERS + 1] if n_nonmissing > 0 else np.zeros(N_NUMBERS, dtype=np.int64)
    p = 1 / N_NUMBERS
    expected = n_nonmissing * p
    sd = math.sqrt(n_nonmissing * p * (1 - p)) if n_nonmissing > 0 else 0.0
    null_lo, null_hi = nr.binomial_band(n_nonmissing, p) if n_nonmissing > 0 else (0.0, 0.0)

    rows = []
    for number in range(1, N_NUMBERS + 1):
        count = int(counts[number - 1])
        parity, band = _parity_band(number)
        wilson_lo, wilson_hi = nr.wilson_ci(count, n_nonmissing) if n_nonmissing > 0 else (0.0, 0.0)
        z = (count - expected) / sd if sd > 0 else 0.0
        rows.append({
            "number": number, "parity": parity, "band": band, "count": count, "n_draws": n_nonmissing,
            "rel_freq": count / n_nonmissing if n_nonmissing > 0 else 0.0,
            "wilson_lo": wilson_lo, "wilson_hi": wilson_hi, "expected": expected,
            "null_lo": null_lo, "null_hi": null_hi, "z": z,
            "n_nonmissing": n_nonmissing, "n_missing_special": n_missing,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# P1/P2: pair-level metrics
# ---------------------------------------------------------------------------

def pair_cooccurrence(df: pd.DataFrame) -> pd.DataFrame:
    n_draws = len(df)
    main = df[MAIN_COLS].to_numpy(dtype=np.int64)
    mat = np.zeros((N_NUMBERS + 1, N_NUMBERS + 1), dtype=np.int64)
    idx_i, idx_j = np.triu_indices(6, k=1)
    pi = main[:, idx_i]
    pj = main[:, idx_j]
    np.add.at(mat, (pi.ravel(), pj.ravel()), 1)

    p = Q_PAIR
    expected = n_draws * p
    sd = math.sqrt(n_draws * p * (1 - p))
    null_lo, null_hi = nr.binomial_band(n_draws, p)

    rows = []
    for i in range(1, N_NUMBERS + 1):
        for j in range(i + 1, N_NUMBERS + 1):
            count = int(mat[i, j])
            z = (count - expected) / sd if sd > 0 else 0.0
            rows.append({
                "number_i": i, "number_j": j, "count": count, "expected": expected,
                "null_lo": null_lo, "null_hi": null_hi, "z": z,
            })
    return pd.DataFrame(rows)


def pair_count_distribution(pair_df: pd.DataFrame, n_draws: int) -> pd.DataFrame:
    from scipy.stats import binom
    counts = pair_df["count"].to_numpy()
    lo, hi = int(counts.min()), int(counts.max())
    rows = []
    for c in range(lo, hi + 1):
        observed_pairs = int((counts == c).sum())
        null_prob = float(binom.pmf(c, n_draws, Q_PAIR))
        rows.append({"count": c, "observed_pairs": observed_pairs, "null_prob": null_prob, "expected_pairs": null_prob * 1485})
    return pd.DataFrame(rows)


def block_stability(df: pd.DataFrame, n_blocks: int) -> pd.DataFrame:
    n_draws = len(df)
    main = df[MAIN_COLS].to_numpy(dtype=np.int64)
    draw_ids = df["draw_id"].to_numpy()
    block_ranges = np.array_split(np.arange(n_draws), n_blocks)

    def number_vec(idx):
        block = main[idx]
        counts = np.bincount(block.ravel(), minlength=N_NUMBERS + 1)
        return counts[1 : N_NUMBERS + 1]

    def pair_vec(idx):
        block = main[idx]
        mat = np.zeros((N_NUMBERS + 1, N_NUMBERS + 1), dtype=np.int64)
        idx_i, idx_j = np.triu_indices(6, k=1)
        pi = block[:, idx_i]
        pj = block[:, idx_j]
        np.add.at(mat, (pi.ravel(), pj.ravel()), 1)
        sub = mat[1 : N_NUMBERS + 1, 1 : N_NUMBERS + 1]
        return sub[np.triu_indices(N_NUMBERS, k=1)]

    def pearson(x, y):
        x = x.astype(float)
        y = y.astype(float)
        xm, ym = x - x.mean(), y - y.mean()
        denom = math.sqrt((xm**2).sum() * (ym**2).sum())
        return float((xm * ym).sum() / denom) if denom > 0 else float("nan")

    number_vecs = [number_vec(idx) for idx in block_ranges]
    pair_vecs = [pair_vec(idx) for idx in block_ranges]

    rows = []
    for a in range(n_blocks):
        for b in range(a + 1, n_blocks):
            idx_a, idx_b = block_ranges[a], block_ranges[b]
            first_a, last_a = draw_ids[idx_a[0]], draw_ids[idx_a[-1]]
            first_b, last_b = draw_ids[idx_b[0]], draw_ids[idx_b[-1]]
            r_number = pearson(number_vecs[a], number_vecs[b])
            r_pair = pearson(pair_vecs[a], pair_vecs[b])
            rows.append({
                "level": "number", "block_a": a, "block_b": b,
                "first_draw_id_a": first_a, "last_draw_id_a": last_a,
                "first_draw_id_b": first_b, "last_draw_id_b": last_b,
                "pearson_r": r_number,
            })
            rows.append({
                "level": "pair", "block_a": a, "block_b": b,
                "first_draw_id_a": first_a, "last_draw_id_a": last_a,
                "first_draw_id_b": first_b, "last_draw_id_b": last_b,
                "pearson_r": r_pair,
            })
    return pd.DataFrame(rows)
