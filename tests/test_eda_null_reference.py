"""T2/T3: exact null pmfs vs brute-force enumeration and known constants (M3 spec section 3.1, 6)."""
from __future__ import annotations

import itertools
import math

import numpy as np
import pytest

from src.statistics import null_model, null_reference as nr

SMALL_CASES = [(10, 3), (12, 4), (11, 6)]


def _draws(N: int, k: int):
    return list(itertools.combinations(range(1, N + 1), k))


def _brute_sum(N, k):
    counts: dict[int, int] = {}
    for d in _draws(N, k):
        counts[sum(d)] = counts.get(sum(d), 0) + 1
    denom = math.comb(N, k)
    return {s: c / denom for s, c in counts.items()}


def _brute_min(N, k):
    counts: dict[int, int] = {}
    for d in _draws(N, k):
        counts[d[0]] = counts.get(d[0], 0) + 1
    denom = math.comb(N, k)
    return {m: c / denom for m, c in counts.items()}


def _brute_max(N, k):
    counts: dict[int, int] = {}
    for d in _draws(N, k):
        counts[d[-1]] = counts.get(d[-1], 0) + 1
    denom = math.comb(N, k)
    return {m: c / denom for m, c in counts.items()}


def _brute_range(N, k):
    counts: dict[int, int] = {}
    for d in _draws(N, k):
        r = d[-1] - d[0]
        counts[r] = counts.get(r, 0) + 1
    denom = math.comb(N, k)
    return {r: c / denom for r, c in counts.items()}


def _brute_hypergeom(N, K, k):
    band = set(range(1, K + 1))
    counts: dict[int, int] = {}
    for d in _draws(N, k):
        x = sum(1 for v in d if v in band)
        counts[x] = counts.get(x, 0) + 1
    denom = math.comb(N, k)
    return {x: c / denom for x, c in counts.items()}


def _brute_consecutive(N, k):
    counts: dict[int, int] = {}
    for d in _draws(N, k):
        c = sum(1 for i in range(len(d) - 1) if d[i + 1] - d[i] == 1)
        counts[c] = counts.get(c, 0) + 1
    denom = math.comb(N, k)
    return {c: v / denom for c, v in counts.items()}


def _brute_gap(N, k):
    counts: dict[int, int] = {}
    n_gaps = 0
    for d in _draws(N, k):
        for i in range(len(d) - 1):
            g = d[i + 1] - d[i]
            counts[g] = counts.get(g, 0) + 1
        n_gaps += len(d) - 1
    return {g: c / n_gaps for g, c in counts.items()}


def _brute_min_gap(N, k):
    counts: dict[int, int] = {}
    for d in _draws(N, k):
        mg = min(d[i + 1] - d[i] for i in range(len(d) - 1))
        counts[mg] = counts.get(mg, 0) + 1
    denom = math.comb(N, k)
    return {m: c / denom for m, c in counts.items()}


def _brute_max_gap(N, k):
    counts: dict[int, int] = {}
    for d in _draws(N, k):
        mg = max(d[i + 1] - d[i] for i in range(len(d) - 1))
        counts[mg] = counts.get(mg, 0) + 1
    denom = math.comb(N, k)
    return {m: c / denom for m, c in counts.items()}


def _assert_matches(pmf, brute, abs_err=1e-12):
    assert set(pmf.index) == set(brute.keys())
    for key, p in brute.items():
        assert pmf.loc[key] == pytest.approx(p, abs=abs_err)


@pytest.mark.parametrize("N,k", SMALL_CASES)
class TestT2ExactVsBruteForce:
    def test_sum(self, N, k):
        _assert_matches(nr.sum_pmf(N, k), _brute_sum(N, k))

    def test_min(self, N, k):
        _assert_matches(nr.min_pmf(N, k), _brute_min(N, k))

    def test_max(self, N, k):
        _assert_matches(nr.max_pmf(N, k), _brute_max(N, k))

    def test_range(self, N, k):
        _assert_matches(nr.range_pmf(N, k), _brute_range(N, k))

    def test_hypergeom(self, N, k):
        K = N // 2
        _assert_matches(nr.hypergeom_pmf(N, K, k), _brute_hypergeom(N, K, k))

    def test_consecutive_pairs(self, N, k):
        _assert_matches(nr.consecutive_pairs_pmf(N, k), _brute_consecutive(N, k))

    def test_gap(self, N, k):
        _assert_matches(nr.gap_pmf(N, k), _brute_gap(N, k))

    def test_min_gap(self, N, k):
        _assert_matches(nr.min_gap_pmf(N, k), _brute_min_gap(N, k))

    def test_max_gap(self, N, k):
        _assert_matches(nr.max_gap_pmf(N, k), _brute_max_gap(N, k))


