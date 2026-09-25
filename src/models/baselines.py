"""Baseline probability models B0/B1/B2 (`docs/experiments/EXP-001.md` r2 section 2).

No fitted quantities: history counts are *features* (may use every draw before t), and alpha=1,
W are configuration, not tuned parameters (SPECIFICATION section 7). All arithmetic is exact
integer counts converted to float64 only at the final division, per the section 2 reference
implementation.
"""
from __future__ import annotations

import numpy as np

N_NUMBERS = 55
K_MAIN = 6
ALPHA = 1
B0_P = K_MAIN / N_NUMBERS


def indicator_matrix(main_numbers: np.ndarray) -> np.ndarray:
    """main_numbers: (N, 6) int array of values 1..55. Returns Y: (N, 55) int64 0/1, row i is draw i+1."""
    main_numbers = np.asarray(main_numbers, dtype=np.int64)
    n = main_numbers.shape[0]
    Y = np.zeros((n, N_NUMBERS), dtype=np.int64)
    rows = np.repeat(np.arange(n), main_numbers.shape[1])
    cols = (main_numbers - 1).reshape(-1)
    Y[rows, cols] = 1
    return Y


def prefix_counts(Y: np.ndarray) -> np.ndarray:
    """C: (N+1, 55) int64 prefix sums. C[0] = 0; C[t] = sum_{u=1..t} Y[u] (draw u is row u-1 of Y)."""
    n = Y.shape[0]
    C = np.zeros((n + 1, N_NUMBERS), dtype=np.int64)
    if n > 0:
        np.cumsum(Y, axis=0, out=C[1:])
    return C


def b0_probs(n_out: int) -> np.ndarray:
    """p_k(t) = 6/55 for every k, for n_out draws."""
    return np.full((n_out, N_NUMBERS), B0_P, dtype=np.float64)


def b1_probs(C: np.ndarray, t_values: np.ndarray) -> np.ndarray:
    """p_k(t) = 6*(c_k(t) + alpha) / (6*n_t + 55), n_t = t-1, c_k(t) = C[t-1, k]."""
    t_values = np.asarray(t_values, dtype=np.int64)
    n_t = t_values - 1
    c = C[t_values - 1]
    denom = (6 * n_t + N_NUMBERS).astype(np.float64)[:, None]
    return 6.0 * (c + ALPHA) / denom


def b2_probs(C: np.ndarray, t_values: np.ndarray, W: int) -> np.ndarray:
    """p_k(t) = 6*(c_k^W(t) + alpha) / (6*m_t + 55), m_t = min(W, n_t).

    c_k^W(t) = C[t-1, k] - C[t-1-m_t, k] (sum over draws (t-m_t)..(t-1))."""
    t_values = np.asarray(t_values, dtype=np.int64)
    n_t = t_values - 1
    m_t = np.minimum(W, n_t)
    upper = C[t_values - 1]
    lower = C[t_values - 1 - m_t]
    c = upper - lower
    denom = (6 * m_t + N_NUMBERS).astype(np.float64)[:, None]
    return 6.0 * (c + ALPHA) / denom


def sum_forecast(P: np.ndarray) -> np.ndarray:
    """s_hat(t) = sum_k k * p_k(t)."""
    k = np.arange(1, N_NUMBERS + 1, dtype=np.float64)
    return P @ k


CONFIGS = ["B0", "B1", "B2_W50", "B2_W100", "B2_W200"]
B2_WINDOWS = [50, 100, 200]


def predict_all(C: np.ndarray, t_values: np.ndarray) -> dict[str, np.ndarray]:
    """Returns {config_name: P (T,55)} for all five configurations at the given t values."""
    out = {
        "B0": b0_probs(len(t_values)),
        "B1": b1_probs(C, t_values),
    }
    for w in B2_WINDOWS:
        out[f"B2_W{w}"] = b2_probs(C, t_values, w)
    return out
