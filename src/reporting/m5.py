"""M5 EXP-001 orchestration: spec gate, dirty-tree gate, single loader, fold-table gate, scoring,
bootstrap CIs, W selection, sanity asserts, deterministic write.

Implements `docs/experiments/EXP-001.md` r2 (sha256
a1959d8c8464e7f4a03be1d765828256e91f698e6f0f14371310c07b211c3872). Reuses the M3/M4 spec-approval
gate and single-loader pattern (`src/reporting/eda.py::load_analysis_draws`,
`src/reporting/m4.py::code_version`, `check_no_banned_words`). Descriptive/development framing
only: no per-number output, no rankings, no forecast for any draw above 01190.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import scipy

from src.config import Paths
from src.evaluation import bootstrap as ev_bootstrap
from src.evaluation import folds as ev_folds
from src.evaluation import metrics as ev_metrics
from src.evaluation import selection as ev_selection
from src.models import baselines
from src.reporting import eda as eda_reporting
from src.reporting import m4 as m4_reporting
from src.transformation import tables

log = logging.getLogger(__name__)

M5_MAX_THROUGH_DRAW = eda_reporting.EDA_MAX_THROUGH_DRAW  # "01190"
M5_PINNED_ANALYSIS_VERSION = "ds_16b6be697acb"
EXPERIMENT_ID = "EXP-001"
SEED = ev_bootstrap.SEED
BOOTSTRAP_B = ev_bootstrap.B_DEFAULT

CONFIGS = baselines.CONFIGS  # ["B0", "B1", "B2_W50", "B2_W100", "B2_W200"]
B2_CANDIDATES = baselines.B2_WINDOWS  # [50, 100, 200]

_EXPECTED_FOLD_ROWS = [
    # fold, fit_start, fit_end, inner_train_start, inner_train_end, inner_val_start, inner_val_end, scored_start, scored_end, n
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
_FOLD_COLS = ["fold", "fit_start", "fit_end", "inner_train_start", "inner_train_end",
              "inner_val_start", "inner_val_end", "scored_start", "scored_end", "n"]
EXPECTED_FOLD_TABLE = pd.DataFrame(_EXPECTED_FOLD_ROWS, columns=_FOLD_COLS)


class SanityCheckFailed(RuntimeError):
    """Section 6 sanity asserts failed; a bug to fix, never a value to tune."""


# ---------------------------------------------------------------------------
# Single loader (choke point)
# ---------------------------------------------------------------------------

def load_m5_draws(curated_dir: Path) -> eda_reporting.AnalysisData:
    """The only M5 path to curated data. No override, no --through-draw."""
    return eda_reporting.load_analysis_draws(curated_dir, M5_MAX_THROUGH_DRAW)


# ---------------------------------------------------------------------------
# Build: score every configuration over the scored range 501..1190
# ---------------------------------------------------------------------------

@dataclass
class M5Result:
    data: eda_reporting.AnalysisData
    spec_version: str
    spec_sha256: str
    code_version: str
    provisional: bool
    draw_scores: pd.DataFrame
    metrics: pd.DataFrame
    reliability: pd.DataFrame
    w_selection: pd.DataFrame
    w_star: int
    summary_text: str
    runtime_seconds: float
    fold_table: pd.DataFrame
    p_min: float
    p_max: float


PERIODS_FOLDS = [f"fold_{i:02d}" for i in range(1, 15)]
PERIOD_DEV_POOLED = "dev_pooled"
PERIOD_VALIDATION = "validation"


def _score_all(data: eda_reporting.AnalysisData) -> tuple[np.ndarray, dict[str, np.ndarray], np.ndarray, np.ndarray]:
    """Returns (t_values, {config: P}, Y_scored, s_actual_scored) for the scored range 501..1190."""
    df = data.frame
    main = df[tables.MAIN_COLS].to_numpy(dtype=np.int64)
    Y = baselines.indicator_matrix(main)
    C = baselines.prefix_counts(Y)

    t_values = np.arange(501, 1191, dtype=np.int64)
    ev_folds.assert_dev_only(t_values.tolist())
    predictions = baselines.predict_all(C, t_values)
    Y_scored = Y[t_values - 1]
    s_actual = Y_scored @ np.arange(1, 56, dtype=np.float64)
    return t_values, predictions, Y_scored, s_actual


def _period_masks(scored_map: pd.DataFrame) -> dict[str, np.ndarray]:
    """scored_map: rows for draw_id 501..1190 (ordered), columns draw_id, fold, in_validation."""
    masks: dict[str, np.ndarray] = {}
    for i in range(1, 15):
        masks[f"fold_{i:02d}"] = (scored_map["fold"] == i).to_numpy()
    masks[PERIOD_DEV_POOLED] = np.ones(len(scored_map), dtype=bool)
    masks[PERIOD_VALIDATION] = scored_map["in_validation"].to_numpy()
    return masks


def build_m5(data: eda_reporting.AnalysisData, folds: list[ev_folds.Fold], spec_version: str,
             spec_sha256: str, code_ver: str, provisional: bool, t0: float) -> M5Result:
    scored_map = ev_folds.scored_draw_table(folds)  # draw_id 501..1190, fold, in_validation
    t_values, predictions, Y_scored, s_actual = _score_all(data)
    assert list(scored_map["draw_id"]) == list(t_values), "scored draw ids must match the fold table exactly"

    # ---- per-draw scores (draw_scores.csv) ----
    draw_rows: list[pd.DataFrame] = []
    per_config_series: dict[str, dict[str, np.ndarray]] = {}
    for cfg in CONFIGS:
        P = predictions[cfg]
        ll, n_clipped = ev_metrics.per_draw_log_loss(Y_scored, P)
        brier = ev_metrics.per_draw_brier(Y_scored, P)
        sp = ev_metrics.sum_p(P)
        s_hat = ev_metrics.sum_forecast(P)
        per_config_series[cfg] = {"ll": ll, "brier": brier, "sum_p": sp, "n_clipped": n_clipped,
                                   "sum_actual": s_actual, "sum_forecast": s_hat, "P": P}
        df_cfg = pd.DataFrame({
            "draw_id": [f"{int(d):05d}" for d in t_values],
            "fold": scored_map["fold"].to_numpy(),
            "in_validation": scored_map["in_validation"].to_numpy(),
            "config": cfg,
            "ll": ll, "brier": brier, "sum_p": sp, "n_clipped": n_clipped,
            "sum_actual": s_actual, "sum_forecast": s_hat,
        })
        draw_rows.append(df_cfg)
    draw_scores = pd.concat(draw_rows, ignore_index=True)
    p_min = min(float(predictions[cfg].min()) for cfg in CONFIGS)
    p_max = max(float(predictions[cfg].max()) for cfg in CONFIGS)

    # ---- metrics.csv (bootstrap per period, shared idx across configs) ----
    masks = _period_masks(scored_map)
    b0_ll_full = per_config_series["B0"]["ll"]
    b0_brier_full = per_config_series["B0"]["brier"]
    b0_mae_diff_full = per_config_series["B0"]["sum_actual"] - per_config_series["B0"]["sum_forecast"]

    metrics_rows: list[dict] = []
    reliability_rows: list[dict] = []
    validation_ll_by_w: dict[int, float] = {}

    for period, mask in masks.items():
        n_period = int(mask.sum())
        idx = ev_bootstrap.bootstrap_indices(n_period, seed=SEED, B=BOOTSTRAP_B)
        draw_first = f"{int(t_values[mask].min()):05d}"
        draw_last = f"{int(t_values[mask].max()):05d}"

        for cfg in CONFIGS:
            s = per_config_series[cfg]
            ll_p, brier_p = s["ll"][mask], s["brier"][mask]
            sp_p, ncl_p = s["sum_p"][mask], s["n_clipped"][mask]
            sum_actual_p, sum_forecast_p = s["sum_actual"][mask], s["sum_forecast"][mask]
            P_p = s["P"][mask]
            Y_p = Y_scored[mask]

            ll_mean = float(ll_p.mean())
            brier_mean = float(brier_p.mean())
            ece_val, n_bins, bin_ids, bin_n, bin_pmean, bin_ymean, bin_pmin, bin_pmax = ev_metrics.ece_table(P_p, Y_p)
            sp_mean, sp_min, sp_max = float(sp_p.mean()), float(sp_p.min()), float(sp_p.max())
            n_clipped_total = int(ncl_p.sum())
            mae, rmse = ev_metrics.sum_mae_rmse(sum_actual_p, sum_forecast_p)

            ll_ci = ev_bootstrap.percentile_ci(ll_p[idx].mean(axis=1))
            brier_ci = ev_bootstrap.percentile_ci(brier_p[idx].mean(axis=1))
            ece_ci = ev_bootstrap.bootstrap_ece_ci(P_p, Y_p, idx)
            diff = sum_actual_p - sum_forecast_p
            mae_ci = ev_bootstrap.percentile_ci(np.abs(diff)[idx].mean(axis=1))
            rmse_ci = ev_bootstrap.percentile_ci(np.sqrt((diff[idx] ** 2).mean(axis=1)))
            ncl_ci = ev_bootstrap.percentile_ci(ncl_p[idx].mean(axis=1))

            b0_ll_p, b0_brier_p = b0_ll_full[mask], b0_brier_full[mask]
            delta_ll = ll_p - b0_ll_p
            delta_brier = brier_p - b0_brier_p
            b0_mae_diff_p = b0_mae_diff_full[mask]
            delta_mae = np.abs(diff) - np.abs(b0_mae_diff_p)
            b0_diff_p = b0_mae_diff_p

            delta_ll_mean = float(delta_ll.mean())
            delta_brier_mean = float(delta_brier.mean())
            delta_mae_mean = float(delta_mae.mean())
            b0_rmse = float(np.sqrt((b0_diff_p ** 2).mean()))
            delta_rmse_mean = rmse - b0_rmse

            delta_ll_ci = ev_bootstrap.percentile_ci(delta_ll[idx].mean(axis=1))
            delta_brier_ci = ev_bootstrap.percentile_ci(delta_brier[idx].mean(axis=1))
            delta_mae_ci = ev_bootstrap.percentile_ci(delta_mae[idx].mean(axis=1))
            rmse_resampled = np.sqrt((diff[idx] ** 2).mean(axis=1))
            b0_rmse_resampled = np.sqrt((b0_diff_p[idx] ** 2).mean(axis=1))
            delta_rmse_ci = ev_bootstrap.percentile_ci(rmse_resampled - b0_rmse_resampled)

            if cfg == "B0":
                set_level_value: float | str = ev_metrics.SET_LEVEL_LOG_SCORE_B0
                set_level_ci = (np.nan, np.nan)
            else:
                set_level_value = "NA (marginal-only)"
                set_level_ci = (np.nan, np.nan)

            selection_biased = False
            if period == PERIOD_VALIDATION and cfg == "B1":
                selection_biased = True  # section 8.3 label; B1 has no within-family choice
            # B2(W*) label set after w_star known; recorded post-hoc below.

            metric_defs = [
                ("ll", ll_mean, ll_ci),
                ("brier", brier_mean, brier_ci),
                ("ece", ece_val, ece_ci),
                ("ece_n_bins", n_bins, (np.nan, np.nan)),
                ("sum_p_mean", sp_mean, (np.nan, np.nan)),
                ("sum_p_min", sp_min, (np.nan, np.nan)),
                ("sum_p_max", sp_max, (np.nan, np.nan)),
                ("n_clipped", n_clipped_total, ncl_ci),
                ("sum_mae", mae, mae_ci),
                ("sum_rmse", rmse, rmse_ci),
                ("set_level_ls", set_level_value, set_level_ci),
                ("delta_ll_vs_b0", delta_ll_mean, delta_ll_ci),
                ("delta_brier_vs_b0", delta_brier_mean, delta_brier_ci),
                ("delta_sum_mae_vs_b0", delta_mae_mean, delta_mae_ci),
                ("delta_sum_rmse_vs_b0", delta_rmse_mean, delta_rmse_ci),
            ]
            for metric_name, value, (ci_lo, ci_hi) in metric_defs:
                metrics_rows.append({
                    "period": period, "draw_first": draw_first, "draw_last": draw_last,
                    "n_draws": n_period, "config": cfg, "metric": metric_name, "value": value,
                    "ci_lo": ci_lo, "ci_hi": ci_hi, "validation_exposed": True,
                    "selection_biased": selection_biased,
                })

            if period in (PERIOD_DEV_POOLED, PERIOD_VALIDATION):
                for b, n_b, pm, ym, pmn, pmx in zip(bin_ids, bin_n, bin_pmean, bin_ymean, bin_pmin, bin_pmax):
                    reliability_rows.append({
                        "period": period, "config": cfg, "bin": int(b), "n": int(n_b),
                        "p_mean": float(pm), "y_mean": float(ym), "p_min": float(pmn), "p_max": float(pmx),
                    })

            if period == PERIOD_VALIDATION and cfg.startswith("B2_W"):
                w = int(cfg.split("W")[1])
                validation_ll_by_w[w] = ll_mean

    metrics_df = pd.DataFrame(metrics_rows)

    # ---- W selection ----
    w_star, w_sel_df = ev_selection.select_w(validation_ll_by_w)
    finalist_b2 = f"B2_W{w_star}"
    val_mask = (metrics_df["period"] == PERIOD_VALIDATION) & (metrics_df["config"] == finalist_b2)
    metrics_df.loc[val_mask, "selection_biased"] = True

    reliability_df = pd.DataFrame(reliability_rows)

    runtime_seconds = time.time() - t0
    fold_tbl = ev_folds.fold_table(folds)

    summary_text = render_summary(data, spec_version, spec_sha256, code_ver, draw_scores, metrics_df,
                                   w_star, w_sel_df, fold_tbl, runtime_seconds, provisional)

    return M5Result(
        data=data, spec_version=spec_version, spec_sha256=spec_sha256, code_version=code_ver,
        provisional=provisional, draw_scores=draw_scores, metrics=metrics_df,
        reliability=reliability_df, w_selection=w_sel_df, w_star=w_star, summary_text=summary_text,
        runtime_seconds=runtime_seconds, fold_table=fold_tbl, p_min=p_min, p_max=p_max,
    )


# ---------------------------------------------------------------------------
# Section 6: sanity asserts
# ---------------------------------------------------------------------------

B0_LL_EXPECTED = 0.3446104320908521
B0_BS_EXPECTED = 0.09719008264462808
EXPECTED_PERIOD_SIZES = {**{f"fold_{i:02d}": 50 for i in range(1, 14)}, "fold_14": 40,
                          PERIOD_DEV_POOLED: 690, PERIOD_VALIDATION: 210}


def run_sanity_checks(result: M5Result) -> None:
    ds = result.draw_scores
    b0 = ds[ds["config"] == "B0"]
    if not np.allclose(b0["ll"].to_numpy(), B0_LL_EXPECTED, atol=1e-12, rtol=0):
        raise SanityCheckFailed("B0 log loss deviates from the constant reference")
    if not np.allclose(b0["brier"].to_numpy(), B0_BS_EXPECTED, atol=1e-12, rtol=0):
        raise SanityCheckFailed("B0 Brier score deviates from the constant reference")

    b0_dev_ece_row = result.metrics[(result.metrics["period"] == PERIOD_DEV_POOLED)
                                     & (result.metrics["config"] == "B0") & (result.metrics["metric"] == "ece")]
    b0_dev_bins_row = result.metrics[(result.metrics["period"] == PERIOD_DEV_POOLED)
                                      & (result.metrics["config"] == "B0") & (result.metrics["metric"] == "ece_n_bins")]
    if not (abs(float(b0_dev_ece_row["value"].iloc[0])) < 1e-12):
        raise SanityCheckFailed("B0 ECE is not ~0 on dev_pooled")
    if int(b0_dev_bins_row["value"].iloc[0]) != 1:
        raise SanityCheckFailed("B0 does not have exactly 1 ECE bin on dev_pooled")

    if (ds["sum_p"] - 6).abs().max() > 1e-9:
        raise SanityCheckFailed("|sum p - 6| exceeds 1e-9 for some draw/config")
    if not (0.0 < result.p_min and result.p_max < 1.0):
        raise SanityCheckFailed(f"p is not strictly within (0, 1): min={result.p_min}, max={result.p_max}")
    if (ds["n_clipped"] != 0).any():
        raise SanityCheckFailed("n_clipped is expected to be 0 for every scored draw/config")

    for period, expected_n in EXPECTED_PERIOD_SIZES.items():
        rows = result.metrics[(result.metrics["period"] == period) & (result.metrics["metric"] == "ll")]
        if rows.empty or int(rows["n_draws"].iloc[0]) != expected_n:
            raise SanityCheckFailed(f"period {period} does not have the expected size {expected_n}")


# ---------------------------------------------------------------------------
# Summary text (OBSERVED / EVIDENCE / INTERPRETATION / LIMITATION)
# ---------------------------------------------------------------------------

_LIMITATIONS = [
    "Every development draw (00001-01190) was already seen descriptively in M3 and M4, so validation is exposed.",
    "LL and Brier assess marginals only. Within-draw dependence is not scored, and B1/B2 have no set-level score.",
    "Per-fold CIs rest on 4-5 blocks of length 10, so they are very rough and descriptive.",
    "Fold scores for B0-B2 come from one continuous scored series, then split by fold. They are not independent replications.",
    "Only M6 (01191-01401, run once) can decide H6.",
]


def _null_reference_line(cfg: str, w_or_n: int, delta_ll_ref: float, delta_bs_ref: float) -> str:
    return f"{cfg}: null reference delta LL approx {delta_ll_ref:.5f}, delta BS approx {delta_bs_ref:.5f} (m={w_or_n})."


def render_summary(data: eda_reporting.AnalysisData, spec_version: str, spec_sha256: str, code_ver: str,
                    draw_scores: pd.DataFrame, metrics_df: pd.DataFrame, w_star: int, w_sel_df: pd.DataFrame,
                    fold_tbl: pd.DataFrame, runtime_seconds: float, provisional: bool) -> str:
    lines = ["# M5 EXP-001 summary", ""]
    lines.append("## Parameters")
    lines.append(f"experiment_id: {EXPERIMENT_ID}")
    lines.append(f"source_dataset_version: {data.source_dataset_version}")
    lines.append(f"analysis_version: {data.analysis_version}")
    lines.append(f"spec_version: {spec_version}")
    lines.append(f"spec_sha256: {spec_sha256}")
    lines.append(f"code_version: {code_ver}")
    lines.append(f"seed: {SEED}")
    lines.append(f"runtime_seconds: {runtime_seconds:.1f}")
    lines.append(f"provisional: {provisional}")
    lines.append(f"selected_w: {w_star}")
    lines.append("")

    lines.append("## OBSERVED")
    lines.append("Per-fold mean log loss and Brier score, every configuration (folds 1-9 are reported "
                 "but not used for selection):")
    for _, row in fold_tbl.iterrows():
        fold_label = f"fold_{int(row['fold']):02d}"
        sub = metrics_df[(metrics_df["period"] == fold_label) & (metrics_df["metric"].isin(["ll", "brier"]))]
        parts = []
        for cfg in CONFIGS:
            ll_v = sub[(sub["config"] == cfg) & (sub["metric"] == "ll")]["value"]
            bs_v = sub[(sub["config"] == cfg) & (sub["metric"] == "brier")]["value"]
            if not ll_v.empty:
                parts.append(f"{cfg} ll={float(ll_v.iloc[0]):.5f} brier={float(bs_v.iloc[0]):.5f}")
        lines.append(f"{fold_label} (n={int(row['n'])}): " + "; ".join(parts))
    lines.append("")

    lines.append("## EVIDENCE")
    lines.append("Pooled delta vs B0 with 95% bootstrap CIs, descriptive, development data:")
    for period in (PERIOD_DEV_POOLED, PERIOD_VALIDATION):
        for cfg in ("B1", f"B2_W{w_star}"):
            row = metrics_df[(metrics_df["period"] == period) & (metrics_df["config"] == cfg)
                              & (metrics_df["metric"] == "delta_ll_vs_b0")]
            if row.empty:
                continue
            r = row.iloc[0]
            lines.append(f"{period} {cfg}: delta LL {float(r['value']):.5f} "
                         f"(95% CI {float(r['ci_lo']):.5f} to {float(r['ci_hi']):.5f}).")
    lines.append("")

    lines.append("## INTERPRETATION")
    lines.append("Under the null, every B1/B2 configuration is expected to score slightly worse than B0, "
                 "and B1 is expected to be the closest; a realised delta below 0 on development data is not "
                 "evidence against the null (section 9). Validation scores are selection-biased/optimistic "
                 "and validation-exposed (section 8); only M6 can support an H6 claim.")
    for w in B2_CANDIDATES:
        row = w_sel_df[w_sel_df["W"] == w].iloc[0]
        lines.append(f"W={w}: mean validation log loss {row['L_W']:.6f}, "
                     f"L_W - L* = {row['L_W_minus_Lstar']:.2e}, "
                     f"in_tie_set={bool(row['in_tie_set'])}, selected={bool(row['selected'])}.")
    lines.append(f"Selected W* = {w_star} (SPECIFICATION section 7 rule, tie measured against the minimum only).")
    lines.append("")

    lines.append("## LIMITATION")
    for t in _LIMITATIONS:
        lines.append(f"- {t}")
    lines.append("")

    text = "\n".join(lines)
    m4_reporting.check_no_banned_words(text)
    return text


# ---------------------------------------------------------------------------
# Write outputs
# ---------------------------------------------------------------------------

CSV_KWARGS = dict(index=False, lineterminator="\n", float_format="%.10g", encoding="utf-8")


def _library_versions() -> dict:
    return {"numpy": np.__version__, "scipy": scipy.__version__, "pandas": pd.__version__}


def _add_version_cols(df: pd.DataFrame, data: eda_reporting.AnalysisData, code_ver: str, spec_sha256: str) -> pd.DataFrame:
    out = df.copy()
    out["experiment_id"] = EXPERIMENT_ID
    out["analysis_version"] = data.analysis_version
    out["source_dataset_version"] = data.source_dataset_version
    out["code_version"] = code_ver
    out["spec_sha256"] = spec_sha256
    return out


def write_m5(result: M5Result, target_dir: Path, supersedes: str | None = None, timestamp_utc: str = "") -> Path:
    if target_dir.exists():
        raise FileExistsError(f"run directory already exists, refusing to overwrite: {target_dir}")
    tmp_dir = target_dir.parent / (target_dir.name + ".tmp")
    if tmp_dir.exists():
        for p in sorted(tmp_dir.glob("*"), reverse=True):
            p.unlink()
        tmp_dir.rmdir()
    tmp_dir.mkdir(parents=True, exist_ok=True)

    file_hashes: dict[str, str] = {}

    def _write_csv(name: str, df: pd.DataFrame):
        out_df = _add_version_cols(df, result.data, result.code_version, result.spec_sha256)
        path = tmp_dir / f"{name}.csv"
        out_df.to_csv(path, **CSV_KWARGS)
        file_hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()

    _write_csv("draw_scores", result.draw_scores)
    _write_csv("metrics", result.metrics)
    _write_csv("reliability", result.reliability)
    _write_csv("w_selection", result.w_selection)

    summary_path = tmp_dir / "summary.md"
    summary_bytes = result.summary_text.encode("utf-8")
    summary_path.write_bytes(summary_bytes)
    file_hashes[summary_path.name] = hashlib.sha256(summary_bytes).hexdigest()

    try:
        from src.reporting import m5_charts
        chart_paths = m5_charts.render_all(result, tmp_dir)
        for p in chart_paths:
            file_hashes[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    except ImportError:  # pragma: no cover - chart module always present, defensive only
        pass

    manifest = {
        "experiment_id": EXPERIMENT_ID,
        "status": "NEEDS_REVIEW",
        "spec_version": result.spec_version,
        "spec_sha256": result.spec_sha256,
        "code_version": result.code_version,
        "source_dataset_version": result.data.source_dataset_version,
        "analysis_version": result.data.analysis_version,
        "feature_version": "F-HIST-v1",
        "model_family": {"B1": "B1-a1-v1", "B2": [f"B2-a1-W{w}-v1" for w in B2_CANDIDATES], "B0": "B0-v1"},
        "train_period": "00001-00980", "validation_period": "00981-01190", "test_period": "01191-01401 (not accessed)",
        "seed": SEED,
        "fold_list": result.fold_table.to_dict(orient="records"),
        "w_star": result.w_star,
        "library_versions": _library_versions(),
        "timestamp_utc": timestamp_utc,
        "provisional": result.provisional,
        "test_period_accessed": False,
        "m6_run": False,
        "supersedes": supersedes,
        "runtime_seconds": result.runtime_seconds,
        "files": {},
    }
    manifest["files"] = {k: file_hashes[k] for k in sorted(file_hashes)}
    manifest_bytes = (json.dumps(manifest, sort_keys=True, indent=2, default=str) + "\n").encode("utf-8")
    manifest_path = tmp_dir / "manifest.json"
    manifest_path.write_bytes(manifest_bytes)

    os.replace(tmp_dir, target_dir)
    return target_dir


# ---------------------------------------------------------------------------
# Top-level orchestration used by the CLI
# ---------------------------------------------------------------------------

def _utc_timestamp(now: datetime | None = None) -> str:
    dt = now or datetime.now(timezone.utc)
    return dt.strftime("%Y%m%dT%H%M%SZ")


def run_m5(paths: Paths, provisional: bool = False, now: datetime | None = None) -> int:
    t0 = time.time()
    try:
        spec_version, spec_sha256 = eda_reporting.check_spec_approval(paths.root)
    except eda_reporting.EdaSpecNotApproved as exc:
        log.warning("m5_spec_not_approved", extra={"detail": str(exc)})
        return 2

    code_ver = m4_reporting.code_version(paths.root)
    if code_ver.endswith("-dirty") and not provisional:
        log.warning("m5_dirty_tree_refused", extra={"code_version": code_ver})
        return 2

    try:
        data = load_m5_draws(paths.curated)
    except eda_reporting.EdaLoadError as exc:
        log.error("m5_load_error", extra={"detail": str(exc)})
        return 2

    if data.analysis_version != M5_PINNED_ANALYSIS_VERSION:
        log.error("m5_analysis_version_mismatch", extra={"got": data.analysis_version, "expected": M5_PINNED_ANALYSIS_VERSION})
        return 2
    max_draw_id = int(data.frame["draw_id"].astype(int).max())
    if data.n_draws != 1190 or max_draw_id != 1190:
        log.error("m5_n_or_max_draw_mismatch", extra={"n_draws": data.n_draws, "max_draw_id": max_draw_id})
        return 2

    folds = ev_folds.build_folds()
    ft = ev_folds.fold_table(folds)
    if not ft.equals(EXPECTED_FOLD_TABLE):
        log.error("m5_fold_table_mismatch")
        return 2

    result = build_m5(data, folds, spec_version, spec_sha256, code_ver, provisional, t0)

    try:
        run_sanity_checks(result)
    except SanityCheckFailed as exc:
        log.error("m5_sanity_check_failed", extra={"detail": str(exc)})
        return 2

    ts = _utc_timestamp(now)
    run_id = f"{code_ver}_{ts}"
    base = (paths.root / "outputs" / "m5" / "provisional" / EXPERIMENT_ID) if provisional \
        else (paths.root / "outputs" / "m5" / EXPERIMENT_ID)
    target_dir = base / run_id
    if target_dir.exists():
        log.error("m5_run_id_exists", extra={"run_id": run_id})
        return 2

    write_m5(result, target_dir, timestamp_utc=ts)
    return 0
