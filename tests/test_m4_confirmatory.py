"""Tests for src/statistics/confirmatory.py against SPECIFICATION.md v1.2.1 section 6.5
acceptance criteria. Seeds are fixed; a failure means investigate, never change the seed."""
from __future__ import annotations

import math
import random

import numpy as np
import pandas as pd
import pytest
from scipy.stats import hypergeom

from src.statistics import confirmatory as conf
from src.statistics import null_model
from src.transformation import tables

SEED = 20260924


# ---------------------------------------------------------------------------
# p formula
# ---------------------------------------------------------------------------

def test_p_formula_never_zero_and_matches_definition():
    reps = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    # T_obs above every replicate -> p = 1/(R+1)
    assert conf.simulated_p(100.0, reps) == pytest.approx(1 / 6)
    # T_obs equal to two replicates (>=), plus itself counted once
    assert conf.simulated_p(3.0, reps) == pytest.approx((1 + 3) / 6)
    # T_obs below every replicate -> p = 1
    assert conf.simulated_p(0.0, reps) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Holm hand example
# ---------------------------------------------------------------------------

def test_holm_hand_example():
    adj = conf.holm([0.01, 0.04, 0.03, 0.005])
    assert adj == pytest.approx([0.03, 0.06, 0.06, 0.02])


def test_holm_monotonic_and_capped_at_1():
    adj = conf.holm([0.5, 0.6, 0.9, 0.99])
    assert all(0 <= a <= 1 for a in adj)
    # sorted adjusted values must be non-decreasing
    order = np.argsort([0.5, 0.6, 0.9, 0.99])
    sorted_adj = np.array(adj)[order]
    assert np.all(np.diff(sorted_adj) >= -1e-12)


# ---------------------------------------------------------------------------
# Overlap moments (hypergeometric): mean 36/55, var 0.529146
# ---------------------------------------------------------------------------

def test_overlap_mean_and_variance_match_hypergeometric_enumeration():
    # |S_t ∩ S_{t-j}| ~ Hypergeometric(N=55, K=6, n=6): mean = 6*6/55, var per spec formula.
    dist = hypergeom(55, 6, 6)
    mean = dist.mean()
    var = dist.var()
    assert mean == pytest.approx(36 / 55, abs=1e-9)
    assert var == pytest.approx(conf.OVERLAP_VAR, abs=1e-9)
    assert conf.OVERLAP_VAR == pytest.approx(0.529146, abs=1e-6)


def test_overlap_mean_matches_brute_force_small_case():
    # Brute-force check with a smaller (N,k) using the exact enumeration logic of overlap.
    import itertools
    N, k = 10, 3
    subsets = list(itertools.combinations(range(1, N + 1), k))
    # mean overlap between two independent uniform k-subsets = k^2/N (hypergeometric mean)
    total = 0
    count = 0
    for a in subsets:
        for b in subsets:
            total += len(set(a) & set(b))
            count += 1
    brute_mean = total / count
    assert brute_mean == pytest.approx(k * k / N, abs=1e-9)


# ---------------------------------------------------------------------------
# FRESH null: mean X2_main ~= 49, mean X2_spec ~= 54 (R=10000, n=1190)
# ---------------------------------------------------------------------------

def test_fresh_null_x2_main_and_x2_spec_means():
    n = 1190
    R = 10_000
    rng = null_model.rng_for(9101, SEED)  # dedicated test-only stream, distinct from M4 streams
    p_num = 6 / 55
    e_main = n * p_num
    e_spec = n / 55

    x2_main = np.empty(R)
    x2_spec = np.empty(R)
    chunk = 500
    done = 0
    while done < R:
        c = min(chunk, R - done)
        main_flat, special_flat = null_model.simulate_draws(c * n, rng, chunk_size=min(c * n, 200_000))
        main = main_flat.reshape(c, n, 6)
        special = special_flat.reshape(c, n)
        for i in range(c):
            f = np.bincount(main[i].ravel(), minlength=56)[1:]
            x2_main[done + i] = np.sum((f - e_main) ** 2 / e_main)
            s = np.bincount(special[i], minlength=56)[1:]
            x2_spec[done + i] = np.sum((s - e_spec) ** 2 / e_spec)
        done += c

    assert x2_main.mean() == pytest.approx(49, abs=0.3)
    assert x2_spec.mean() == pytest.approx(54, abs=0.35)


