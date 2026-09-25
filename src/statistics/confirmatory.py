"""M4 confirmatory family C1-C13 (`docs/SPECIFICATION.md` v1.2.1 section 6).

Pure functions only: ndarray/DataFrame in, dict/DataFrame out. No I/O, no globals mutated.
Reuses `src/statistics/null_model.py` (whole-draw simulator, seeded RNG streams) and
`src/statistics/null_reference.py` (exact pmfs) from the M3 EDA design.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.stats import binomtest

from src.statistics import null_model
from src.statistics import null_reference as nr

N_NUMBERS = 55
K_MAIN = 6
SEED = 20260924
R_DEFAULT = 10_000
R_ESCALATE = 100_000
STREAM_FRESH = 101
STREAM_PERM = 102
STREAM_FRESH_ESCALATE = 1101
STREAM_PERM_ESCALATE = 1102
ROLL_W = 170
ROLL_STEP = 85
LAGS = tuple(range(1, 11))
OVERLAP_MEAN = 36 / 55
OVERLAP_VAR = 6 * (6 / 55) * (49 / 55) * (49 / 54)  # 0.529146...
MEDIAN_SUM = 168
ESCALATE_LO = 0.04
ESCALATE_HI = 0.06

_CHUNK = 200  # replicate datasets per generation chunk
MIN_CELL_EXPECTED = 5.0  # section 6.2 cell-pooling rule: n*P >= 5


# ---------------------------------------------------------------------------
# Section 6.1: simulated p, Holm
# ---------------------------------------------------------------------------

def simulated_p(t_obs: float, t_reps: np.ndarray) -> float:
    """(1 + #{r : T_r >= T_obs}) / (R + 1). Never returns 0."""
    r = np.asarray(t_reps, dtype=float)
    R = len(r)
    return (1 + int(np.sum(r >= t_obs))) / (R + 1)


def holm(pvalues: list[float]) -> list[float]:
    """Holm-adjusted p-values. Adjusted p for sorted p_(i) is max_{j<=i} min(1, (m-j+1)*p_(j))."""
    p = np.asarray(pvalues, dtype=float)
    m = len(p)
    if m == 0:
        return []
    order = np.argsort(p, kind="stable")
    sorted_p = p[order]
    adj_sorted = np.empty(m)
    running_max = 0.0
    for i in range(m):
        val = min(1.0, (m - i) * sorted_p[i])
        running_max = max(running_max, val)
        adj_sorted[i] = running_max
    adj = np.empty(m)
    adj[order] = adj_sorted
    return adj.tolist()


# ---------------------------------------------------------------------------
# Observed-data feature extraction
# ---------------------------------------------------------------------------

@dataclass
class ObservedData:
    main: np.ndarray  # (n, 6) int, 1..55, ascending
    special: np.ndarray  # (n',) int, 1..55, non-missing only, in draw order
    special_present: np.ndarray  # (n,) bool, aligned with `main`: True where special is non-missing
    n: int
    n_prime: int
    year_group_sizes: list[int]
    year_labels: list[str]


def _indicator(main: np.ndarray, N: int = N_NUMBERS) -> np.ndarray:
    """(n, N) 0/1 matrix: row t, col k-1 = 1 if k in draw t."""
    n = main.shape[0]
    I = np.zeros((n, N), dtype=np.int16)
    rows = np.repeat(np.arange(n), main.shape[1])
    cols = (main - 1).ravel()
    I[rows, cols] = 1
    return I


def build_observed(df: pd.DataFrame, main_cols: list[str]) -> ObservedData:
    main = df[main_cols].to_numpy(dtype=np.int64)
    special_all = df["special_number"]
    special_present = special_all.notna().to_numpy()
    special = special_all[special_all.notna()].to_numpy(dtype=np.int64)
    dates = pd.to_datetime(df["draw_date"])
    years_int = dates.dt.year.to_numpy()
    # C7/C8 require contiguous per-year blocks in draw order (n7 fix: the real, informative check
    # is that the calendar year is non-decreasing over t; a sum-of-group-sizes check is vacuous,
    # since group sizes are counted directly from the year labels and always sum to n).
    if not np.all(np.diff(years_int) >= 0):
        raise ValueError("draw years are not non-decreasing in draw order; C7/C8 year grouping requires contiguous per-year blocks")
    years = pd.Series(years_int.astype(str))
    # contiguous blocks by calendar year, in chronological order (draws are sorted by draw_id/date)
    year_labels: list[str] = []
    year_group_sizes: list[int] = []
    for y, grp in years.groupby(years, sort=False):
        year_labels.append(y)
        year_group_sizes.append(len(grp))
    # groupby(sort=False) preserves first-seen order, which is chronological here; sort by label
    # to be explicit and deterministic (years are monotonic over t, so this is a no-op re-check).
    order = np.argsort(year_labels)
    year_labels = [year_labels[i] for i in order]
    year_group_sizes = [year_group_sizes[i] for i in order]
    return ObservedData(
        main=main, special=special, special_present=special_present, n=len(df), n_prime=len(special),
        year_group_sizes=year_group_sizes, year_labels=year_labels,
    )


def rolling_windows(n: int, w: int = ROLL_W, step: int = ROLL_STEP) -> list[tuple[int, int]]:
    """0-indexed half-open [start, end) windows of width w, step `step`, from ordinal 1."""
    windows = []
    start = 0
    while start + w <= n:
        windows.append((start, start + w))
        start += step
    return windows


# ---------------------------------------------------------------------------
# Per-replicate statistic bundles (shared by observed data and both null generators)
# ---------------------------------------------------------------------------

@dataclass
class MainStats:
    I: np.ndarray  # (n, 55)
    f: np.ndarray  # (55,)
    sum_t: np.ndarray
    range_t: np.ndarray
    odd_t: np.ndarray
    low_t: np.ndarray
    consec_t: np.ndarray


def main_stats(main: np.ndarray, N: int = N_NUMBERS) -> MainStats:
    I = _indicator(main, N)
    f = I.sum(axis=0)
    sum_t = main.sum(axis=1)
    range_t = main[:, -1] - main[:, 0]
    odd_t = (main % 2 == 1).sum(axis=1)
    low_t = (main <= 27).sum(axis=1)
    consec_t = (np.diff(main, axis=1) == 1).sum(axis=1)
    return MainStats(I=I, f=f, sum_t=sum_t, range_t=range_t, odd_t=odd_t, low_t=low_t, consec_t=consec_t)


def overlap_means(I: np.ndarray, lags=LAGS) -> dict[int, float]:
    n = I.shape[0]
    out = {}
    for j in lags:
        if j >= n:
            out[j] = float("nan")
            continue
        ov = (I[j:] * I[:-j]).sum(axis=1)
        out[j] = float(ov.mean())
    return out


def ljung_box(y: np.ndarray, H: int = 10) -> tuple[float, np.ndarray]:
    n = len(y)
    yc = y - y.mean()
    denom = float((yc**2).sum())
    r = np.array([float((yc[h:] * yc[:-h]).sum()) / denom for h in range(1, H + 1)])
    hs = np.arange(1, H + 1)
    Q = n * (n + 2) * float(np.sum(r**2 / (n - hs)))
    return Q, r


def runs_stat(y: np.ndarray, median: int = MEDIAN_SUM) -> dict:
    mask = y != median
    a = (y[mask] > median).astype(int)
    n_ties = int((~mask).sum())
    m = len(a)
    if m == 0:
        return {"T": float("nan"), "runs": 0, "mu": float("nan"), "n_plus": 0, "n_minus": 0, "n_ties": n_ties}
    runs = 1 + int(np.sum(a[1:] != a[:-1]))
    n_plus = int(a.sum())
    n_minus = m - n_plus
    if n_plus == 0 or n_minus == 0:
        mu = float("nan")
        T = float("nan")
    else:
        mu = 1 + 2 * n_plus * n_minus / (n_plus + n_minus)
        T = abs(runs - mu)
    return {"T": T, "runs": runs, "mu": mu, "n_plus": n_plus, "n_minus": n_minus, "n_ties": n_ties}


def ks_D(values: np.ndarray, support_lo: int, support_hi: int, cdf0: np.ndarray) -> float:
    """cdf0: array of F0(s) for s = support_lo..support_hi inclusive."""
    n = len(values)
    sorted_v = np.sort(values)
    s_grid = np.arange(support_lo, support_hi + 1)
    ecdf = np.searchsorted(sorted_v, s_grid, side="right") / n
    return float(np.max(np.abs(ecdf - cdf0)))


def pearson_cells(counts: np.ndarray, null_p: np.ndarray, n: int) -> tuple[float, np.ndarray, np.ndarray]:
    """counts: observed cell counts. null_p: cell probabilities (same order). Returns (X2, O, E)."""
    E = null_p * n
    X2 = float(np.sum((counts - E) ** 2 / E))
    return X2, counts.astype(float), E


def year_group_x2(I: np.ndarray, f_ref: np.ndarray, n: int, group_sizes: list[int]) -> tuple[float, list[float]]:
    idx = 0
    contributions = []
    for ng in group_sizes:
        Og = I[idx: idx + ng].sum(axis=0).astype(float)
        Eg = ng * f_ref / n
        contributions.append(float(np.sum((Og - Eg) ** 2 / Eg)))
        idx += ng
    return float(sum(contributions)), contributions


def rolling_x2(I: np.ndarray, f_ref: np.ndarray, n: int, windows: list[tuple[int, int]]) -> list[float]:
    out = []
    for s, e in windows:
        w = e - s
        Ow = I[s:e].sum(axis=0).astype(float)
        Ew = w * f_ref / n
        out.append(float(np.sum((Ow - Ew) ** 2 / Ew)))
    return out


def pooled_cells(pmf: pd.Series, n: int, min_expected: float = MIN_CELL_EXPECTED) -> list[tuple[str, int, int, float]]:
    """Section 6.2 cell-pooling rule, decided from null probabilities and n only (never from
    observed counts): merge tail cells inward, each tail separately, until every cell has null
    expected count n*P >= min_expected. Applies to C11-C13 alike (a general rule; at n=1190 it
    happens to reproduce the odd/low singleton cells and the consecutive-pairs {0,1,2,>=3} cells
    shown in SPECIFICATION section 6.2's table, since those are themselves instances of this rule).
    Returns (label, lo, hi, prob) in ascending value order; lo..hi are inclusive and contiguous
    across the whole original support."""
    values = list(pmf.index)
    probs = list(pmf.to_numpy(dtype=float))
    cells = [[int(v), int(v), p] for v, p in zip(values, probs)]  # [lo, hi, prob]

    while len(cells) > 1 and cells[0][2] * n < min_expected:
        cells[1][0] = cells[0][0]
        cells[1][2] += cells[0][2]
        cells.pop(0)
    while len(cells) > 1 and cells[-1][2] * n < min_expected:
        cells[-2][1] = cells[-1][1]
        cells[-2][2] += cells[-1][2]
        cells.pop()

    out: list[tuple[str, int, int, float]] = []
    for i, (lo, hi, p) in enumerate(cells):
        if lo == hi:
            label = str(lo)
        elif i == 0:
            label = f"<={hi}"
        elif i == len(cells) - 1:
            label = f">={lo}"
        else:
            label = f"{lo}-{hi}"  # not expected for single-tail-at-a-time pooling, kept for safety
        out.append((label, lo, hi, p))
    return out


def cell_index_lookup(cells: list[tuple[str, int, int, float]], support_lo: int, support_hi: int) -> np.ndarray:
    """lookup[v - support_lo] = index into `cells` that v falls into, for v = support_lo..support_hi."""
    lookup = np.empty(support_hi - support_lo + 1, dtype=np.int64)
    for i, (_label, lo, hi, _p) in enumerate(cells):
        lookup[lo - support_lo: hi - support_lo + 1] = i
    return lookup


def bucket_counts(values: np.ndarray, lookup: np.ndarray, support_lo: int, n_cells: int) -> np.ndarray:
    idx = lookup[values - support_lo]
    return np.bincount(idx, minlength=n_cells).astype(float)


# ---------------------------------------------------------------------------
# FRESH replicate generation (streamed, chunked; chunk-size invariant)
# ---------------------------------------------------------------------------

def _fresh_chunks(n: int, n_prime: int, R: int, seed: int, stream_id: int, chunk_size: int = _CHUNK):
    rng = null_model.rng_for(stream_id, seed)
    remaining = R
    while remaining > 0:
        c = min(chunk_size, remaining)
        row_chunk = min(c * n, 200_000)
        main_flat, special_flat = null_model.simulate_draws(c * n, rng, chunk_size=row_chunk)
        main_chunk = main_flat.reshape(c, n, K_MAIN)
        special_chunk = special_flat.reshape(c, n)[:, :n_prime]
        yield main_chunk, special_chunk
        remaining -= c


def _perm_chunks(main: np.ndarray, R: int, seed: int, stream_id: int, chunk_size: int = _CHUNK):
    """R permutations of the real draw order (whole draws moved). Chunk-size invariant: the RNG
    stream is consumed one permutation at a time regardless of the outer chunk grouping."""
    n = main.shape[0]
    rng = null_model.rng_for(stream_id, seed)
    remaining = R
    while remaining > 0:
        c = min(chunk_size, remaining)
        perms = np.empty((c, n), dtype=np.int64)
        for i in range(c):
            perms[i] = rng.permutation(n)
        yield perms
        remaining -= c


# ---------------------------------------------------------------------------
# Sum / range null references (exact CDFs, cached at import for N=55,k=6)
# ---------------------------------------------------------------------------

def _cdf_from_pmf(pmf: pd.Series, lo: int, hi: int) -> np.ndarray:
    full = pd.Series(0.0, index=range(lo, hi + 1))
    full.update(pmf)
    return full.sort_index().cumsum().to_numpy()


SUM_SUPPORT = (21, 315)
RANGE_SUPPORT = (5, 54)


def _sum_cdf() -> np.ndarray:
    return _cdf_from_pmf(nr.sum_pmf(N_NUMBERS, K_MAIN), *SUM_SUPPORT)


def _range_cdf() -> np.ndarray:
    return _cdf_from_pmf(nr.range_pmf(N_NUMBERS, K_MAIN), *RANGE_SUPPORT)


# ---------------------------------------------------------------------------
# Main confirmatory run
# ---------------------------------------------------------------------------

@dataclass
class TestResult:
    id: str
    hypothesis: str
    statistic: float
    null: str
    R: int
    stream: int
    p_sim: float
    effect: dict = field(default_factory=dict)
    n: int = 0
    N: int = 0  # 6n (section 6.2's N = 6n; recorded for every row, directly used by C7/C8)
    replicate_mean: float = float("nan")


@dataclass
class ConfirmatoryRun:
    n: int
    n_prime: int
    R: int
    seed: int
    streams: dict
    family: list[TestResult]
    followups: dict[str, pd.DataFrame]
    exploratory: dict


def run_family(
    obs: ObservedData,
    R: int = R_DEFAULT,
    seed: int = SEED,
    fresh_stream: int = STREAM_FRESH,
    perm_stream: int = STREAM_PERM,
    year_G: int | None = None,
) -> ConfirmatoryRun:
    n, n_prime = obs.n, obs.n_prime
    p_num = K_MAIN / N_NUMBERS
    e_main = n * p_num  # 6n/55
    e_spec = n_prime / N_NUMBERS

    ms_obs = main_stats(obs.main)
    special_obs_counts = np.bincount(obs.special, minlength=N_NUMBERS + 1)[1:]

    # observed statistics --------------------------------------------------
    X2_main_obs = float(np.sum((ms_obs.f - e_main) ** 2 / e_main))
    X2_spec_obs = float(np.sum((special_obs_counts - e_spec) ** 2 / e_spec))

    overlap_obs = overlap_means(ms_obs.I)
    Z_obs = {j: (overlap_obs[j] - OVERLAP_MEAN) / math.sqrt(OVERLAP_VAR / (n - j)) for j in LAGS}
    T_C3_obs = float(sum(Z_obs[j] ** 2 for j in LAGS))

    Q_obs, r_obs = ljung_box(ms_obs.sum_t.astype(float), H=10)

    runs_obs = runs_stat(ms_obs.sum_t)

    year_G = year_G if year_G is not None else len(obs.year_group_sizes)
    X2_C7_obs, contrib_C7_obs = year_group_x2(ms_obs.I, ms_obs.f.astype(float), n, obs.year_group_sizes)

    windows = rolling_windows(n)
    x2w_obs = rolling_x2(ms_obs.I, ms_obs.f.astype(float), n, windows)
    T_C8_obs = float(max(x2w_obs)) if x2w_obs else float("nan")

    cdf0_sum = _sum_cdf()
    D_C9_obs = ks_D(ms_obs.sum_t, *SUM_SUPPORT, cdf0_sum)
    cdf0_range = _range_cdf()
    D_C10_obs = ks_D(ms_obs.range_t, *RANGE_SUPPORT, cdf0_range)

    # m4/m6: cells pooled from the exact null pmf and n (section 6.2), not hardcoded; at n=1190
    # this reproduces the odd/low singleton cells and the consecutive-pairs {0,1,2,>=3} cells
    # (from the exact pmf, not the 6-decimal-rounded constants used previously).
    odd_pmf = nr.hypergeom_pmf(N_NUMBERS, 28, K_MAIN)
    odd_cells = pooled_cells(odd_pmf, n)
    odd_lookup = cell_index_lookup(odd_cells, 0, 6)
    odd_p = np.array([c[3] for c in odd_cells])
    odd_obs_counts = bucket_counts(ms_obs.odd_t, odd_lookup, 0, len(odd_cells))
    X2_C11_obs, O_C11_obs, E_C11_obs = pearson_cells(odd_obs_counts, odd_p, n)

    low_pmf = nr.hypergeom_pmf(N_NUMBERS, 27, K_MAIN)
    low_cells = pooled_cells(low_pmf, n)
    low_lookup = cell_index_lookup(low_cells, 0, 6)
    low_p = np.array([c[3] for c in low_cells])
    low_obs_counts = bucket_counts(ms_obs.low_t, low_lookup, 0, len(low_cells))
    X2_C12_obs, O_C12_obs, E_C12_obs = pearson_cells(low_obs_counts, low_p, n)

    consec_pmf = nr.consecutive_pairs_pmf(N_NUMBERS, K_MAIN)
    consec_cells = pooled_cells(consec_pmf, n)
    consec_lookup = cell_index_lookup(consec_cells, 0, K_MAIN - 1)
    c13_p = np.array([c[3] for c in consec_cells])
    consec_obs_counts = bucket_counts(ms_obs.consec_t, consec_lookup, 0, len(consec_cells))
    X2_C13_obs, O_C13_obs, E_C13_obs = pearson_cells(consec_obs_counts, c13_p, n)

    # replicate accumulators (FRESH) ---------------------------------------
    r_X2_main, r_X2_spec = [], []
    r_T_C3, r_Z = [], {j: [] for j in LAGS}
    r_Q, r_r = [], {h: [] for h in range(1, 11)}
    r_T_C6 = []
    r_D_C9, r_D_C10 = [], []
    r_X2_C11, r_O_C11 = [], []
    r_X2_C12, r_O_C12 = [], []
    r_X2_C13, r_O_C13 = [], []

    for main_chunk, special_chunk in _fresh_chunks(n, n_prime, R, seed, fresh_stream):
        c = main_chunk.shape[0]
        for i in range(c):
            ms = main_stats(main_chunk[i])
            r_X2_main.append(float(np.sum((ms.f - e_main) ** 2 / e_main)))

            s_counts = np.bincount(special_chunk[i], minlength=N_NUMBERS + 1)[1:]
            r_X2_spec.append(float(np.sum((s_counts - e_spec) ** 2 / e_spec)))

            ov = overlap_means(ms.I)
            Z = {j: (ov[j] - OVERLAP_MEAN) / math.sqrt(OVERLAP_VAR / (n - j)) for j in LAGS}
            r_T_C3.append(float(sum(Z[j] ** 2 for j in LAGS)))
            for j in LAGS:
                r_Z[j].append(abs(Z[j]))

            Q, r_vec = ljung_box(ms.sum_t.astype(float), H=10)
            r_Q.append(Q)
            for h in range(1, 11):
                r_r[h].append(abs(r_vec[h - 1]))

            rs = runs_stat(ms.sum_t)
            r_T_C6.append(rs["T"])

            r_D_C9.append(ks_D(ms.sum_t, *SUM_SUPPORT, cdf0_sum))
            r_D_C10.append(ks_D(ms.range_t, *RANGE_SUPPORT, cdf0_range))

            oc = bucket_counts(ms.odd_t, odd_lookup, 0, len(odd_cells))
            X2o, Oo, _ = pearson_cells(oc, odd_p, n)
            r_X2_C11.append(X2o)
            r_O_C11.append(Oo)

            lc = bucket_counts(ms.low_t, low_lookup, 0, len(low_cells))
            X2l, Ol, _ = pearson_cells(lc, low_p, n)
            r_X2_C12.append(X2l)
            r_O_C12.append(Ol)

            cc = bucket_counts(ms.consec_t, consec_lookup, 0, len(consec_cells))
            X2c, Oc, _ = pearson_cells(cc, c13_p, n)
            r_X2_C13.append(X2c)
            r_O_C13.append(Oc)

    r_X2_main = np.array(r_X2_main)
    r_X2_spec = np.array(r_X2_spec)
    r_T_C3 = np.array(r_T_C3)
    r_Q = np.array(r_Q)
    r_T_C6 = np.array(r_T_C6)
    r_D_C9 = np.array(r_D_C9)
    r_D_C10 = np.array(r_D_C10)
    r_X2_C11 = np.array(r_X2_C11)
    r_X2_C12 = np.array(r_X2_C12)
    r_X2_C13 = np.array(r_X2_C13)
    r_O_C11 = np.array(r_O_C11)  # (R, 7)
    r_O_C12 = np.array(r_O_C12)
    r_O_C13 = np.array(r_O_C13)  # (R, 4)

    # replicate accumulators (PERM) -----------------------------------------
    r_T_C4, r_Zstar = [], {j: [] for j in LAGS}
    r_X2_C7, r_contrib_C7 = [], {g: [] for g in range(len(obs.year_group_sizes))}
    r_T_C8, r_x2w = [], {w: [] for w in range(len(windows))}
    overlap_perm_all = {j: [] for j in LAGS}

    for perms in _perm_chunks(obs.main, R, seed, perm_stream):
        for i in range(perms.shape[0]):
            idx = perms[i]
            I_perm = ms_obs.I[idx]
            ov = overlap_means(I_perm)
            for j in LAGS:
                overlap_perm_all[j].append(ov[j])

            X2g, contrib = year_group_x2(I_perm, ms_obs.f.astype(float), n, obs.year_group_sizes)
            r_X2_C7.append(X2g)
            for gi, c_val in enumerate(contrib):
                r_contrib_C7[gi].append(c_val)

            x2w = rolling_x2(I_perm, ms_obs.f.astype(float), n, windows)
            r_T_C8.append(float(max(x2w)) if x2w else float("nan"))
            for wi, val in enumerate(x2w):
                r_x2w[wi].append(val)

    overlap_perm_mean = {j: float(np.mean(overlap_perm_all[j])) for j in LAGS}
    overlap_perm_sd = {j: float(np.std(overlap_perm_all[j], ddof=0)) for j in LAGS}
    # T_C4 replicate values: recompute Z* using the PERM mean/sd derived from this same sample.
    for j in LAGS:
        arr = np.array(overlap_perm_all[j])
        sd = overlap_perm_sd[j] if overlap_perm_sd[j] > 0 else float("nan")
        z = (arr - overlap_perm_mean[j]) / sd
        r_Zstar[j] = np.abs(z)
    r_T_C4 = np.zeros(R)
    for j in LAGS:
        r_T_C4 += r_Zstar[j] ** 2

    Z_obs_perm = {j: (overlap_obs[j] - overlap_perm_mean[j]) / (overlap_perm_sd[j] if overlap_perm_sd[j] > 0 else float("nan")) for j in LAGS}
    T_C4_obs = float(sum(Z_obs_perm[j] ** 2 for j in LAGS))

    r_X2_C7 = np.array(r_X2_C7)
    r_T_C8 = np.array(r_T_C8)

    # --- assemble family (m = 13) ------------------------------------------
    def eff_c1():
        z = (ms_obs.f - e_main) / math.sqrt(e_main * (1 - p_num))
        return {"dispersion_ratio": X2_main_obs / 49, "max_abs_z": float(np.max(np.abs(z)))}

    def eff_c2():
        p_spec = 1 / N_NUMBERS
        return {"ratio": X2_spec_obs / 54}

    family = [
        TestResult("C1", "H1", X2_main_obs, "FRESH", R, fresh_stream, simulated_p(X2_main_obs, r_X2_main), eff_c1()),
        TestResult("C2", "H2", X2_spec_obs, "FRESH", R, fresh_stream, simulated_p(X2_spec_obs, r_X2_spec), eff_c2()),
        TestResult("C3", "H3", T_C3_obs, "FRESH", R, fresh_stream, simulated_p(T_C3_obs, r_T_C3),
                   {"overlap_minus_null": {j: overlap_obs[j] - OVERLAP_MEAN for j in LAGS},
                    "ci_halfwidth": {j: 1.96 * math.sqrt(OVERLAP_VAR / (n - j)) for j in LAGS}}),
        TestResult("C4", "H3", T_C4_obs, "PERM", R, perm_stream, simulated_p(T_C4_obs, r_T_C4),
                   {"overlap_minus_perm_mean": {j: overlap_obs[j] - overlap_perm_mean[j] for j in LAGS}}),
        TestResult("C5", "H3", Q_obs, "FRESH", R, fresh_stream, simulated_p(Q_obs, r_Q),
                   {"r": {h: float(r_obs[h - 1]) for h in range(1, 11)}, "max_abs_r": float(np.max(np.abs(r_obs))),
                    "ci_halfwidth": 1.96 / math.sqrt(n)}),
        TestResult("C6", "H3", runs_obs["T"], "FRESH", R, fresh_stream, simulated_p(runs_obs["T"], r_T_C6),
                   {"R_runs": runs_obs["runs"], "mu": runs_obs["mu"], "n_plus": runs_obs["n_plus"],
                    "n_minus": runs_obs["n_minus"], "n_ties": runs_obs["n_ties"]}),
        TestResult("C7", "H4", X2_C7_obs, "PERM", R, perm_stream, simulated_p(X2_C7_obs, r_X2_C7),
                   {"cramers_v": math.sqrt(X2_C7_obs / (6 * n * (year_G - 1))) if year_G > 1 else float("nan"),
                    "perm_mean_v": float(np.mean(np.sqrt(r_X2_C7 / (6 * n * (year_G - 1))))) if year_G > 1 else float("nan"),
                    "perm_q95_v": float(np.quantile(np.sqrt(r_X2_C7 / (6 * n * (year_G - 1))), 0.95)) if year_G > 1 else float("nan")}),
    ]
    # C8 not applicable if fewer than 3 rolling windows fit (section 6.2 footnote); m drops to 12.
    if len(windows) >= 3:
        family.append(TestResult("C8", "H4", T_C8_obs, "PERM", R, perm_stream, simulated_p(T_C8_obs, r_T_C8),
                   {"v_roll": math.sqrt(T_C8_obs / (6 * ROLL_W)),
                    "perm_mean_v_roll": float(np.mean(np.sqrt(r_T_C8 / (6 * ROLL_W))))}))
    family += [
        TestResult("C9", "H5", D_C9_obs, "FRESH", R, fresh_stream, simulated_p(D_C9_obs, r_D_C9),
                   {"mean_minus_168": float(ms_obs.sum_t.mean() - 168),
                    "ci95": _mean_ci(ms_obs.sum_t)}),
        TestResult("C10", "H5", D_C10_obs, "FRESH", R, fresh_stream, simulated_p(D_C10_obs, r_D_C10),
                   {"mean_minus_40": float(ms_obs.range_t.mean() - 40), "ci95": _mean_ci(ms_obs.range_t)}),
        TestResult("C11", "H5", X2_C11_obs, "FRESH", R, fresh_stream, simulated_p(X2_C11_obs, r_X2_C11),
                   {"w": math.sqrt(X2_C11_obs / n), "mean_minus_expected": float(ms_obs.odd_t.mean() - 168 / 55)}),
        TestResult("C12", "H5", X2_C12_obs, "FRESH", R, fresh_stream, simulated_p(X2_C12_obs, r_X2_C12),
                   {"w": math.sqrt(X2_C12_obs / n), "mean_minus_expected": float(ms_obs.low_t.mean() - 162 / 55)}),
        TestResult("C13", "H5", X2_C13_obs, "FRESH", R, fresh_stream, simulated_p(X2_C13_obs, r_X2_C13),
                   {"w": math.sqrt(X2_C13_obs / n), "mean_minus_expected": float(ms_obs.consec_t.mean() - 6 / 11)}),
    ]

    # M2: n, N=6n and the replicate mean of T per test (a sanity check: e.g. C1's replicate mean
    # should be near 49, C2 near 54, C7 near (G-1)*49, C8 near 49*(1-W/n)).
    _replicate_means = {
        "C1": float(np.mean(r_X2_main)), "C2": float(np.mean(r_X2_spec)),
        "C3": float(np.mean(r_T_C3)), "C4": float(np.mean(r_T_C4)),
        "C5": float(np.mean(r_Q)), "C6": float(np.nanmean(r_T_C6)),
        "C7": float(np.mean(r_X2_C7)), "C8": float(np.nanmean(r_T_C8)) if len(windows) >= 3 else float("nan"),
        "C9": float(np.mean(r_D_C9)), "C10": float(np.mean(r_D_C10)),
        "C11": float(np.mean(r_X2_C11)), "C12": float(np.mean(r_X2_C12)), "C13": float(np.mean(r_X2_C13)),
    }
    N_val = 6 * n
    for t in family:
        t.n = n
        t.N = N_val
        t.replicate_mean = _replicate_means[t.id]

    # --- follow-ups (always computed; interpretation gated by parent) ------
    followups: dict[str, pd.DataFrame] = {}

    followups["C1"] = _binom_followup(ms_obs.f, n, p_num, "number")
    followups["C2"] = _binom_followup(special_obs_counts, n_prime, 1 / N_NUMBERS, "number")

    overlap_minus_null = {j: overlap_obs[j] - OVERLAP_MEAN for j in LAGS}
    overlap_ci_hw = {j: 1.96 * math.sqrt(OVERLAP_VAR / (n - j)) for j in LAGS}
    followups["C3"] = _lag_followup(Z_obs, r_Z, R, "C3", "FRESH",
                                     signed_map=overlap_minus_null, ci_halfwidth_map=overlap_ci_hw)
    followups["C4"] = _lag_followup(Z_obs_perm, r_Zstar, R, "C4", "PERM")
    r_signed = {h: float(r_obs[h - 1]) for h in range(1, 11)}
    r_ci_hw = {h: 1.96 / math.sqrt(n) for h in range(1, 11)}
    followups["C5"] = _lag_followup({h: r_obs[h - 1] for h in range(1, 11)},
                                     {h: np.array(r_r[h]) for h in range(1, 11)}, R, "C5", "FRESH", quantity="r",
                                     signed_map=r_signed, ci_halfwidth_map=r_ci_hw)

    followups["C7"] = _year_followup(contrib_C7_obs, r_contrib_C7, obs.year_labels, R)
    if len(windows) >= 3:
        followups["C8"] = _window_followup(x2w_obs, r_x2w, windows, R)

    followups["C11"] = _cell_followup(O_C11_obs, E_C11_obs, r_O_C11, R, [c[0] for c in odd_cells])
    followups["C12"] = _cell_followup(O_C12_obs, E_C12_obs, r_O_C12, R, [c[0] for c in low_cells])
    followups["C13"] = _cell_followup(O_C13_obs, E_C13_obs, r_O_C13, R, [c[0] for c in consec_cells])

    exploratory = _exploratory(ms_obs, obs, fresh_stream, seed, R)

    return ConfirmatoryRun(
        n=n, n_prime=n_prime, R=R, seed=seed,
        streams={"fresh": fresh_stream, "perm": perm_stream},
        family=family, followups=followups, exploratory=exploratory,
    )


def _mean_ci(values: np.ndarray) -> tuple[float, float]:
    m = float(values.mean())
    sd = float(values.std(ddof=1))
    n = len(values)
    half = 1.96 * sd / math.sqrt(n)
    return (m - half, m + half)


def _binom_followup(counts: np.ndarray, n: int, p: float, key_name: str) -> pd.DataFrame:
    """C1/C2 follow-up: exact two-sided binomial test per number, plus the Wilson 95% CI (M2:
    citable from the M3 EDA output; computed directly here so the CSV is self-contained)."""
    rows = []
    for i, cnt in enumerate(counts, start=1):
        res = binomtest(int(cnt), n, p, alternative="two-sided")
        wilson_lo, wilson_hi = nr.wilson_ci(int(cnt), n)
        rows.append({key_name: i, "count": int(cnt), "n": n, "p_null": p, "p_raw": res.pvalue,
                      "wilson_lo": wilson_lo, "wilson_hi": wilson_hi})
    df = pd.DataFrame(rows)
    df["p_holm"] = holm(df["p_raw"].tolist())
    return df.sort_values(key_name).reset_index(drop=True)


def _lag_followup(obs_map: dict, rep_map: dict, R: int, parent: str, null_kind: str, quantity: str = "Z",
                   signed_map: dict | None = None, ci_halfwidth_map: dict | None = None) -> pd.DataFrame:
    rows = []
    for j in sorted(obs_map):
        obs_val = abs(obs_map[j])
        reps = rep_map[j]
        p = simulated_p(obs_val, reps)
        row = {"lag": j, "quantity": quantity, "abs_stat": obs_val, "R": R, "null": null_kind, "p_raw": p}
        if signed_map is not None:
            row["value"] = signed_map[j]
        if ci_halfwidth_map is not None:
            hw = ci_halfwidth_map[j]
            row["ci_lo"] = signed_map[j] - hw
            row["ci_hi"] = signed_map[j] + hw
        rows.append(row)
    df = pd.DataFrame(rows)
    df["p_holm"] = holm(df["p_raw"].tolist())
    return df.sort_values("lag").reset_index(drop=True)


def _year_followup(contrib_obs: list[float], contrib_rep: dict[int, list[float]], year_labels: list[str], R: int) -> pd.DataFrame:
    rows = []
    for gi, label in enumerate(year_labels):
        p = simulated_p(contrib_obs[gi], np.array(contrib_rep[gi]))
        rows.append({"year": label, "contribution": contrib_obs[gi], "R": R, "null": "PERM", "p_raw": p})
    df = pd.DataFrame(rows)
    df["p_holm"] = holm(df["p_raw"].tolist())
    return df.sort_values("year").reset_index(drop=True)


def _window_followup(x2w_obs: list[float], x2w_rep: dict[int, list[float]], windows: list[tuple[int, int]], R: int) -> pd.DataFrame:
    rows = []
    for wi, (s, e) in enumerate(windows):
        p = simulated_p(x2w_obs[wi], np.array(x2w_rep[wi]))
        rows.append({"window_index": wi + 1, "start_ordinal": s + 1, "end_ordinal": e, "x2_w": x2w_obs[wi], "R": R, "null": "PERM", "p_raw": p})
    df = pd.DataFrame(rows)
    df["p_holm"] = holm(df["p_raw"].tolist())
    return df.sort_values("window_index").reset_index(drop=True)


def _cell_followup(O_obs: np.ndarray, E_obs: np.ndarray, O_rep: np.ndarray, R: int, cell_labels: list) -> pd.DataFrame:
    """Per-cell |standardized residual|, FRESH p, within the aggregate."""
    rows = []
    for ci, label in enumerate(cell_labels):
        e = E_obs[ci]
        z_obs = abs((O_obs[ci] - e) / math.sqrt(e))
        z_rep = np.abs((O_rep[:, ci] - e) / math.sqrt(e))
        p = simulated_p(z_obs, z_rep)
        rows.append({"cell": label, "observed": O_obs[ci], "expected": e, "abs_z": z_obs, "R": R, "null": "FRESH", "p_raw": p})
    df = pd.DataFrame(rows)
    df["p_holm"] = holm(df["p_raw"].tolist())
    return df


# Dedicated stream for the exploratory conditional-H2 test only (never a confirmatory-family
# stream: 101/102/1101/1102 are reserved for the pre-registered family, and 1/2 for M3).
_STREAM_EXPLORATORY_COND_H2 = 103


def _conditional_h2(obs: ObservedData, seed: int, R: int) -> dict:
    """Rank of the special among the 49 numbers not drawn as main; X2 over 49 cells (E = n'/49).
    Under the FRESH mechanism the special is uniform over those 49 by construction, so its rank is
    exactly uniform on 1..49 regardless of H1/H2; this checks that construction on the real data.
    Uses a lightweight direct categorical draw (not the whole-draw simulator) on a dedicated,
    exploratory-only stream, since it is not part of the confirmatory family."""
    n_prime = obs.n_prime
    if n_prime == 0:
        return {"n_prime": 0, "statistic": float("nan"), "p_sim": float("nan")}

    main_masked = obs.main[obs.special_present]  # (n', 6), aligned in order with obs.special
    all_numbers = np.arange(1, N_NUMBERS + 1)
    ranks = np.empty(n_prime, dtype=np.int64)
    for i in range(n_prime):
        non_main = np.setdiff1d(all_numbers, main_masked[i], assume_unique=False)
        ranks[i] = int(np.searchsorted(non_main, obs.special[i]) + 1)  # 1..49
    obs_counts = np.bincount(ranks, minlength=50)[1:50]
    e = n_prime / 49
    X2_obs = float(np.sum((obs_counts - e) ** 2 / e))

    rng = null_model.rng_for(_STREAM_EXPLORATORY_COND_H2, seed)
    reps = rng.integers(1, 50, size=(R, n_prime))
    rep_X2 = np.empty(R)
    for i in range(R):
        c = np.bincount(reps[i], minlength=50)[1:50]
        rep_X2[i] = np.sum((c - e) ** 2 / e)
    p = simulated_p(X2_obs, rep_X2)
    return {"n_prime": n_prime, "statistic": X2_obs, "R": R, "stream": _STREAM_EXPLORATORY_COND_H2, "p_sim": p}


# Registered exploratory-only stream for the "sum chi2 on the M3 bins" item (n9).
_STREAM_EXPLORATORY_SUM_BINS = 104


def _sum_bin_definition() -> list[tuple[int, int]]:
    """M3's fixed width-10 sum bins: 21-30, 31-40, ..., 301-310, then 311-315 (the exact DP
    support's last, narrower bin, since the maximum sum is 315)."""
    bins = [(lo, lo + 9) for lo in range(21, 311, 10)]
    bins.append((311, 315))
    return bins


def _sum_chi2_m3_bins(sum_t: np.ndarray, n: int, seed: int, R: int) -> dict:
    """n9: sum chi2 on the M3 bins, exact bin probabilities from the DP sum pmf, then the same
    section 6.2 tail-pooling rule, FRESH p on a dedicated exploratory stream (104)."""
    bins = _sum_bin_definition()
    edges_lo = np.array([lo for lo, _hi in bins])
    pmf = nr.sum_pmf(N_NUMBERS, K_MAIN)
    bin_probs = np.array([float(pmf.reindex(range(lo, hi + 1), fill_value=0.0).sum()) for lo, hi in bins])
    pmf_series = pd.Series(bin_probs, index=range(len(bins)))
    pooled = pooled_cells(pmf_series, n)
    lookup = cell_index_lookup(pooled, 0, len(bins) - 1)
    p_arr = np.array([c[3] for c in pooled])

    def bucket(sum_vals: np.ndarray) -> np.ndarray:
        bin_idx = np.searchsorted(edges_lo, sum_vals, side="right") - 1
        return bucket_counts(bin_idx, lookup, 0, len(pooled))

    obs_counts = bucket(sum_t)
    X2_obs, _O, _E = pearson_cells(obs_counts, p_arr, n)

    R_use = min(R, 2000)
    rng = null_model.rng_for(_STREAM_EXPLORATORY_SUM_BINS, seed)
    main_flat, _ = null_model.simulate_draws(R_use * n, rng, chunk_size=min(R_use * n, 200_000))
    main_batch = main_flat.reshape(R_use, n, K_MAIN)
    rep_X2 = np.empty(R_use)
    for i in range(R_use):
        s = main_batch[i].sum(axis=1)
        c = bucket(s)
        X2r, _, _ = pearson_cells(c, p_arr, n)
        rep_X2[i] = X2r

    p = simulated_p(X2_obs, rep_X2)
    return {"statistic": X2_obs, "R": R_use, "stream": _STREAM_EXPLORATORY_SUM_BINS, "p_sim": p,
            "n_cells": len(pooled)}


def _exploratory(ms_obs: MainStats, obs: ObservedData, fresh_stream: int, seed: int, R: int) -> dict:
    """Section 6.4 items with a concrete, pinned definition. Labelled 'exploratory, unadjusted'.
    `computed` lists what is computed here; `deferred` lists the remaining open-ended items
    (ruling (b)), already available descriptively in `outputs/eda/through_01190/`."""
    n = obs.n
    p_num = K_MAIN / N_NUMBERS
    e_main = n * p_num
    X2_main_obs = float(np.sum((ms_obs.f - e_main) ** 2 / e_main))
    from scipy.stats import chi2 as chi2_dist
    chi2_c1_scaled = X2_main_obs * 54 / 49
    p_c1_chi2 = float(1 - chi2_dist.cdf(chi2_c1_scaled, df=54))

    Q_obs5, _ = ljung_box(ms_obs.sum_t.astype(float), H=5)
    Q_obs20, _ = ljung_box(ms_obs.sum_t.astype(float), H=20)
    Q_obs10, r10 = ljung_box(ms_obs.sum_t.astype(float), H=10)
    p_c5_chi2 = float(1 - chi2_dist.cdf(Q_obs10, df=10))
    p_c5_chi2_Q5 = float(1 - chi2_dist.cdf(Q_obs5, df=5))
    p_c5_chi2_Q20 = float(1 - chi2_dist.cdf(Q_obs20, df=20))

    cond_h2 = _conditional_h2(obs, seed, min(R, 2000))
    sum_bins = _sum_chi2_m3_bins(ms_obs.sum_t, n, seed, R)

    return {
        "label": "exploratory, unadjusted",
        "c1_chi2_54_49_scaled": {"statistic": chi2_c1_scaled, "df": 54, "p_asymptotic": p_c1_chi2},
        "c5_chi2_10_asymptotic": {"statistic": Q_obs10, "df": 10, "p_asymptotic": p_c5_chi2},
        "ljung_box_Q5": {"statistic": Q_obs5, "df": 5, "p_asymptotic": p_c5_chi2_Q5},
        "ljung_box_Q20": {"statistic": Q_obs20, "df": 20, "p_asymptotic": p_c5_chi2_Q20},
        "conditional_h2_rank": cond_h2,
        "sum_chi2_m3_bins": sum_bins,
        "computed": ["c1_chi2_54_49_scaled", "c5_chi2_10_asymptotic", "ljung_box_Q5", "ljung_box_Q20",
                     "conditional_h2_rank", "sum_chi2_m3_bins"],
        "deferred": ["per_(year,number)_cells", "quarter_tables", "pair_co_occurrence", "min_max_gap_metrics"],
        "deferred_note": "these remain available descriptively in outputs/eda/through_01190 (M3); "
                          "not recomputed here as new confirmatory-style p-values (ruling (b)).",
    }
