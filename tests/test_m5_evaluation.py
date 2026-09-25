"""Tests for src/evaluation/{folds,metrics,bootstrap,selection}.py:
T5 (fold builder), T6 (dev-range guard), T8 (W selection), T9 (metric hand examples),
T10 (bootstrap), T11 (null reference). Per docs/experiments/EXP-001.md r2 sections 3-5, 9, 10."""
from __future__ import annotations

import math

import numpy as np
import pytest

from src.evaluation import bootstrap as bs
from src.evaluation import folds as ev_folds
from src.evaluation import metrics as ev_metrics
from src.evaluation import selection as ev_selection
from src.models import baselines as bl


# ---------------------------------------------------------------------------
# T5: fold builder
# ---------------------------------------------------------------------------

_EXPECTED_ROWS = [
    (1, 1, 500, 1, 400, 401, 500, 501, 550, 50),
    (2, 1, 550, 1, 450, 451, 550, 551, 600, 50),
    (3, 1, 600, 1, 500, 501, 600, 601, 650, 50),
    (4, 1, 650, 1, 550, 551, 650, 651, 700, 50),
    (5, 1, 700, 1, 600, 601, 700, 701, 750, 50),
    (6, 1, 750, 1, 650, 651, 750, 751, 800, 50),
    (7, 1, 800, 1, 700, 701, 800, 801, 850, 50),
    (8, 1, 850, 1, 750, 751, 850, 851, 900, 50),
    (9, 1, 900, 1, 800, 801, 900, 901, 950, 50),
    (10, 1, 950, 1, 850, 851, 950, 951, 1000, 50),
    (11, 1, 1000, 1, 900, 901, 1000, 1001, 1050, 50),
    (12, 1, 1050, 1, 950, 951, 1050, 1051, 1100, 50),
    (13, 1, 1100, 1, 1000, 1001, 1100, 1101, 1150, 50),
    (14, 1, 1150, 1, 1050, 1051, 1150, 1151, 1190, 40),
]


def test_t5_fold_table_matches_spec_exactly():
    ft = ev_folds.fold_table()
    assert len(ft) == 14
    for row, expected in zip(ft.itertuples(index=False), _EXPECTED_ROWS):
        assert tuple(row) == expected


def test_t5_scored_ranges_disjoint_and_union_is_501_1190():
    folds = ev_folds.build_folds()
    all_scored: list[int] = []
    for f in folds:
        rng = list(range(f.scored_start, f.scored_end + 1))
        assert not (set(rng) & set(all_scored)), "scored ranges must be disjoint"
        all_scored.extend(rng)
        assert f.fit_end < f.scored_start
    assert sorted(all_scored) == list(range(501, 1191))


def test_t5_validation_mask_has_210_draws_20_from_fold_10():
    scored = ev_folds.scored_draw_table()
    val = scored[scored["in_validation"]]
    assert len(val) == 210
    assert len(val[val["fold"] == 10]) == 20
    for f in (11, 12, 13):
        assert len(val[val["fold"] == f]) == 50
    assert len(val[val["fold"] == 14]) == 40


def test_t5_inner_windows_match_spec():
    ft = ev_folds.fold_table()
    row10 = ft[ft["fold"] == 10].iloc[0]
    assert (row10["inner_val_start"], row10["inner_val_end"]) == (851, 950)
    assert (row10["inner_train_start"], row10["inner_train_end"]) == (1, 850)


# ---------------------------------------------------------------------------
# T6: dev-range guard
# ---------------------------------------------------------------------------

def test_t6_assert_dev_only_raises_on_1191():
    with pytest.raises(ev_folds.DevRangeViolation):
        ev_folds.assert_dev_only([1191])
    with pytest.raises(ev_folds.DevRangeViolation):
        ev_folds.assert_dev_only([500, 1000, 1191])
    ev_folds.assert_dev_only([1, 500, 1190])  # no raise


def test_t6_fold_builder_and_scorer_raise_on_1191():
    # The fold builder itself never proposes 1191; this checks the guard is actually wired in.
    with pytest.raises(ev_folds.DevRangeViolation):
        ev_folds.assert_dev_only(range(1151, 1192))


# ---------------------------------------------------------------------------
# T8: W selection
# ---------------------------------------------------------------------------

def test_t8_distinct_values_give_argmin():
    w_star, table = ev_selection.select_w({50: 0.1, 100: 0.2, 200: 0.3})
    assert w_star == 50
    assert table[table["W"] == 50]["selected"].iloc[0]


