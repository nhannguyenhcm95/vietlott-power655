"""M5 metrics: per-draw log loss / Brier, Sigma p, ECE/reliability, set-level log score, sum
forecast MAE/RMSE (`docs/experiments/EXP-001.md` r2 section 5; SPECIFICATION section 9).
"""
from __future__ import annotations

import math

import numpy as np
from scipy.special import comb
from scipy.stats import binom

EPS = 1e-6
N_NUMBERS = 55

# ln C(55,6) = ln 28,989,675
SET_LEVEL_LOG_SCORE_B0 = math.log(comb(55, 6, exact=True))


def clip_probs(P: np.ndarray) -> np.ndarray:
    return np.clip(P, EPS, 1 - EPS)


def per_draw_log_loss(Y: np.ndarray, P: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Returns (LL(t) array, n_clipped(t) array). LL uses clipped p; n_clipped counts cells
    where the raw p fell outside [EPS, 1-EPS]."""
    Pc = clip_probs(P)
    n_clipped = ((P < EPS) | (P > 1 - EPS)).sum(axis=1)
    ll = -(Y * np.log(Pc) + (1 - Y) * np.log(1 - Pc)).mean(axis=1)
    return ll, n_clipped


def per_draw_brier(Y: np.ndarray, P: np.ndarray) -> np.ndarray:
    """Unclipped, per section 5."""
    return ((Y - P) ** 2).mean(axis=1)


def sum_p(P: np.ndarray) -> np.ndarray:
    return P.sum(axis=1)


def ece_table(P: np.ndarray, Y: np.ndarray) -> tuple[float, int, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Pools all (t, k) cells. Returns (ece, n_bins, bin_ids, n_per_bin, p_mean_per_bin, y_mean_per_bin)."""
    p_flat = np.asarray(P, dtype=np.float64).reshape(-1)
    y_flat = np.asarray(Y, dtype=np.float64).reshape(-1)
    n = p_flat.size
    quantiles = np.quantile(p_flat, [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9])
    edges = np.unique(quantiles)
    bins = np.searchsorted(edges, p_flat, side="right")

    nbins = int(bins.max()) + 1 if n > 0 else 0
    counts = np.bincount(bins, minlength=nbins)
    psum = np.bincount(bins, weights=p_flat, minlength=nbins)
    ysum = np.bincount(bins, weights=y_flat, minlength=nbins)
    # min/max per bin (needed for the reliability table only, not for ECE itself)
    pmin = np.full(nbins, np.nan)
    pmax = np.full(nbins, np.nan)
    for b in np.unique(bins):
        pmin[b] = p_flat[bins == b].min()
        pmax[b] = p_flat[bins == b].max()

    nonempty = counts > 0
    p_mean = np.divide(psum, counts, out=np.zeros_like(psum), where=nonempty)
    y_mean = np.divide(ysum, counts, out=np.zeros_like(ysum), where=nonempty)
    ece_val = float(np.sum((counts[nonempty] / n) * np.abs(y_mean[nonempty] - p_mean[nonempty])))
    n_bins = int(nonempty.sum())

    bin_ids = np.nonzero(nonempty)[0]
    return ece_val, n_bins, bin_ids, counts[nonempty], p_mean[nonempty], y_mean[nonempty], pmin[nonempty], pmax[nonempty]


def ece_value_only(P: np.ndarray, Y: np.ndarray) -> float:
    """Fast path for bootstrap resampling: same binning as ece_table but returns only the scalar."""
    p_flat = np.asarray(P, dtype=np.float64).reshape(-1)
    y_flat = np.asarray(Y, dtype=np.float64).reshape(-1)
    n = p_flat.size
    quantiles = np.quantile(p_flat, [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9])
    edges = np.unique(quantiles)
    bins = np.searchsorted(edges, p_flat, side="right")
    nbins = int(bins.max()) + 1 if n > 0 else 0
    counts = np.bincount(bins, minlength=nbins)
    psum = np.bincount(bins, weights=p_flat, minlength=nbins)
    ysum = np.bincount(bins, weights=y_flat, minlength=nbins)
    nonempty = counts > 0
    p_mean = psum[nonempty] / counts[nonempty]
    y_mean = ysum[nonempty] / counts[nonempty]
    return float(np.sum((counts[nonempty] / n) * np.abs(y_mean - p_mean)))


def sum_forecast(P: np.ndarray) -> np.ndarray:
    k = np.arange(1, N_NUMBERS + 1, dtype=np.float64)
    return P @ k


def sum_mae_rmse(s_actual: np.ndarray, s_forecast: np.ndarray) -> tuple[float, float]:
    diff = s_actual - s_forecast
    mae = float(np.mean(np.abs(diff)))
    rmse = float(np.sqrt(np.mean(diff ** 2)))
    return mae, rmse


# ---------------------------------------------------------------------------
# Section 9 (EXP-001 r2): exact null-reference expectations. Sanity references only, never targets.
# ---------------------------------------------------------------------------

P0 = 6 / 55


def exact_delta_bs(m: int, p0: float = P0) -> float:
    """E[delta BS(t)] = 36*m*p0*(1-p0) / (6m+55)^2, history length m (B2: m=min(W,n_t); B1: m=n_t)."""
    return 36.0 * m * p0 * (1 - p0) / (6 * m + 55) ** 2


def exact_delta_ll(m: int, p0: float = P0) -> float:
    """E[delta LL(t)] = sum_{c=0..m} Bin(c;m,p0)*[CE(p0, p_hat(c)) - H(p0)],
    p_hat(c) = 6(c+1)/(6m+55), CE(p0,q) = -p0 ln q - (1-p0) ln(1-q), H(p0)=CE(p0,p0)."""
    if m == 0:
        return 0.0
    c = np.arange(0, m + 1)
    p_hat = 6.0 * (c + 1) / (6 * m + 55)
    ce = -p0 * np.log(p_hat) - (1 - p0) * np.log(1 - p_hat)
    h = -p0 * math.log(p0) - (1 - p0) * math.log(1 - p0)
    weights = binom.pmf(c, m, p0)
    return float(np.sum(weights * (ce - h)))
