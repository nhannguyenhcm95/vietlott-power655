"""T1, T6, T7, T13: draw metrics hand examples, number/pair level, pooling and partial periods."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from src.statistics import eda, null_reference as nr


def _frame(rows):
    """rows: list of (draw_id, draw_date, main_tuple, special)."""
    data = []
    for draw_id, d, main, special in rows:
        row = {"draw_id": draw_id, "draw_date": d}
        for i, v in enumerate(main, start=1):
            row[f"n{i}"] = v
        row["special_number"] = special
        data.append(row)
    df = pd.DataFrame(data)
    df["t"] = range(1, len(df) + 1)
    return df


# ---------------------------------------------------------------------------
# T1
# ---------------------------------------------------------------------------

def test_t1_hand_example_1():
    df = _frame([("00001", "2017-08-01", (1, 2, 3, 53, 54, 55), 10)])
    m = eda.draw_metrics(df)
    row = m.iloc[0]
    assert row["sum"] == 168
    assert row["min"] == 1 and row["max"] == 55 and row["range"] == 54
    assert row["odd_count"] == 4
    assert row["low_count"] == 3
    assert row["consecutive_pairs"] == 4
    assert [row[f"gap_{i}"] for i in range(1, 6)] == [1, 1, 50, 1, 1]
    assert row["max_gap"] == 50 and row["min_gap"] == 1


def test_t1_hand_example_2():
    df = _frame([("00001", "2017-08-01", (5, 10, 14, 23, 24, 38), 35)])
    m = eda.draw_metrics(df)
    row = m.iloc[0]
    assert row["sum"] == 114
    assert row["range"] == 33
    assert row["odd_count"] == 2
    assert row["low_count"] == 5
    assert row["consecutive_pairs"] == 1
    assert [row[f"gap_{i}"] for i in range(1, 6)] == [5, 4, 9, 1, 14]


# ---------------------------------------------------------------------------
# T6: number level hand fixture
# ---------------------------------------------------------------------------

FIXTURE_ROWS = [
    ("00001", "2017-08-01", (1, 2, 3, 4, 5, 6), 10),
    ("00002", "2017-08-03", (1, 7, 8, 9, 10, 11), 12),
    ("00003", "2017-08-05", (2, 7, 12, 13, 14, 15), 20),
    ("00004", "2017-08-08", (16, 17, 18, 19, 20, 21), 30),
    ("00005", "2017-08-10", (1, 2, 22, 23, 24, 25), 40),
    ("00006", "2017-08-12", (7, 26, 27, 28, 29, 30), 50),
]


def test_t6_number_frequency_and_wilson():
    df = _frame(FIXTURE_ROWS)
    freq = eda.number_frequency(df)
    row1 = freq[freq.number == 1].iloc[0]
    assert row1["count"] == 3  # appears in draws 1, 2, 5
    row7 = freq[freq.number == 7].iloc[0]
    assert row7["count"] == 3  # draws 2, 3, 6

    lo, hi = nr.wilson_ci(5, 10)
    assert lo == pytest.approx(0.2366, abs=1e-4)
    assert hi == pytest.approx(0.7634, abs=1e-4)
    lo0, hi0 = nr.wilson_ci(0, 10)
    assert lo0 == pytest.approx(0.0, abs=1e-4)
    assert hi0 == pytest.approx(0.2775, abs=1e-4)


def test_t6_period_counts():
    df = _frame(FIXTURE_ROWS)
    period = eda.number_frequency_by_period(df)
    years = period[period.period_type == "year"]
    assert set(years["period"]) == {"2017"}
    total_count_number1 = years[years.number == 1]["count"].iloc[0]
    assert total_count_number1 == 3


def test_t6_rolling_counts_sum_to_6w():
    df = _frame(FIXTURE_ROWS)
    W = 3
    rolling = eda.rolling_number_counts(df, W)
    for window_end, g in rolling.groupby("window_end_draw_id"):
        assert g["count"].sum() == 6 * W


def test_t6_interarrival_gaps_hand_fixture():
    # number appears at ordinals 2, 5, 6 out of n=6 draws -> gaps [3,1], censored gaps excluded
    rows = [
        ("00001", "2017-08-01", (10, 11, 12, 13, 14, 15), 1),
        ("00002", "2017-08-03", (1, 20, 21, 22, 23, 24), 2),
        ("00003", "2017-08-05", (30, 31, 32, 33, 34, 35), 3),
        ("00004", "2017-08-08", (36, 37, 38, 39, 40, 41), 4),
        ("00005", "2017-08-10", (1, 42, 43, 44, 45, 46), 5),
        ("00006", "2017-08-12", (1, 47, 48, 49, 50, 51), 6),
    ]
    df = _frame(rows)
    n = len(df)
    main = df[eda.MAIN_COLS].to_numpy()
    present = (main == 1).any(axis=1)
    ords = np.arange(1, n + 1)[present]
    gaps = np.diff(ords).tolist()
    assert gaps == [3, 1]

    interarrival = eda.interarrival_gaps(df)
    # cell "1" should have observed_count 1 (the single gap of length 1); no cell for length 3
    # should exceed the actual pooled count present for this tiny fixture (g0 collapses quickly).
    total_observed = interarrival["observed_count"].sum()
    assert total_observed == 2  # exactly the two uncensored gaps [3, 1] found above


def test_t6_interarrival_e_g_matches_enumeration_and_simulation():
    """F5: E_g must match brute-force enumeration for a tiny (N, k, n) and a null simulation for
    a larger n, not merely be >= 0."""
    import itertools
    import math

    # Brute force over a tiny universe: N=6 numbers, k=2 per draw, n=3 draws.
    N, k, n = 6, 2, 3
    draws_space = list(itertools.combinations(range(1, N + 1), k))
    total_gap_counts = {g: 0 for g in range(1, n)}
    total_sequences = 0
    for seq in itertools.product(draws_space, repeat=n):
        total_sequences += 1
        for number in range(1, N + 1):
            ords = [t + 1 for t, draw in enumerate(seq) if number in draw]
            for a, b in zip(ords, ords[1:]):
                g = b - a
                if g in total_gap_counts:
                    total_gap_counts[g] += 1
    p = k / N
    for g in range(1, n):
        expected_formula = N * (n - g) * p**2 * (1 - p) ** (g - 1)
        expected_brute = total_gap_counts[g] / total_sequences
        assert expected_formula == pytest.approx(expected_brute, abs=1e-9)

    # Null simulation check at a larger n (matches the review's suggested n=300, R>=300).
    from src.statistics import null_model
    n_sim, reps = 300, 300
    p_real = eda.P_NUMBER
    sim_counts = {g: 0 for g in (1, 2, 10, 20)}
    for rep in range(reps):
        rng = null_model.rng_for(stream_id=900_000 + rep)
        main_sim, _ = null_model.simulate_draws(n_sim, rng)
        t = np.arange(1, n_sim + 1)
        for number in range(1, 56):
            present = (main_sim == number).any(axis=1)
            ords = t[present]
            if len(ords) >= 2:
                for g in np.diff(ords):
                    if g in sim_counts:
                        sim_counts[g] += 1
    for g, count in sim_counts.items():
        sim_mean = count / reps
        e_g = 55 * (n_sim - g) * p_real**2 * (1 - p_real) ** (g - 1)
        se = math.sqrt(e_g)  # approx Poisson-like MC standard error for a count statistic
        assert abs(sim_mean - e_g) < 4 * se


def test_t6_first_last_and_cumulative():
    df = _frame(FIXTURE_ROWS)
    appearance = eda.appearance_summary(df)
    row1 = appearance[appearance.number == 1].iloc[0]
    assert row1["first_draw_id"] == "00001"
    assert row1["last_draw_id"] == "00005"

    cum = eda.cumulative_counts(df)
    last_row = cum[(cum.draw_id == "00006") & (cum.number == 1)].iloc[0]
    assert last_row["cumulative_count"] == 3


# ---------------------------------------------------------------------------
# T7: pair level
# ---------------------------------------------------------------------------

def test_t7_pair_matrix_symmetric_properties():
    df = _frame(FIXTURE_ROWS)
    pairs = eda.pair_cooccurrence(df)
    n_draws = len(df)
    assert pairs["count"].sum() == 15 * n_draws  # C(6,2) pairs per draw
    # diagonal = fk check via number_frequency
    freq = eda.number_frequency(df)
    for number in range(1, 56):
        expected_row_sum = freq[freq.number == number]["count"].iloc[0] * 5
        row_sum = pairs[(pairs.number_i == number) | (pairs.number_j == number)]["count"].sum()
        assert row_sum == expected_row_sum


def test_t7_stability_r_one_for_identical_blocks():
    # build 10 identical draws split into 2 blocks of 5 identical composition each
    rows = []
    for i in range(1, 11):
        rows.append((f"{i:05d}", "2017-08-01", (1, 2, 3, 4, 5, 6), 10))
    df = _frame(rows)
    stability = eda.block_stability(df, n_blocks=2)
    for _, row in stability.iterrows():
        assert row["pearson_r"] == pytest.approx(1.0, abs=1e-9) or math.isnan(row["pearson_r"])


# ---------------------------------------------------------------------------
# T13: pooling and partial periods
# ---------------------------------------------------------------------------

def _all_metric_unit_specs():
    """(metric, units, n_obs) for all 10 draw metrics, matching draw_metric_distribution's own
    construction (F1: extend the invariant check to every metric, not just min_pmf)."""
    return [
        ("sum", eda._sum_bin_units(nr.sum_pmf())),
        ("min", eda._pmf_to_units(nr.min_pmf())),
        ("max", eda._pmf_to_units(nr.max_pmf())),
        ("range", eda._pmf_to_units(nr.range_pmf())),
        ("odd_count", eda._pmf_to_units(nr.hypergeom_pmf(55, 28, 6))),
        ("low_count", eda._pmf_to_units(nr.hypergeom_pmf(55, 27, 6))),
        ("gap", eda._pmf_to_units(nr.gap_pmf())),
        ("max_gap", eda._pmf_to_units(nr.max_gap_pmf())),
        ("min_gap", eda._pmf_to_units(nr.min_gap_pmf())),
    ]


@pytest.mark.parametrize("n_draws", [980, 1190])
def test_t13_pooled_cells_sum_to_one_and_meet_threshold(n_draws):
    """F1: the pooling invariant (every cell's own n*P >= 5) must hold for all 10 metrics at the
    real n's, not just min_pmf. `gap` uses n_obs = 5*n_draws (5 spacings per draw)."""
    for metric, units in _all_metric_unit_specs():
        n_obs = n_draws * 5 if metric == "gap" else n_draws
        cells = eda._pool_cells(units, n_obs)
        total = sum(c["null_prob"] for c in cells)
        assert total == pytest.approx(1.0, abs=1e-9), metric
        for c in cells:
            assert c["expected_count"] >= 5.0 - 1e-9 or len(cells) == 1, (metric, c)

    # consecutive_pairs uses fixed_cells, not _pool_cells, but its cells must also clear 5 at
    # both n's per spec section 3.1 (n*P(>=3) = 6.8 at n=980, 8.3 at n=1190).
    pmf = nr.consecutive_pairs_pmf()
    values = np.array([0, 1, 2, 3, 4, 5])
    rows = eda._metric_distribution_rows(
        "consecutive_pairs", values, pmf, n_draws, fixed_cells=[(0, 0), (1, 1), (2, 2), (3, None)],
    )
    for r in rows:
        assert r["expected_count"] >= 5.0 - 1e-9


def test_t13_pooling_identical_for_same_n_different_draws():
    """F5: run draw_metric_distribution on two fixtures with the same n but different observed
    draws, and assert the null-derived columns (cell, null_prob, expected_count) are identical,
    since pooling depends only on the null pmf and n, never on observed data."""
    rows_a = [(f"{i:05d}", "2017-08-01", tuple(sorted(((i * 7 + j) % 55) + 1 for j in range(6))), 1)
              for i in range(1, 51)]
    rows_b = [(f"{i:05d}", "2017-08-01", tuple(sorted(((i * 13 + 3 * j) % 55) + 1 for j in range(6))), 2)
              for i in range(1, 51)]
    # ensure each row has 6 distinct ascending numbers
    def _fix(rows):
        fixed = []
        for draw_id, d, main, special in rows:
            uniq = sorted(set(main))
            while len(uniq) < 6:
                cand = (uniq[-1] % 55) + 1
                if cand not in uniq:
                    uniq.append(cand)
                uniq = sorted(set(uniq))
            fixed.append((draw_id, d, tuple(uniq[:6]), special))
        return fixed

    df_a = _frame(_fix(rows_a))
    df_b = _frame(_fix(rows_b))
    assert len(df_a) == len(df_b) == 50

    dist_a = eda.draw_metric_distribution(eda.draw_metrics(df_a), len(df_a))
    dist_b = eda.draw_metric_distribution(eda.draw_metrics(df_b), len(df_b))
    pd.testing.assert_frame_equal(
        dist_a[["metric", "cell", "null_prob", "expected_count", "null_lo", "null_hi", "reference"]],
        dist_b[["metric", "cell", "null_prob", "expected_count", "null_lo", "null_hi", "reference"]],
    )

    interarrival_a = eda.interarrival_gaps(df_a)
    interarrival_b = eda.interarrival_gaps(df_b)
    pd.testing.assert_frame_equal(
        interarrival_a[["cell", "expected_count", "null_share"]],
        interarrival_b[["cell", "expected_count", "null_share"]],
    )


def test_f2_draw_metric_distribution_cells_ordered_numerically():
    """F2: within each metric, cells run lower-pooled-tail, then numeric cells in order, then
    upper-pooled-tail - never lexicographic."""
    def cell_sort_key(cell: str):
        if cell.startswith("<="):
            return (-1, int(cell[2:]))
        if cell.startswith(">="):
            return (1, int(cell[2:]))
        if "-" in cell[1:]:
            return (0, int(cell.split("-")[0]))
        return (0, int(cell))

    for n_draws in (980, 1190):
        # a deterministic, RNG-free generator that always yields 6 distinct ascending numbers
        rows = []
        for i in range(1, n_draws + 1):
            start = (i * 7) % 50 + 1
            nums = sorted({((start + j * 3 - 1) % 55) + 1 for j in range(6)})
            j = 6
            while len(nums) < 6:
                cand = ((start + j) % 55) + 1
                if cand not in nums:
                    nums.append(cand)
                nums = sorted(set(nums))
                j += 1
            rows.append((f"{i:05d}", "2017-08-01", tuple(sorted(nums)[:6]), 1))
        df = _frame(rows)
        dist = eda.draw_metric_distribution(eda.draw_metrics(df), n_draws)
        for metric in dist["metric"].unique():
            sub = dist[dist["metric"] == metric]
            keys = [cell_sort_key(c) for c in sub["cell"]]
            assert keys == sorted(keys), (metric, list(sub["cell"]))
            cells = list(sub["cell"])
            if len(cells) > 1:
                # if the low end is pooled it must be the first row; if the high end is pooled
                # it must be the last row (never mid-table, as the lexicographic bug produced).
                pooled_lo = [c for c in cells if c.startswith("<=")]
                pooled_hi = [c for c in cells if c.startswith(">=")]
                if pooled_lo:
                    assert cells[0] == pooled_lo[0]
                if pooled_hi:
                    assert cells[-1] == pooled_hi[0]


def test_t13_consecutive_pairs_cells_fixed():
    pmf = nr.consecutive_pairs_pmf()
    for n in (980, 1190):
        values = np.array([0, 1, 2, 3, 4, 5])
        rows = eda._metric_distribution_rows(
            "consecutive_pairs", values, pmf, n, fixed_cells=[(0, 0), (1, 1), (2, 2), (3, None)],
        )
        cells = [r["cell"] for r in rows]
        assert cells == ["0", "1", "2", ">=3"]


def test_t13_sum_bin_probs_equal_exact_pmf_sums():
    pmf = nr.sum_pmf()
    units = eda._sum_bin_units(pmf)
    total = sum(u["prob"] for u in units)
    assert total == pytest.approx(1.0, abs=1e-9)
    for u in units:
        expected = float(pmf[(pmf.index >= u["lo"]) & (pmf.index <= u["hi"])].sum())
        assert u["prob"] == pytest.approx(expected, abs=1e-12)


def test_t13_partial_flags_real_range():
    from src.transformation import tables
    fact = tables.read_fact_draw("data/curated")
    fact = fact[fact["draw_id"] <= "01190"].copy()
    fact["t"] = range(1, len(fact) + 1)
    period = eda.number_frequency_by_period(fact)
    years = period[period.period_type == "year"].drop_duplicates("period")
    partial_years = set(years[years.partial]["period"])
    assert partial_years == {"2017", "2025"}
    non_partial = set(years[~years.partial]["period"])
    assert non_partial == {"2018", "2019", "2020", "2021", "2022", "2023", "2024"}
