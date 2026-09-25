"""Exact null reference distributions for the M3 EDA metrics (spec section 3.1).

All functions are pure and take N, k as parameters so tests can enumerate small cases.
`math.comb` returns 0 outside its support (negative or out-of-range arguments), matching
the spec's note.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy.stats import binom, hypergeom


def sum_pmf(N: int = 55, k: int = 6) -> pd.Series:
    """pmf of the sum of a uniform k-subset of 1..N, via 0/1-knapsack DP, exact (Fraction-free
    integer counts divided by C(N,k))."""
    total = N * (N + 1) // 2
    dp = np.zeros((k + 1, total + 1), dtype=object)
    dp[0, 0] = 1
    for num in range(1, N + 1):
        top = min(k, num)
        for j in range(top, 0, -1):
            dp[j, num:] = dp[j, num:] + dp[j - 1, : total + 1 - num]
    counts = dp[k]
    denom = math.comb(N, k)
    idx = np.nonzero(counts)[0]
    probs = np.array([counts[i] / denom for i in idx], dtype=float)
    return pd.Series(probs, index=idx.astype(int)).sort_index()


def min_pmf(N: int = 55, k: int = 6) -> pd.Series:
    denom = math.comb(N, k)
    vals = {m: math.comb(N - m, k - 1) / denom for m in range(1, N - k + 2)}
    return pd.Series(vals).sort_index()


def max_pmf(N: int = 55, k: int = 6) -> pd.Series:
    denom = math.comb(N, k)
    vals = {m: math.comb(m - 1, k - 1) / denom for m in range(k, N + 1)}
    return pd.Series(vals).sort_index()


def range_pmf(N: int = 55, k: int = 6) -> pd.Series:
    denom = math.comb(N, k)
    vals = {r: (N - r) * math.comb(r - 1, k - 2) / denom for r in range(k - 1, N)}
    return pd.Series(vals).sort_index()


def hypergeom_pmf(N: int, K: int, k: int) -> pd.Series:
    lo = max(0, k - (N - K))
    hi = min(k, K)
    vals = {x: float(hypergeom.pmf(x, N, K, k)) for x in range(lo, hi + 1)}
    return pd.Series(vals).sort_index()


def consecutive_pairs_pmf(N: int = 55, k: int = 6) -> pd.Series:
    denom = math.comb(N, k)
    vals = {c: math.comb(k - 1, c) * math.comb(N - k + 1, k - c) / denom for c in range(0, k)}
    return pd.Series(vals).sort_index()


def gap_pmf(N: int = 55, k: int = 6) -> pd.Series:
    """pmf of a single spacing g_i (i = 1..k-1); spacings are exchangeable."""
    denom = math.comb(N, k)
    vals = {d: math.comb(N - d, k - 1) / denom for d in range(1, N - k + 2)}
    return pd.Series(vals).sort_index()


def min_gap_pmf(N: int = 55, k: int = 6) -> pd.Series:
    denom = math.comb(N, k)

    def surv(d: int) -> float:
        arg = N - (k - 1) * (d - 1)
        if arg < k or arg < 0:
            return 0.0
        return math.comb(arg, k) / denom

    vals: dict[int, float] = {}
    d = 1
    while surv(d) > 0:
        vals[d] = surv(d) - surv(d + 1)
        d += 1
        if d > N:  # safety bound
            break
    return pd.Series(vals).sort_index()


def max_gap_pmf(N: int = 55, k: int = 6) -> pd.Series:
    denom = math.comb(N, k)
    m = k - 1  # number of internal gaps
    max_s = N - 1

    def count_tuples(g: int) -> np.ndarray:
        """c_g(s): number of m-tuples of ints in [1,g] summing to s, for s = 0..max_s."""
        dp = np.zeros(max_s + 1, dtype=object)
        dp[0] = 1
        for _ in range(m):
            new = np.zeros(max_s + 1, dtype=object)
            for v in range(1, g + 1):
                if v <= max_s:
                    new[v:] = new[v:] + dp[: max_s + 1 - v]
            dp = new
        return dp

    def cdf(g: int) -> float:
        if g <= 0:
            return 0.0
        gg = min(g, max_s)
        counts = count_tuples(gg)
        s_vals = np.arange(max_s + 1)
        weights = np.maximum(N - s_vals, 0)
        total = sum(int(counts[i]) * int(weights[i]) for i in range(max_s + 1))
        return total / denom

    vals: dict[int, float] = {}
    g_hi = N - k + 1
    prev = 0.0
    for g in range(1, g_hi + 1):
        c = cdf(g)
        p = c - prev
        if p > 1e-15:
            vals[g] = p
        prev = c
    return pd.Series(vals).sort_index()


def geometric_pmf(p: float, g_max: int) -> pd.Series:
    """pmf of a Geometric(p) count of trials until first success, truncated to g = 1..g_max."""
    g = np.arange(1, g_max + 1)
    probs = (1 - p) ** (g - 1) * p
    return pd.Series(probs, index=g)


def binomial_band(m: int, p: float, lo_q: float = 0.025, hi_q: float = 0.975) -> tuple[float, float]:
    """Pointwise central quantile band (coverage >= 95%) for Binomial(m, p)."""
    lo = float(binom.ppf(lo_q, m, p))
    hi = float(binom.ppf(hi_q, m, p))
    return lo, hi


def wilson_ci(count: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """Wilson score confidence interval for a binomial proportion."""
    if n == 0:
        return 0.0, 0.0
    phat = count / n
    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    adj = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    lo = max(0.0, center - adj)
    hi = min(1.0, center + adj)
    return lo, hi
