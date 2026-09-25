"""Tests for src/models/baselines.py: T1 (hand examples), T2 (Sigma p / range), T3 (short-history
rule), T4 (no future leakage). Per docs/experiments/EXP-001.md r2 sections 2 and 10."""
from __future__ import annotations

import random

import numpy as np
import pytest

from src.models import baselines as bl


def _random_history(n: int, seed: int = 0) -> np.ndarray:
    rng = random.Random(seed)
    rows = [sorted(rng.sample(range(1, 56), 6)) for _ in range(n)]
    return np.array(rows, dtype=np.int64)


# ---------------------------------------------------------------------------
# T1: hand examples
# ---------------------------------------------------------------------------

def test_t1_n0_all_equal_b0():
    main = _random_history(5)
    Y = bl.indicator_matrix(main)
    C = bl.prefix_counts(Y)
    p = bl.b1_probs(C, np.array([1]))[0]
    assert np.allclose(p, 6 / 55, atol=1e-15)
    p2 = bl.b2_probs(C, np.array([1]), 50)[0]
    assert np.allclose(p2, 6 / 55, atol=1e-15)
    p0 = bl.b0_probs(1)[0]
    assert np.allclose(p0, 6 / 55, atol=1e-15)


def test_t1_b1_one_prior_draw():
    main = np.array([[1, 2, 3, 4, 5, 6], [7, 8, 9, 10, 11, 12]], dtype=np.int64)
    Y = bl.indicator_matrix(main)
    C = bl.prefix_counts(Y)
    p = bl.b1_probs(C, np.array([2]))[0]  # t=2: n_t=1, one prior draw {1..6}
    for k in range(1, 56):
        expected = 12 / 61 if k <= 6 else 6 / 61
        assert abs(p[k - 1] - expected) < 1e-15, f"k={k}"


def test_t1_b2_w2_at_t4_matches_draws_2_and_3_only():
    # 5 draws; B2(W=2) at t=4 should use draws 2 and 3 only (not draw 1).
    main = np.array([
        [1, 2, 3, 4, 5, 6],     # draw 1
        [7, 8, 9, 10, 11, 12],  # draw 2
        [7, 8, 9, 10, 11, 12],  # draw 3
        [13, 14, 15, 16, 17, 18],  # draw 4
        [19, 20, 21, 22, 23, 24],  # draw 5
    ], dtype=np.int64)
    Y = bl.indicator_matrix(main)
    C = bl.prefix_counts(Y)
    p = bl.b2_probs(C, np.array([4]), 2)[0]
    m_t = 2
    denom = 6 * m_t + 55
    for k in range(1, 56):
        c = 2 if k in range(7, 13) else 0  # draws 2,3 both contain 7..12
        expected = 6 * (c + 1) / denom
        assert abs(p[k - 1] - expected) < 1e-15, f"k={k}"


# ---------------------------------------------------------------------------
# T2: Sigma p and range
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", [1, 2, 3])
def test_t2_sum_p_and_range(seed):
    n = 300
    main = _random_history(n, seed=seed)
    Y = bl.indicator_matrix(main)
    C = bl.prefix_counts(Y)
    t_values = np.arange(1, n + 1)
    preds = bl.predict_all(C, t_values)
    for cfg, P in preds.items():
        s = P.sum(axis=1)
        assert np.all(np.abs(s - 6) <= 1e-9), cfg
        assert np.all(P > 0) and np.all(P < 1), cfg


# ---------------------------------------------------------------------------
# T3: short-history rule
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("W", [5, 10, 37])
def test_t3_b2_equals_b1_for_short_history(W):
    n = 200
    main = _random_history(n, seed=7)
    Y = bl.indicator_matrix(main)
    C = bl.prefix_counts(Y)
    t_values = np.arange(1, W + 2)  # t <= W+1
    b1 = bl.b1_probs(C, t_values)
    b2 = bl.b2_probs(C, t_values, W)
    assert np.array_equal(b1, b2)

    b0_at_1 = bl.b0_probs(1)[0]
    assert np.array_equal(b1[0], b0_at_1)


def test_t3_b2_ignores_draws_before_the_window():
    W = 10
    n = 60
    main = _random_history(n, seed=11)
    t = W + 20  # > W+1, well inside history
    Y = bl.indicator_matrix(main)
    C = bl.prefix_counts(Y)
    base = bl.b2_probs(C, np.array([t]), W)[0]

    # Changing draw t-W-1 (outside the window) must not change p(t).
    main_changed_outside = main.copy()
    idx_outside = t - W - 1 - 1  # 0-based row index for draw (t-W-1)
    main_changed_outside[idx_outside] = np.array(sorted(set(range(1, 56)) - set(main_changed_outside[idx_outside].tolist()))[:6])
    Y2 = bl.indicator_matrix(main_changed_outside)
    C2 = bl.prefix_counts(Y2)
    p_outside_changed = bl.b2_probs(C2, np.array([t]), W)[0]
    assert np.array_equal(base, p_outside_changed)

    # Changing draw t-W (inside the window) must change p(t).
    main_changed_inside = main.copy()
    idx_inside = t - W - 1  # 0-based row index for draw (t-W)
    main_changed_inside[idx_inside] = np.array(sorted(set(range(1, 56)) - set(main_changed_inside[idx_inside].tolist()))[:6])
    Y3 = bl.indicator_matrix(main_changed_inside)
    C3 = bl.prefix_counts(Y3)
    p_inside_changed = bl.b2_probs(C3, np.array([t]), W)[0]
    assert not np.array_equal(base, p_inside_changed)


# ---------------------------------------------------------------------------
# T4: no future leakage
# ---------------------------------------------------------------------------

def test_t4_no_future_leakage():
    n = 200
    main = _random_history(n, seed=13)
    rng = random.Random(99)
    seeded_ts = rng.sample(range(2, n + 1), 20)

    Y = bl.indicator_matrix(main)
    C = bl.prefix_counts(Y)

    for t in seeded_ts:
        preds_before = {cfg: P[0].copy() for cfg, P in bl.predict_all(C, np.array([t])).items()}

        # Replace every draw >= t (1-based) with different valid draws.
        replaced = main.copy()
        rng2 = random.Random(1000 + t)
        for row in range(t - 1, n):  # 0-based rows for draws t..n
            replaced[row] = sorted(rng2.sample(range(1, 56), 6))
        Y2 = bl.indicator_matrix(replaced)
        C2 = bl.prefix_counts(Y2)
        preds_after = {cfg: P[0] for cfg, P in bl.predict_all(C2, np.array([t])).items()}

        for cfg in preds_before:
            assert np.array_equal(preds_before[cfg], preds_after[cfg]), f"t={t} cfg={cfg}"

        # Changing only draw t changes y(t) but not p(t).
        only_t = main.copy()
        rng3 = random.Random(2000 + t)
        only_t[t - 1] = sorted(rng3.sample(range(1, 56), 6))
        Y3 = bl.indicator_matrix(only_t)
        C3 = bl.prefix_counts(Y3)
        preds_only_t = {cfg: P[0] for cfg, P in bl.predict_all(C3, np.array([t])).items()}
        for cfg in preds_before:
            assert np.array_equal(preds_before[cfg], preds_only_t[cfg]), f"t={t} cfg={cfg}"
        assert not np.array_equal(Y[t - 1], Y3[t - 1])