# ---------------------------------------------------------------------------
# PERM null means: C7 X2 ~ (G-1)*49, C8 mean X2_w ~ 49*(1-W/n), on ONE fixed FRESH null dataset
# ---------------------------------------------------------------------------

def _fixed_fresh_dataset(n: int, seed: int, stream: int):
    rng = null_model.rng_for(stream, seed)
    main, special = null_model.simulate_draws(n, rng)
    return main, special


def test_perm_null_c7_and_c8_means_within_2pct():
    n = 1190
    main, _ = _fixed_fresh_dataset(n, SEED, stream=9102)
    ms = conf.main_stats(main)
    f_ref = ms.f.astype(float)

    # 9 roughly-equal year groups summing to n (synthetic, proportional)
    G = 9
    base = n // G
    sizes = [base] * G
    sizes[-1] += n - base * G

    windows = conf.rolling_windows(n)

    R = 4000
    x2_c7 = []
    x2w_means = []
    for perms in conf._perm_chunks(main, R, SEED, stream_id=9202, chunk_size=200):
        for i in range(perms.shape[0]):
            I_perm = ms.I[perms[i]]
            X2g, _ = conf.year_group_x2(I_perm, f_ref, n, sizes)
            x2_c7.append(X2g)
            x2w = conf.rolling_x2(I_perm, f_ref, n, windows)
            x2w_means.append(np.mean(x2w))

    mean_c7 = np.mean(x2_c7)
    mean_c8 = np.mean(x2w_means)
    expected_c7 = (G - 1) * 49
    expected_c8 = 49 * (1 - conf.ROLL_W / n)

    assert mean_c7 == pytest.approx(expected_c7, rel=0.02)
    assert mean_c8 == pytest.approx(expected_c8, rel=0.02)


# ---------------------------------------------------------------------------
# Chunk invariance
# ---------------------------------------------------------------------------

def test_fresh_chunks_invariant_to_chunk_size():
    n = 20
    R = 12
    outs = []
    for cs in (1, 5, 12):
        mains = []
        specials = []
        for m, s in conf._fresh_chunks(n, n, R, SEED, stream_id=9301, chunk_size=cs):
            mains.append(m)
            specials.append(s)
        outs.append((np.concatenate(mains, axis=0), np.concatenate(specials, axis=0)))
    for i in range(1, len(outs)):
        assert np.array_equal(outs[0][0], outs[i][0])
        assert np.array_equal(outs[0][1], outs[i][1])


def test_perm_chunks_invariant_to_chunk_size():
    n = 15
    main = np.arange(1, n * 6 + 1).reshape(n, 6) % 55 + 1
    R = 10
    outs = []
    for cs in (1, 4, 10):
        perms = []
        for p in conf._perm_chunks(main, R, SEED, stream_id=9302, chunk_size=cs):
            perms.append(p)
        outs.append(np.concatenate(perms, axis=0))
    for i in range(1, len(outs)):
        assert np.array_equal(outs[0], outs[i])


# ---------------------------------------------------------------------------
# Escalation trigger
# ---------------------------------------------------------------------------

def test_escalation_trigger_boundaries():
    lo, hi = conf.ESCALATE_LO, conf.ESCALATE_HI
    assert lo == 0.04 and hi == 0.06
    p_holm = pd.Series([0.01, 0.041, 0.5])
    assert bool(((p_holm >= lo) & (p_holm <= hi)).any()) is True
    p_holm2 = pd.Series([0.01, 0.5, 0.9])
    assert bool(((p_holm2 >= lo) & (p_holm2 <= hi)).any()) is False


# ---------------------------------------------------------------------------
# Small hand-computed pipeline sanity: known cell counts vs exact pmf on a tiny synthetic set
# ---------------------------------------------------------------------------

def test_pearson_cells_matches_hand_example():
    counts = np.array([1, 2, 3, 4])
    p = np.array([0.1, 0.2, 0.3, 0.4])
    n = 10
    X2, O, E = conf.pearson_cells(counts, p, n)
    E_expected = p * n
    assert np.allclose(E, E_expected)
    assert X2 == pytest.approx(np.sum((counts - E_expected) ** 2 / E_expected))