class TestT3KnownConstants:
    N, k = 55, 6

    def test_sum_pmf_sums_to_one_and_moments(self):
        pmf = nr.sum_pmf(self.N, self.k)
        assert pmf.sum() == pytest.approx(1.0, abs=1e-12)
        mean = (pmf.index.to_numpy() * pmf.to_numpy()).sum()
        var = ((pmf.index.to_numpy() - mean) ** 2 * pmf.to_numpy()).sum()
        assert mean == pytest.approx(168.0, abs=1e-9)
        assert var == pytest.approx(1372.0, abs=1e-6)

    def test_sum_pmf_symmetric(self):
        pmf = nr.sum_pmf(self.N, self.k)
        for s, p in pmf.items():
            mirror = 21 + 315 - s
            assert pmf.loc[mirror] == pytest.approx(p, abs=1e-12)

    def test_min_max_means(self):
        min_pmf = nr.min_pmf(self.N, self.k)
        max_pmf = nr.max_pmf(self.N, self.k)
        assert min_pmf.sum() == pytest.approx(1.0, abs=1e-12)
        assert max_pmf.sum() == pytest.approx(1.0, abs=1e-12)
        e_min = (min_pmf.index.to_numpy() * min_pmf.to_numpy()).sum()
        e_max = (max_pmf.index.to_numpy() * max_pmf.to_numpy()).sum()
        assert e_min == pytest.approx(8.0, abs=1e-9)
        assert e_max == pytest.approx(48.0, abs=1e-9)

    def test_range_mean(self):
        pmf = nr.range_pmf(self.N, self.k)
        assert pmf.sum() == pytest.approx(1.0, abs=1e-12)
        e_range = (pmf.index.to_numpy() * pmf.to_numpy()).sum()
        assert e_range == pytest.approx(40.0, abs=1e-9)

    def test_consecutive_pairs(self):
        pmf = nr.consecutive_pairs_pmf(self.N, self.k)
        assert pmf.sum() == pytest.approx(1.0, abs=1e-12)
        e_c = (pmf.index.to_numpy() * pmf.to_numpy()).sum()
        assert e_c == pytest.approx(6 / 11, abs=1e-9)
        assert pmf.loc[0] == pytest.approx(math.comb(50, 6) / math.comb(55, 6), abs=1e-12)

    def test_gap_mean(self):
        pmf = nr.gap_pmf(self.N, self.k)
        assert pmf.sum() == pytest.approx(1.0, abs=1e-12)
        e_gap = (pmf.index.to_numpy() * pmf.to_numpy()).sum()
        assert e_gap == pytest.approx(8.0, abs=1e-9)

    def test_module_constants(self):
        assert null_model.Q_PAIR == pytest.approx(1 / 99, abs=1e-15)
        assert null_model.P_NUMBER == pytest.approx(6 / 55, abs=1e-15)

    def test_geometric_mean_approx(self):
        pmf = nr.geometric_pmf(null_model.P_NUMBER, g_max=2000)
        mean = (pmf.index.to_numpy() * pmf.to_numpy()).sum()
        assert mean == pytest.approx(55 / 6, abs=1e-3)


def test_wilson_ci_hand_values():
    lo, hi = nr.wilson_ci(5, 10)
    assert lo == pytest.approx(0.2366, abs=1e-4)
    assert hi == pytest.approx(0.7634, abs=1e-4)
    lo0, hi0 = nr.wilson_ci(0, 10)
    assert lo0 == pytest.approx(0.0, abs=1e-4)
    assert hi0 == pytest.approx(0.2775, abs=1e-4)


def test_binomial_band_matches_scipy():
    from scipy.stats import binom
    lo, hi = nr.binomial_band(1190, 6 / 55)
    assert lo == binom.ppf(0.025, 1190, 6 / 55)
    assert hi == binom.ppf(0.975, 1190, 6 / 55)
