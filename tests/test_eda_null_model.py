"""T4/T5: simulator correctness and RNG determinism (M3 spec section 3.2, 6)."""
from __future__ import annotations

import math

import numpy as np
import pytest

from src.statistics import null_model as nm
from src.statistics import mc_reference


def test_t4_simulator_correctness():
    rng = nm.rng_for(stream_id=1)
    main, special = nm.simulate_draws(200_000, rng)
    m = 200_000

    assert main.shape == (m, 6)
    assert special.shape == (m,)

    # 6 distinct ascending values in 1..55
    assert (main >= 1).all() and (main <= 55).all()
    assert (np.diff(main, axis=1) > 0).all()

    # special not in main
    in_main = (main == special[:, None]).any(axis=1)
    assert not in_main.any()

    # each number's rate within 5 SE of 6/55
    p = nm.P_NUMBER
    se = math.sqrt(p * (1 - p) / m)
    counts = np.zeros(56, dtype=np.int64)
    flat = main.ravel()
    np.add.at(counts, flat, 1)
    for k in range(1, 56):
        rate = counts[k] / m
        assert abs(rate - p) < 5 * se

    # special rate within 5 SE of 1/55
    ps = 1 / 55
    se_s = math.sqrt(ps * (1 - ps) / m)
    scounts = np.zeros(56, dtype=np.int64)
    np.add.at(scounts, special, 1)
    for k in range(1, 56):
        rate = scounts[k] / m
        assert abs(rate - ps) < 5 * se_s

    # mean sum within 4*sqrt(1372/m) of 168
    sums = main.sum(axis=1)
    se_sum = 4 * math.sqrt(1372 / m)
    assert abs(sums.mean() - 168) < se_sum

    # TV distance (consecutive pmf) < 0.01
    from src.statistics import null_reference as nr
    consec = (np.diff(main, axis=1) == 1).sum(axis=1)
    obs_counts = np.bincount(consec, minlength=6)
    obs_probs = obs_counts / m
    exact = nr.consecutive_pairs_pmf(55, 6)
    tv = 0.0
    for c in range(6):
        exact_p = exact.get(c, 0.0)
        tv += abs(obs_probs[c] - exact_p)
    tv /= 2
    assert tv < 0.01


def test_t4_pearson_x2_mean_near_49():
    """2,000 datasets of n=200 have mean Pearson X^2 within 4 SE of 49 (not 54)."""
    reps = 2000
    n = 200
    x2s = []
    p = nm.P_NUMBER
    rng = nm.rng_for(stream_id=999001)
    for i in range(reps):
        main, _ = nm.simulate_draws(n, rng)
        counts = np.zeros(56, dtype=np.int64)
        np.add.at(counts, main.ravel(), 1)
        counts = counts[1:]
        expected = n * p
        x2 = ((counts - expected) ** 2 / expected).sum()
        x2s.append(x2)
    x2s = np.array(x2s)
    mean_x2 = x2s.mean()
    se = x2s.std(ddof=1) / math.sqrt(reps)
    assert abs(mean_x2 - 49) < 4 * se


def test_t5_rng_determinism_same_seed():
    rng1 = nm.rng_for(stream_id=1)
    rng2 = nm.rng_for(stream_id=1)
    m1, s1 = nm.simulate_draws(500, rng1)
    m2, s2 = nm.simulate_draws(500, rng2)
    assert np.array_equal(m1, m2)
    assert np.array_equal(s1, s2)


def test_t5_rng_determinism_chunk_invariance():
    ref_main, ref_special = nm.simulate_draws(210, nm.rng_for(stream_id=2))
    for chunk in (1, 7, 210):
        main, special = nm.simulate_draws(210, nm.rng_for(stream_id=2), chunk_size=chunk)
        assert np.array_equal(main, ref_main)
        assert np.array_equal(special, ref_special)


def test_t5_different_stream_gives_different_arrays():
    m1, s1 = nm.simulate_draws(50, nm.rng_for(stream_id=1))
    m2, s2 = nm.simulate_draws(50, nm.rng_for(stream_id=2))
    assert not np.array_equal(m1, m2)


def test_t5_replicate_references_chunk_invariance():
    kwargs = dict(n=200, windows=[50], n_blocks=5, reps=30, seed=123)
    ref = mc_reference.replicate_references(**kwargs, replicate_chunk_size=1)
    for chunk in (3, 30):
        out = mc_reference.replicate_references(**kwargs, replicate_chunk_size=chunk)
        assert out.equals(ref)


def test_f7_special_band_moves_with_n_prime_below_n():
    """F7: with n' < n, the special-number simultaneous quantiles move with n' (simulated on
    stream 2, registered in null_model's module docstring convention) and match Binomial(n', 1/55)
    min/max quantiles within MC error, distinct from the n-based main-number band."""
    n, n_prime, reps = 500, 200, 4000
    out_full = mc_reference.replicate_references(n=n, windows=[], n_blocks=2, reps=reps, seed=7, n_special=n)
    out_partial = mc_reference.replicate_references(n=n, windows=[], n_blocks=2, reps=reps, seed=7, n_special=n_prime)

    sp_min_full = out_full.loc[out_full.statistic == "special_frequency_min", "value"].iloc[0]
    sp_max_full = out_full.loc[out_full.statistic == "special_frequency_max", "value"].iloc[0]
    sp_min_partial = out_partial.loc[out_partial.statistic == "special_frequency_min", "value"].iloc[0]
    sp_max_partial = out_partial.loc[out_partial.statistic == "special_frequency_max", "value"].iloc[0]

    # n' < n must give a visibly tighter (smaller-scale) special band.
    assert sp_max_partial - sp_min_partial < sp_max_full - sp_min_full

    # Compare against the exact Binomial(n', 1/55) min/max-of-55 reference, computed directly by
    # brute-force simulation (independent of mc_reference's own internals).
    p = 1 / 55
    rng = np.random.default_rng(12345)
    mins, maxs = [], []
    for _ in range(reps):
        counts = rng.binomial(n_prime, p, size=55)
        mins.append(counts.min())
        maxs.append(counts.max())
    ref_lo = np.quantile(mins, 0.025)
    ref_hi = np.quantile(maxs, 0.975)
    assert abs(sp_min_partial - ref_lo) <= 3
    assert abs(sp_max_partial - ref_hi) <= 3

    # The main-number band (which always uses n, not n') is unaffected by n_special.
    freq_max_full = out_full.loc[out_full.statistic == "number_frequency_max", "value"].iloc[0]
    freq_max_partial = out_partial.loc[out_partial.statistic == "number_frequency_max", "value"].iloc[0]
    assert freq_max_full == freq_max_partial