def test_runs_stat_hand_example():
    # y = [170, 168, 150, 200, 168, 100]; median=168 drops the two ties, leaving [150? no] check order
    y = np.array([170, 168, 150, 200, 168, 100])
    r = conf.runs_stat(y, median=168)
    # ties dropped, order kept: 170(>) , 150(<), 200(>), 100(<) -> a = [1,0,1,0]
    assert r["n_ties"] == 2
    assert r["n_plus"] == 2
    assert r["n_minus"] == 2
    assert r["runs"] == 4  # 1,0,1,0 alternates every step -> 4 runs
    assert r["mu"] == pytest.approx(1 + 2 * 2 * 2 / 4)
    assert r["T"] == pytest.approx(abs(4 - r["mu"]))


def test_ljung_box_hand_example_matches_manual_acf():
    y = np.array([1.0, 2.0, 3.0, 2.0, 1.0, 2.0, 3.0, 2.0, 1.0, 2.0])
    Q, r = conf.ljung_box(y, H=3)
    n = len(y)
    yc = y - y.mean()
    denom = (yc**2).sum()
    r1 = (yc[1:] * yc[:-1]).sum() / denom
    assert r[0] == pytest.approx(r1)
    assert Q == pytest.approx(n * (n + 2) * np.sum(r**2 / (n - np.arange(1, 4))))


def test_ks_D_against_known_uniform_case():
    # values uniform 1..10 (n=10000 replicated), cdf0 exact uniform on 1..10
    vals = np.tile(np.arange(1, 11), 1000)
    cdf0 = np.arange(1, 11) / 10
    D = conf.ks_D(vals, 1, 10, cdf0)
    assert D == pytest.approx(0.0, abs=1e-9)


def test_rolling_windows_covers_1190_with_13_windows():
    windows = conf.rolling_windows(1190)
    assert len(windows) == 13
    assert windows[0] == (0, 170)
    assert windows[-1][1] == 1190


# ---------------------------------------------------------------------------
# build_observed: year grouping and loader-level sanity on a tiny synthetic frame
# ---------------------------------------------------------------------------

def _synthetic_df(n: int, seed: int = 1) -> pd.DataFrame:
    rng = random.Random(seed)
    rows = []
    for i in range(1, n + 1):
        nums = sorted(rng.sample(range(1, 56), 6))
        remaining = [x for x in range(1, 56) if x not in nums]
        special = rng.choice(remaining)
        year = 2017 + (i - 1) // 20
        rows.append({
            "draw_id": f"{i:05d}", "draw_date": f"{year}-01-{(i % 27) + 1:02d}",
            "n1": nums[0], "n2": nums[1], "n3": nums[2], "n4": nums[3], "n5": nums[4], "n6": nums[5],
            "special_number": special,
        })
    return pd.DataFrame(rows)


def test_build_observed_year_groups_sum_to_n():
    df = _synthetic_df(400)
    obs = conf.build_observed(df, tables.MAIN_COLS)
    assert sum(obs.year_group_sizes) == 400
    assert obs.n == 400
    assert obs.n_prime == 400


def test_build_observed_rejects_non_monotonic_years():
    """n7: the real check is that the calendar year is non-decreasing in draw order."""
    df = _synthetic_df(40)
    # swap two rows' draw_date years to break monotonicity while keeping draw_id order.
    dates = df["draw_date"].tolist()
    dates[0], dates[-1] = dates[-1], dates[0]
    df["draw_date"] = dates
    with pytest.raises(ValueError, match="non-decreasing"):
        conf.build_observed(df, tables.MAIN_COLS)


def test_build_observed_accepts_monotonic_years():
    df = _synthetic_df(40)  # _synthetic_df already assigns years in non-decreasing blocks
    obs = conf.build_observed(df, tables.MAIN_COLS)
    assert obs.n == 40


# ---------------------------------------------------------------------------
# m4: cell pooling from the exact null pmf and n (not hardcoded), valid at n = 211 (replication)
# ---------------------------------------------------------------------------

