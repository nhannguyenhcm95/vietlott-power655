"""Circular block bootstrap over draws (`docs/experiments/EXP-001.md` r2 section 5;
SPECIFICATION section 9.3). One index matrix per period, shared by all five configurations
(paired comparisons). block length L=10, B=10000, seed=20260924 (`numpy.random.default_rng`).
"""
from __future__ import annotations

import math

import numpy as np

from src.evaluation import metrics as m

B_DEFAULT = 10_000
BLOCK = 10
SEED = 20260924


def bootstrap_indices(n: int, seed: int = SEED, B: int = B_DEFAULT, block: int = BLOCK) -> np.ndarray:
    """Exactly per section 5: nb = ceil(n/10); starts = rng.integers(0,n,size=(B,nb));
    idx = ((starts[:,:,None] + arange(10)) % n).reshape(B, nb*10)[:, :n]."""
    rng = np.random.default_rng(seed)
    nb = math.ceil(n / block)
    starts = rng.integers(0, n, size=(B, nb))
    idx = ((starts[:, :, None] + np.arange(block)) % n).reshape(B, nb * block)[:, :n]
    return idx


def percentile_ci(stats: np.ndarray) -> tuple[float, float]:
    lo, hi = np.percentile(stats, [2.5, 97.5])
    return float(lo), float(hi)


def bootstrap_mean_ci(series: np.ndarray, idx: np.ndarray) -> tuple[float, float]:
    """series: (n,). idx: (B, n). Returns the percentile CI of the resampled mean."""
    resampled_means = series[idx].mean(axis=1)
    return percentile_ci(resampled_means)


def bootstrap_ece_ci(P: np.ndarray, Y: np.ndarray, idx: np.ndarray) -> tuple[float, float]:
    """Recomputes ECE (with bins recomputed) on each resample, per section 5."""
    B = idx.shape[0]
    vals = np.empty(B, dtype=np.float64)
    for b in range(B):
        rows = idx[b]
        vals[b] = m.ece_value_only(P[rows], Y[rows])
    return percentile_ci(vals)