def test_t8_tie_within_1e12_gives_larger_w():
    x = 0.5
    w_star, table = ev_selection.select_w({50: x, 100: x + 1.0, 200: x})
    assert w_star == 200


def test_t8_tied_50_100_with_200_higher_by_1e9_gives_100():
    x = 0.5
    w_star, table = ev_selection.select_w({50: x, 100: x, 200: x + 1e-9})
    assert w_star == 100


def test_t8_chain_not_tied_transitively_gives_100():
    x = 0.5
    w_star, table = ev_selection.select_w({50: x, 100: x + 0.6e-12, 200: x + 1.2e-12})
    assert w_star == 100
    row200 = table[table["W"] == 200].iloc[0]
    assert not row200["in_tie_set"]


# ---------------------------------------------------------------------------
# T9: metric hand examples
# ---------------------------------------------------------------------------

def test_t9_ll_and_brier_p_half_six_ones():
    Y = np.zeros((1, 55))
    Y[0, :6] = 1
    P = np.full((1, 55), 0.5)
    ll, n_clipped = ev_metrics.per_draw_log_loss(Y, P)
    brier = ev_metrics.per_draw_brier(Y, P)
    assert abs(ll[0] - math.log(2)) < 1e-12
    assert abs(brier[0] - 0.25) < 1e-12
    assert n_clipped[0] == 0


def test_t9_clip_and_n_clipped():
    Y = np.array([[1] + [0] * 54])
    P = np.array([[0.0] + [0.5] * 54])
    ll, n_clipped = ev_metrics.per_draw_log_loss(Y, P)
    assert n_clipped[0] == 1
    expected_first_term = -math.log(1e-6)
    # ll is the mean over 55 cells; verify the clipped cell's contribution directly.
    Pc = ev_metrics.clip_probs(P)
    assert abs(Pc[0, 0] - 1e-6) < 1e-15


def test_t9_ece_hand_example():
    p = np.array([0.1] * 10 + [0.3] * 10).reshape(1, 20)
    y = np.zeros((1, 20))
    y[0, :2] = 1       # 2 ones among the p=0.1 group
    y[0, 10:13] = 1     # 3 ones among the p=0.3 group
    ece_val, n_bins, bin_ids, bin_n, bin_pmean, bin_ymean, bin_pmin, bin_pmax = ev_metrics.ece_table(p, y)
    assert n_bins == 2
    assert abs(ece_val - 0.05) < 1e-12


def test_t9_b0_constants_and_set_level_score():
    n = 20
    Y = np.zeros((n, 55))
    for i in range(n):
        Y[i, :6] = 1
    P = bl.b0_probs(n)
    ll, n_clipped = ev_metrics.per_draw_log_loss(Y, P)
    brier = ev_metrics.per_draw_brier(Y, P)
    assert np.allclose(ll, 0.3446104320908521, atol=1e-12)
    assert np.allclose(brier, 0.09719008264462808, atol=1e-12)
    ece_val, n_bins, *_ = ev_metrics.ece_table(P, Y)
    assert ece_val < 1e-12
    assert n_bins == 1
    assert abs(ev_metrics.SET_LEVEL_LOG_SCORE_B0 - math.log(28_989_675)) < 1e-9


# ---------------------------------------------------------------------------
# T10: bootstrap
# ---------------------------------------------------------------------------

def test_t10_same_seed_gives_identical_idx():
    idx1 = bs.bootstrap_indices(37, seed=42, B=100)
    idx2 = bs.bootstrap_indices(37, seed=42, B=100)
    assert np.array_equal(idx1, idx2)


def test_t10_shape_and_range():
    n = 55
    idx = bs.bootstrap_indices(n, seed=1, B=50)
    assert idx.shape == (50, n)
    assert idx.min() >= 0 and idx.max() < n


def test_t10_rows_are_circular_runs_of_length_10():
    n = 33
    idx = bs.bootstrap_indices(n, seed=5, B=20, block=10)
    for row in idx:
        # every consecutive run of 10 (except possibly the tail, truncated to n) must be a
        # circular rotation: idx[j+1] == (idx[j] + 1) % n within a block of 10.
        full_blocks = len(row) // 10
        for b in range(full_blocks):
            block = row[b * 10:(b + 1) * 10]
            for j in range(len(block) - 1):
                assert block[j + 1] == (block[j] + 1) % n