def test_pooled_cells_valid_at_n_1190_reproduces_spec_table():
    from src.statistics import null_reference as nr
    n = 1190
    consec_cells = conf.pooled_cells(nr.consecutive_pairs_pmf(55, 6), n)
    labels = [c[0] for c in consec_cells]
    assert labels == ["0", "1", "2", ">=3"]
    probs = [c[3] for c in consec_cells]
    assert probs[0] == pytest.approx(0.548150, abs=1e-6)
    assert probs[1] == pytest.approx(0.365434, abs=1e-6)
    assert probs[2] == pytest.approx(0.079442, abs=1e-6)
    assert probs[3] == pytest.approx(0.006974, abs=1e-6)
    # odd/low need no pooling at n=1190 (section 6.2)
    odd_cells = conf.pooled_cells(nr.hypergeom_pmf(55, 28, 6), n)
    assert [c[0] for c in odd_cells] == [str(v) for v in range(0, 7)]
    low_cells = conf.pooled_cells(nr.hypergeom_pmf(55, 27, 6), n)
    assert [c[0] for c in low_cells] == [str(v) for v in range(0, 7)]


def test_pooled_cells_valid_at_n_211_replication():
    """m4: at the replication n=211, tail cells must merge inward so every cell has n*P >= 5."""
    from src.statistics import null_reference as nr
    n = 211
    for pmf in (nr.hypergeom_pmf(55, 28, 6), nr.hypergeom_pmf(55, 27, 6), nr.consecutive_pairs_pmf(55, 6)):
        cells = conf.pooled_cells(pmf, n)
        for label, lo, hi, p in cells:
            assert n * p >= 5.0 - 1e-9, f"cell {label} has n*P = {n*p} < 5"
        # probabilities still sum to 1
        assert sum(c[3] for c in cells) == pytest.approx(1.0, abs=1e-9)
    # this differs from the n=1190 cell set (at least one merge should have happened for consec)
    consec_211 = conf.pooled_cells(nr.consecutive_pairs_pmf(55, 6), n)
    consec_1190 = conf.pooled_cells(nr.consecutive_pairs_pmf(55, 6), 1190)
    assert [c[0] for c in consec_211] != [c[0] for c in consec_1190]


def test_pooled_cells_probs_sum_to_one_and_cover_support():
    from src.statistics import null_reference as nr
    for n in (60, 211, 300, 980, 1190):
        pmf = nr.hypergeom_pmf(55, 28, 6)
        cells = conf.pooled_cells(pmf, n)
        assert sum(c[3] for c in cells) == pytest.approx(1.0, abs=1e-9)
        assert cells[0][1] == 0
        assert cells[-1][2] == 6


# ---------------------------------------------------------------------------
# Calibration (slow): section 6.5, "Acceptance criteria for src/statistics (null-only tests)".
#
# 400 synthetic FRESH null datasets, n = 300, inner R = 199, proportional synthetic year labels.
# Each C-test must reject at 0.05 at a rate in [0.0175, 0.090] (99.9% binomial bounds), and the
# Holm family FWER must be <= 0.090. The seed is fixed here; a failure means investigate, never
# change the seed.
# ---------------------------------------------------------------------------

CALIB_SEED = 20260924
CALIB_N = 300
CALIB_R_INNER = 199
CALIB_N_OUTER = 400
CALIB_LO = 0.0175
CALIB_HI = 0.090
CALIB_FWER_HI = 0.090

# Proportional synthetic year labels: the real 00001-01190 per-calendar-year draw counts
# (2017..2025 = 66,155,156,145,144,156,155,156,57; sum 1190, per `outputs/eda/through_01190`),
# scaled proportionally to n = 300 and rounded to integers summing to exactly 300. This is a fixed
# constant, not a read of real data at test time.
_REAL_YEAR_COUNTS_1190 = [66, 155, 156, 145, 144, 156, 155, 156, 57]


def _proportional_year_sizes(n: int, real_counts: list[int]) -> list[int]:
    total = sum(real_counts)
    raw = [n * c / total for c in real_counts]
    sizes = [int(math.floor(x)) for x in raw]
    remainder = n - sum(sizes)
    order = sorted(range(len(raw)), key=lambda i: -(raw[i] - sizes[i]))
    for i in range(remainder):
        sizes[order[i % len(order)]] += 1
    assert sum(sizes) == n
    return sizes


