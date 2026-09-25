"""M3 EDA charts (spec section 5). One function per PNG. Agg backend, fixed figsize/dpi=120.

Every chart draws its null reference (an expected line/bars plus a band); the caption states
whether the reference is exact or MC(R, seed).
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.statistics import eda as stat_eda

FIGSIZE = (9, 5.5)
DPI = 120
SAVE_KWARGS = dict(dpi=DPI, metadata={"Software": None})


def _save(fig, path: Path) -> Path:
    fig.savefig(path, **SAVE_KWARGS)
    plt.close(fig)
    return path


def draw_sum_chart(dist: pd.DataFrame, path: Path, reps: int, seed: int) -> Path:
    sub = dist[dist["metric"] == "sum"].copy()
    fig, ax = plt.subplots(figsize=FIGSIZE)
    x = np.arange(len(sub))
    ax.bar(x, sub["observed_count"], color="tab:blue", alpha=0.7, label="observed")
    ax.plot(x, sub["expected_count"], color="black", marker="o", markersize=3, label="null expected (exact)")
    ax.fill_between(x, sub["null_lo"], sub["null_hi"], color="black", alpha=0.15, label="pointwise band")
    ax.set_xticks(x)
    ax.set_xticklabels(sub["cell"], rotation=90, fontsize=6)
    ax.set_title("Draw sum, width-10 bins (null: exact)")
    ax.set_xlabel("sum bin")
    ax.set_ylabel("count")
    ax.legend(fontsize=8)
    fig.tight_layout()
    return _save(fig, path)


def draw_min_max_range_chart(dist: pd.DataFrame, path: Path) -> Path:
    fig, axes = plt.subplots(1, 3, figsize=FIGSIZE)
    for ax, metric in zip(axes, ["min", "max", "range"]):
        # dist rows are already sorted numerically (lower pooled tail, numeric cells, upper
        # pooled tail) by draw_metric_distribution; charts must not re-sort (F2).
        sub = dist[dist["metric"] == metric]
        ax.bar(sub["cell"], sub["observed_count"], color="tab:blue", alpha=0.7)
        ax.plot(sub["cell"], sub["expected_count"], color="black", marker="o", markersize=2)
        ax.fill_between(range(len(sub)), sub["null_lo"], sub["null_hi"], color="black", alpha=0.15)
        ax.set_title(metric)
        ax.tick_params(axis="x", labelrotation=90, labelsize=5)
    fig.suptitle("Draw min/max/range (null: exact)")
    fig.tight_layout()
    return _save(fig, path)


def draw_odd_low_consecutive_chart(dist: pd.DataFrame, path: Path) -> Path:
    fig, axes = plt.subplots(1, 3, figsize=FIGSIZE)
    for ax, metric in zip(axes, ["odd_count", "low_count", "consecutive_pairs"]):
        sub = dist[dist["metric"] == metric].copy()
        ax.bar(sub["cell"], sub["observed_count"], color="tab:blue", alpha=0.7)
        ax.plot(sub["cell"], sub["expected_count"], color="black", marker="o", markersize=3)
        ax.fill_between(range(len(sub)), sub["null_lo"], sub["null_hi"], color="black", alpha=0.15)
        ax.set_title(metric)
    fig.suptitle("Draw odd/low/consecutive counts (null: exact)")
    fig.tight_layout()
    return _save(fig, path)


def draw_gaps_chart(dist: pd.DataFrame, path: Path) -> Path:
    # F8: the pooled `gap` band is exact_pmf_approx_band (its 5 spacings per draw are dependent),
    # while `max_gap` stays exact; label each subplot with its own reference.
    titles = {"gap": "within_draw_gap (exact pmf, approximate band)", "max_gap": "max_gap (exact)"}
    fig, axes = plt.subplots(1, 2, figsize=FIGSIZE)
    for ax, metric in zip(axes, ["gap", "max_gap"]):
        # dist rows are already sorted numerically; charts must not re-sort (F2).
        sub = dist[dist["metric"] == metric]
        ax.bar(sub["cell"], sub["observed_count"], color="tab:blue", alpha=0.7)
        ax.plot(sub["cell"], sub["expected_count"], color="black", marker="o", markersize=2)
        ax.fill_between(range(len(sub)), sub["null_lo"], sub["null_hi"], color="black", alpha=0.15)
        ax.set_title(titles[metric])
        ax.tick_params(axis="x", labelrotation=90, labelsize=5)
    fig.suptitle("Within-draw gaps: pooled spacing and max_gap")
    fig.tight_layout()
    return _save(fig, path)


def number_frequency_chart(freq: pd.DataFrame, path: Path, reps: int, seed: int) -> Path:
    fig, ax = plt.subplots(figsize=FIGSIZE)
    ax.bar(freq["number"], freq["count"], color="tab:blue", alpha=0.7, label="observed")
    ax.axhline(freq["expected"].iloc[0], color="black", label="null expected (exact)")
    ax.fill_between(freq["number"], freq["null_lo"], freq["null_hi"], color="black", alpha=0.15, label="pointwise band")
    ax.fill_between(freq["number"], freq["sim_lo"], freq["sim_hi"], color="tab:orange", alpha=0.12,
                     label=f"simultaneous band (MC(R={reps}, seed={seed}))")
    ax.set_xlabel("number (1..55)")
    ax.set_ylabel("count")
    ax.set_title(f"Number frequency (null: exact pointwise, MC(R={reps}, seed={seed}) simultaneous)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    return _save(fig, path)


def number_frequency_by_year_chart(freq_period: pd.DataFrame, path: Path) -> Path:
    years = freq_period[freq_period["period_type"] == "year"]
    pivot = years.pivot(index="number", columns="period", values="z").sort_index()
    fig, ax = plt.subplots(figsize=FIGSIZE)
    im = ax.imshow(pivot.to_numpy(), aspect="auto", cmap="RdBu_r", vmin=-4, vmax=4)
    ax.set_yticks(range(0, 55, 5))
    ax.set_yticklabels(pivot.index[::5])
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns, rotation=90, fontsize=6)
    ax.set_xlabel("year")
    ax.set_ylabel("number")
    ax.set_title("Number frequency by year, standardized z (null: exact, fixed scale +/-4)")
    fig.colorbar(im, ax=ax, label="z")
    fig.tight_layout()
    return _save(fig, path)


def number_rolling_chart(ext: pd.DataFrame, w: int, path: Path, reps: int, seed: int) -> Path:
    fig, ax = plt.subplots(figsize=FIGSIZE)
    x = range(len(ext))
    ax.plot(x, ext["max_z"], color="tab:red", linewidth=0.8, label="max z over numbers")
    ax.plot(x, ext["min_z"], color="tab:blue", linewidth=0.8, label="min z over numbers")
    ax.axhline(ext["mc_max_z_q975"].iloc[0], color="black", linestyle="--", label="MC pointwise envelope (97.5%)")
    ax.axhline(ext["mc_min_z_q025"].iloc[0], color="black", linestyle="--", label="MC pointwise envelope (2.5%)")
    ax.set_xlabel("rolling window (ordered by window_end_draw_id)")
    ax.set_ylabel("z")
    ax.set_title(f"Rolling number counts, W={w}: pointwise envelope, MC(R={reps}, seed={seed}) "
                 f"(≈2.5% of windows outside on each side by chance)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    return _save(fig, path)


def number_cumulative_deviation_chart(cumulative: pd.DataFrame, n: int, path: Path) -> Path:
    p = stat_eda.P_NUMBER
    fig, ax = plt.subplots(figsize=FIGSIZE)
    t = np.arange(1, n + 1)
    for number in range(1, 56):
        sub = cumulative[cumulative["number"] == number].sort_values("draw_id")
        deviation = sub["cumulative_count"].to_numpy() - sub["expected"].to_numpy()
        ax.plot(t, deviation, color="grey", alpha=0.25, linewidth=0.5)
    band = 1.96 * np.sqrt(t * p * (1 - p))
    ax.plot(t, band, color="black", linewidth=1.0, label="+/-1.96*sqrt(t*p*(1-p))")
    ax.plot(t, -band, color="black", linewidth=1.0)
    ax.set_xlabel("t (draw ordinal)")
    ax.set_ylabel("cumulative_count(t) - t*p (deviation)")
    ax.set_title("Cumulative count deviation, all 55 numbers (null: exact)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    return _save(fig, path)


def number_interarrival_chart(interarrival: pd.DataFrame, path: Path) -> Path:
    fig, ax = plt.subplots(figsize=FIGSIZE)
    x = range(len(interarrival))
    ax.bar(x, interarrival["observed_count"], color="tab:blue", alpha=0.7, label="observed")
    ax.plot(x, interarrival["expected_count"], color="black", marker="o", markersize=3, label="null expected (exact E_g)")
    ax.set_xticks(list(x))
    ax.set_xticklabels(interarrival["cell"], rotation=90, fontsize=6)
    ax.set_xlabel("gap cell")
    ax.set_ylabel("count")
    ax.set_title("Inter-arrival gaps, pooled over numbers (null: exact)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    return _save(fig, path)


def special_frequency_chart(special: pd.DataFrame, path: Path, reps: int, seed: int) -> Path:
    fig, ax = plt.subplots(figsize=FIGSIZE)
    ax.bar(special["number"], special["count"], color="tab:blue", alpha=0.7, label="observed")
    ax.axhline(special["expected"].iloc[0], color="black", label="null expected (exact)")
    ax.fill_between(special["number"], special["null_lo"], special["null_hi"], color="black", alpha=0.15, label="pointwise band")
    ax.fill_between(special["number"], special["sim_lo"], special["sim_hi"], color="tab:orange", alpha=0.12,
                     label=f"simultaneous band (MC(R={reps}, seed={seed}))")
    ax.set_xlabel("number (1..55)")
    ax.set_ylabel("count")
    ax.set_title(f"Special number frequency (null: exact pointwise, MC(R={reps}, seed={seed}) simultaneous)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    return _save(fig, path)


def pair_cooccurrence_heatmap_chart(pairs: pd.DataFrame, path: Path) -> Path:
    mat = np.full((55, 55), np.nan)
    for row in pairs.itertuples(index=False):
        i, j = int(row.number_i) - 1, int(row.number_j) - 1
        mat[i, j] = row.z
        mat[j, i] = row.z
    fig, ax = plt.subplots(figsize=FIGSIZE)
    im = ax.imshow(mat, cmap="RdBu_r", vmin=-4, vmax=4)
    ax.set_title("Pair co-occurrence, standardized z (null: exact, fixed scale +/-4)")
    ax.set_xlabel("number j")
    ax.set_ylabel("number i")
    fig.colorbar(im, ax=ax, label="z")
    fig.tight_layout()
    return _save(fig, path)


def pair_count_distribution_chart(pair_dist: pd.DataFrame, path: Path) -> Path:
    fig, ax = plt.subplots(figsize=FIGSIZE)
    ax.bar(pair_dist["count"], pair_dist["observed_pairs"], color="tab:blue", alpha=0.7, label="observed")
    ax.plot(pair_dist["count"], pair_dist["expected_pairs"], color="black", marker="o", markersize=3,
            label="null expected (Binomial(n, 1/99))")
    ax.set_xlabel("pair count")
    ax.set_ylabel("number of pairs")
    ax.set_title("Pair count distribution (null: exact Binomial(n, 1/99))")
    ax.legend(fontsize=8)
    fig.tight_layout()
    return _save(fig, path)


def stability_blocks_chart(stability: pd.DataFrame, path: Path, reps: int, seed: int) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=FIGSIZE, sharey=True)
    for ax, level in zip(axes, ["number", "pair"]):
        sub = stability[stability["level"] == level].copy()
        labels = sub["block_a"].astype(str) + "-" + sub["block_b"].astype(str)
        x = range(len(sub))
        ax.errorbar(x, sub["pearson_r"], fmt="o", color="tab:blue", label="observed r")
        ax.fill_between(x, sub["mc_lo_r"], sub["mc_hi_r"], color="black", alpha=0.15, label=f"MC(R={reps}, seed={seed}) 95% interval")
        ax.set_xticks(list(x))
        ax.set_xticklabels(labels, rotation=90, fontsize=6)
        ax.set_title(level)
    fig.suptitle(f"Block stability, Pearson r (null: MC(R={reps}, seed={seed}))")
    axes[0].legend(fontsize=7)
    fig.tight_layout()
    return _save(fig, path)


def render_all(result, out_dir: Path) -> list[Path]:
    tables = result.csv_tables
    n = result.data.n_draws
    reps, seed = result.params.mc_reps, result.params.seed

    paths = []
    paths.append(draw_sum_chart(tables["draw_metric_distribution"], out_dir / "draw_sum.png", reps, seed))
    paths.append(draw_min_max_range_chart(tables["draw_metric_distribution"], out_dir / "draw_min_max_range.png"))
    paths.append(draw_odd_low_consecutive_chart(tables["draw_metric_distribution"], out_dir / "draw_odd_low_consecutive.png"))
    paths.append(draw_gaps_chart(tables["draw_metric_distribution"], out_dir / "draw_gaps.png"))
    paths.append(number_frequency_chart(tables["number_frequency"], out_dir / "number_frequency.png", reps, seed))
    paths.append(number_frequency_by_year_chart(tables["number_frequency_by_period"], out_dir / "number_frequency_by_year.png"))
    for w in result.params.windows:
        key = f"number_rolling_extremes_W{w}"
        if key in tables:
            paths.append(number_rolling_chart(tables[key], w, out_dir / f"number_rolling_W{w}.png", reps, seed))
    paths.append(number_cumulative_deviation_chart(tables["number_cumulative"], n, out_dir / "number_cumulative_deviation.png"))
    paths.append(number_interarrival_chart(tables["number_interarrival"], out_dir / "number_interarrival.png"))
    paths.append(special_frequency_chart(tables["special_frequency"], out_dir / "special_frequency.png", reps, seed))
    paths.append(pair_cooccurrence_heatmap_chart(tables["pair_cooccurrence"], out_dir / "pair_cooccurrence_heatmap.png"))
    paths.append(pair_count_distribution_chart(tables["pair_count_distribution"], out_dir / "pair_count_distribution.png"))
    paths.append(stability_blocks_chart(tables["stability_blocks"], out_dir / "stability_blocks.png", reps, seed))
    return paths