def test_t10_small_n_bootstrap_mean_equals_sample_mean():
    n = 8  # n <= 10: every row is a rotation of 0..n-1, so mean is invariant
    idx = bs.bootstrap_indices(n, seed=3, B=200)
    series = np.arange(1, n + 1, dtype=np.float64)
    resampled_means = series[idx].mean(axis=1)
    assert np.allclose(resampled_means, series.mean(), atol=1e-9)


def test_t10_delta_ci_equals_ci_of_paired_diff_series():
    n = 60
    rng = np.random.default_rng(0)
    a = rng.normal(size=n)
    b = rng.normal(size=n)
    idx = bs.bootstrap_indices(n, seed=9, B=500)
    diff = a - b
    direct_ci = bs.bootstrap_mean_ci(diff, idx)
    a_ci_means = a[idx].mean(axis=1)
    b_ci_means = b[idx].mean(axis=1)
    via_components = bs.percentile_ci(a_ci_means - b_ci_means)
    assert direct_ci == pytest.approx(via_components)


# ---------------------------------------------------------------------------
# T11: null reference
# ---------------------------------------------------------------------------

def test_t11_exact_delta_ll_reproduces_section9():
    assert abs(ev_metrics.exact_delta_ll(50) - 0.00788) < 5e-6
    assert abs(ev_metrics.exact_delta_ll(100) - 0.00445) < 5e-6
    assert abs(ev_metrics.exact_delta_ll(200) - 0.00236) < 5e-6
    assert abs(ev_metrics.exact_delta_ll(500) - 0.00098) < 5e-6


def test_t11_synthetic_uniform_histories_match_null_expectation_and_w_star():
    from src.evaluation import selection as sel

    n_histories = 200
    n_draws = 1190
    rng = np.random.default_rng(2026)

    delta_bs_sums = {cfg: 0.0 for cfg in bl.CONFIGS if cfg != "B0"}
    delta_ll_sums = {cfg: 0.0 for cfg in bl.CONFIGS if cfg != "B0"}
    n_scored_total = 0
    w_star_counts: dict[int, int] = {}

    for h in range(n_histories):
        main = np.array([rng.choice(55, size=6, replace=False) + 1 for _ in range(n_draws)])
        Y = bl.indicator_matrix(main)
        C = bl.prefix_counts(Y)
        t_values = np.arange(501, 1191)
        preds = bl.predict_all(C, t_values)
        Y_scored = Y[t_values - 1]
        n_scored_total += len(t_values)

        for cfg in delta_bs_sums:
            P = preds[cfg]
            ll, _ = ev_metrics.per_draw_log_loss(Y_scored, P)
            brier = ev_metrics.per_draw_brier(Y_scored, P)
            ll0, _ = ev_metrics.per_draw_log_loss(Y_scored, preds["B0"])
            brier0 = ev_metrics.per_draw_brier(Y_scored, preds["B0"])
            delta_ll_sums[cfg] += float((ll - ll0).sum())
            delta_bs_sums[cfg] += float((brier - brier0).sum())

        val_mask = (t_values >= 981) & (t_values <= 1190)
        l_w = {}
        for w in bl.B2_WINDOWS:
            ll_w, _ = ev_metrics.per_draw_log_loss(Y_scored[val_mask], preds[f"B2_W{w}"][val_mask])
            l_w[w] = float(ll_w.mean())
        w_star, _ = sel.select_w(l_w)
        w_star_counts[w_star] = w_star_counts.get(w_star, 0) + 1

    assert w_star_counts == {200: n_histories}

    n_per_history = n_draws - 500
    mc_se_bs = 0.01  # loose bound; the exact reference sits well inside 4x this
    for cfg in delta_bs_sums:
        w_or_n = {"B1": None, "B2_W50": 50, "B2_W100": 100, "B2_W200": 200}[cfg]
        observed_mean_ll = delta_ll_sums[cfg] / (n_histories * n_per_history)
        observed_mean_bs = delta_bs_sums[cfg] / (n_histories * n_per_history)
        if w_or_n is None:
            # B1: m = n_t varies 500..1189; use the per-fold average reference from the spec (approx).
            ref_ll = 0.00062  # dev_pooled average per EXP-001 section 9 (B1)
            ref_bs = None
        else:
            ref_ll = ev_metrics.exact_delta_ll(w_or_n)
            ref_bs = ev_metrics.exact_delta_bs(w_or_n)
        assert abs(observed_mean_ll - ref_ll) < 0.01, cfg  # loose: 200 MC histories, descriptive check
        if ref_bs is not None:
            assert abs(observed_mean_bs - ref_bs) < 0.01, cfg