CALIB_YEAR_SIZES = _proportional_year_sizes(CALIB_N, _REAL_YEAR_COUNTS_1190)
CALIB_YEAR_LABELS = [str(2017 + i) for i in range(len(CALIB_YEAR_SIZES))]


@pytest.mark.slow
def test_calibration_rejection_rates():
    outer_rng = null_model.rng_for(90_500, CALIB_SEED)  # dedicated calibration-only stream

    reject_counts = {}
    seen_ids = None
    family_reject_any = 0

    for outer in range(CALIB_N_OUTER):
        main, special = null_model.simulate_draws(CALIB_N, outer_rng)
        obs = conf.ObservedData(
            main=main, special=special, special_present=np.ones(CALIB_N, dtype=bool),
            n=CALIB_N, n_prime=CALIB_N,
            year_group_sizes=CALIB_YEAR_SIZES, year_labels=CALIB_YEAR_LABELS,
        )
        # Distinct, deterministic inner streams per outer replicate (far from every real M4/M3/test
        # stream used elsewhere), so each of the 400 calibration replicates gets its own inner
        # FRESH/PERM reference sample rather than reusing one fixed sample 400 times.
        fresh_stream = 200_000 + 2 * outer
        perm_stream = 200_001 + 2 * outer
        run = conf.run_family(obs, R=CALIB_R_INNER, seed=CALIB_SEED,
                               fresh_stream=fresh_stream, perm_stream=perm_stream)

        ids = [t.id for t in run.family]
        if seen_ids is None:
            seen_ids = ids
            for tid in ids:
                reject_counts[tid] = 0
        else:
            assert ids == seen_ids, "family membership must be identical across calibration replicates"

        # Per-test calibration uses the RAW simulated p (marginal type-I check on p_sim itself);
        # at m=12 and inner R=199 the smallest achievable *Holm-adjusted* p is m/(R+1) = 0.06 > 0.05,
        # so no test could ever reject under Holm at this R, making a Holm-based per-test rate
        # structurally always 0 regardless of correctness. The Holm-adjusted p is used only for the
        # separate family-wise (FWER) bound below, per SPECIFICATION section 6.5's two-part
        # criterion ("each C-test rejects at 0.05 ... and the Holm family FWER is <= 0.090").
        p_holm = conf.holm([t.p_sim for t in run.family])
        any_reject = False
        for t, ph in zip(run.family, p_holm):
            if t.p_sim <= 0.05:
                reject_counts[t.id] += 1
            if ph <= 0.05:
                any_reject = True
        if any_reject:
            family_reject_any += 1

    rates = {tid: cnt / CALIB_N_OUTER for tid, cnt in reject_counts.items()}
    fwer = family_reject_any / CALIB_N_OUTER

    print(f"\ncalibration rates (raw p<=0.05, n_outer={CALIB_N_OUTER}): "
          + ", ".join(f"{tid}={rates[tid]:.4f}" for tid in sorted(rates)))
    print(f"calibration Holm family FWER: {fwer:.4f}")

    out_of_bounds = {tid: rate for tid, rate in rates.items() if not (CALIB_LO <= rate <= CALIB_HI)}
    assert not out_of_bounds, f"calibration rejection rates out of [{CALIB_LO}, {CALIB_HI}]: {out_of_bounds} (full rates: {rates})"
    assert fwer <= CALIB_FWER_HI, f"Holm family FWER {fwer} exceeds {CALIB_FWER_HI} (rates: {rates})"


def test_run_family_small_smoke():
    """A small end-to-end smoke run (R small) to catch integration errors; not a calibration check."""
    df = _synthetic_df(60)
    obs = conf.build_observed(df, tables.MAIN_COLS)
    run = conf.run_family(obs, R=30, seed=SEED, fresh_stream=9401, perm_stream=9402)
    # C8 is not applicable on this tiny n (fewer than 3 rolling windows of W=170 fit); m drops to 12.
    assert len(run.family) == 12
    assert {t.id for t in run.family} == {"C1", "C2", "C3", "C4", "C5", "C6", "C7", "C9", "C10", "C11", "C12", "C13"}
    for t in run.family:
        assert 0 < t.p_sim <= 1
    for tid, fu in run.followups.items():
        assert "p_raw" in fu.columns and "p_holm" in fu.columns
