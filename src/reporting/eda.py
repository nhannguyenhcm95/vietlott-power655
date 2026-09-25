"""M3 EDA orchestration: spec gate, ceiling, single loader, metric build, deterministic write.

Implements `docs/design/M3-eda-spec.md` Rev 3.1. Descriptive only: no p-values, no
"hot/cold/overdue/due/lucky" labels, no rankings. See the spec for the full framing rules.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import scipy

from src.config import Paths
from src.statistics import eda as stat_eda
from src.statistics import mc_reference
from src.statistics import null_model
from src.statistics import null_reference as nr
from src.transformation import tables

log = logging.getLogger(__name__)

EDA_MAX_THROUGH_DRAW = "01190"
MIN_SPEC_VERSION = (1, 2)

_THROUGH_DRAW_RE = re.compile(r"^\d{5}$")
_REF_RE = re.compile(r"^[A-Z]+-\d+$")
_HEADING_RE = re.compile(r"^#{1,3} ")
_DECISIONS_START_RE = re.compile(r"^### Decisions\b")
# Approval line format: "SPECIFICATION vX.Y[.Z] APPROVED sha256=<hex>"
_APPROVAL_RE = re.compile(r"SPECIFICATION v(\d+(?:\.\d+)+) APPROVED sha256=([0-9a-f]{64})\b")
_OVERRIDE_TEXT_RE = re.compile(r"EDA ceiling override")


class EdaCeilingRefused(RuntimeError):
    """Raised when --through-draw exceeds the ceiling and no valid override applies."""


class EdaSpecNotApproved(RuntimeError):
    """Raised when SPECIFICATION.md is not approved at >= MIN_SPEC_VERSION with a matching sha256."""


class EdaLoadError(RuntimeError):
    """Raised for malformed/non-existent/non-contiguous --through-draw or mixed dataset_version."""


# ---------------------------------------------------------------------------
# Section 1.6: spec-approval gate
# ---------------------------------------------------------------------------

def decision_lines(taskboard_path: Path) -> list[str]:
    """All lines inside any '### Decisions...' section of TASKBOARD.md (section 1.2 rule)."""
    path = Path(taskboard_path)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    in_section = False
    for line in lines:
        if _DECISIONS_START_RE.match(line):
            in_section = True
            out.append(line)
            continue
        if in_section and _HEADING_RE.match(line) and not _DECISIONS_START_RE.match(line):
            in_section = False
            continue
        if in_section:
            out.append(line)
    return out


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(x) for x in version.split("."))


def check_spec_approval(root: Path) -> tuple[str, str]:
    """Returns (version, sha256) of the last matching approval line, or raises EdaSpecNotApproved."""
    root = Path(root)
    taskboard_path = root / "docs" / "TASKBOARD.md"
    spec_path = root / "docs" / "SPECIFICATION.md"

    lines = decision_lines(taskboard_path)
    match = None
    for line in lines:
        m = _APPROVAL_RE.search(line)
        if m:
            match = m  # keep the last match
    if match is None:
        raise EdaSpecNotApproved("no SPECIFICATION APPROVED line found in a Decisions section")

    version, sha256 = match.group(1), match.group(2)
    if _version_tuple(version) < MIN_SPEC_VERSION:
        raise EdaSpecNotApproved(f"approved version v{version} < v{'.'.join(map(str, MIN_SPEC_VERSION))}")

    if not spec_path.exists():
        raise EdaSpecNotApproved(f"{spec_path} does not exist")
    actual_sha = hashlib.sha256(spec_path.read_bytes()).hexdigest()
    if actual_sha != sha256:
        raise EdaSpecNotApproved(f"SPECIFICATION.md sha256 {actual_sha} != approved {sha256}")

    return version, sha256


# ---------------------------------------------------------------------------
# Section 1.2: ceiling
# ---------------------------------------------------------------------------

def check_ceiling(through_draw: str, override_ref: str | None, taskboard_path: Path) -> str:
    """Returns the override_ref actually used ("" if the ceiling did not need one).
    Raises EdaCeilingRefused if the ceiling is exceeded without a valid override."""
    ceiling = int(EDA_MAX_THROUGH_DRAW)
    td = int(through_draw)
    if td <= ceiling:
        return ""

    if not override_ref:
        raise EdaCeilingRefused(f"through_draw {through_draw} exceeds the ceiling {EDA_MAX_THROUGH_DRAW} and no override was given")
    if not _REF_RE.match(override_ref):
        raise EdaCeilingRefused(f"malformed override ref {override_ref!r}")

    token_re = re.compile(r"(?<![\w-])" + re.escape(override_ref) + r"(?![\w-])")
    lines = decision_lines(taskboard_path)
    for line in lines:
        if _OVERRIDE_TEXT_RE.search(line) and token_re.search(line):
            return override_ref

    raise EdaCeilingRefused(f"override ref {override_ref!r} not found on a Decisions line containing 'EDA ceiling override'")


# ---------------------------------------------------------------------------
# Section 1.1-1.4: single loader (choke point)
# ---------------------------------------------------------------------------

@dataclass
class AnalysisData:
    frame: pd.DataFrame
    source_dataset_version: str
    analysis_version: str
    through_draw: str
    n_draws: int


def _validate_through_draw_format(through_draw: str) -> None:
    if not _THROUGH_DRAW_RE.match(through_draw or ""):
        raise EdaLoadError(f"--through-draw {through_draw!r} must match ^\\d{{5}}$")


def load_analysis_draws(curated_dir: Path, through_draw: str) -> AnalysisData:
    """The only EDA code that calls tables.read_fact_draw. Filters, validates, returns analysis
    rows only; rows after the cutoff are never validated, aggregated, hashed or logged."""
    _validate_through_draw_format(through_draw)
    td = int(through_draw)

    fact = tables.read_fact_draw(curated_dir)
    # F4: filter on the raw, already-string draw_id column *before* any numeric cast, so that
    # post-cutoff content (an empty cell, a malformed draw_id, ...) can never influence how
    # pandas infers a whole-column dtype for MAIN_COLS, and can never crash the filter itself.
    draw_id_str = fact["draw_id"].astype(str)
    filtered = fact.loc[draw_id_str <= through_draw].copy()

    if filtered.empty:
        raise EdaLoadError(f"through_draw {through_draw} does not exist in the curated data")

    # F4: cast MAIN_COLS/special_number explicitly on the already-filtered analysis rows only,
    # so a dtype inferred from the whole (unfiltered) column never leaks into the hash/validation.
    for col in tables.MAIN_COLS:
        coerced = pd.to_numeric(filtered[col], errors="coerce")
        if coerced.isna().any():
            raise EdaLoadError(f"{col} has a non-numeric or missing value within the analysis range")
        filtered[col] = coerced.astype(np.int64)
    filtered["special_number"] = pd.to_numeric(filtered["special_number"], errors="coerce").astype("Int64")

    try:
        filtered_ids = filtered["draw_id"].astype(int)
    except ValueError as exc:
        raise EdaLoadError(f"a draw_id within the analysis range is not a valid integer: {exc}")

    if int(filtered_ids.max()) != td:
        raise EdaLoadError(f"through_draw {through_draw} does not exist in the curated data")

    n = len(filtered)
    expected_ids = list(range(1, n + 1))
    if sorted(filtered_ids.tolist()) != expected_ids:
        raise EdaLoadError("analysis draw_ids are not contiguous starting at 00001")

    filtered = filtered.sort_values("draw_id").reset_index(drop=True)

    # validate rows: 6 distinct ints in 1..55, ascending, special not in main or NA
    main = filtered[tables.MAIN_COLS].to_numpy(dtype=np.int64)
    if not ((main >= 1) & (main <= 55)).all():
        raise EdaLoadError("a main number is outside 1..55")
    if not (np.diff(main, axis=1) > 0).all():
        raise EdaLoadError("main numbers are not strictly ascending / distinct")
    special = filtered["special_number"]
    for i, row in enumerate(main):
        sp = special.iloc[i]
        if pd.notna(sp) and int(sp) in row.tolist():
            raise EdaLoadError("special number duplicates a main number")

    versions = filtered["dataset_version"].unique()
    if len(versions) != 1:
        raise EdaLoadError(f"analysis rows have more than one dataset_version: {sorted(versions)}")
    source_dataset_version = str(versions[0])

    content_cols_frame = filtered[tables.CONTENT_COLS]
    analysis_version = tables.dataset_version(content_cols_frame)

    filtered["t"] = range(1, n + 1)

    return AnalysisData(
        frame=filtered, source_dataset_version=source_dataset_version,
        analysis_version=analysis_version, through_draw=through_draw, n_draws=n,
    )


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

@dataclass
class EdaParams:
    windows: list[int] = field(default_factory=lambda: [50, 100, 200])
    n_blocks: int = 5
    mc_reps: int = 10_000
    seed: int = null_model.EDA_SEED
    override_ref: str = ""


@dataclass
class EdaResult:
    data: AnalysisData
    params: EdaParams
    spec_version: str
    spec_sha256: str
    csv_tables: dict[str, pd.DataFrame]
    summary_text: str


def _version_cols(data: AnalysisData, params: EdaParams) -> dict:
    return {
        "source_dataset_version": data.source_dataset_version,
        "analysis_version": data.analysis_version,
        "through_draw": data.through_draw,
        "override_ref": params.override_ref,
    }


def _add_version_cols(df: pd.DataFrame, data: AnalysisData, params: EdaParams) -> pd.DataFrame:
    out = df.copy()
    for k, v in _version_cols(data, params).items():
        out[k] = v
    return out


def _mc_value(mc_df: pd.DataFrame, statistic: str, param: str, quantile) -> float | None:
    row = mc_df[(mc_df["statistic"] == statistic) & (mc_df["param"] == param) & (mc_df["quantile"] == quantile)]
    if row.empty:
        return None
    return float(row["value"].iloc[0])


def build_eda(data: AnalysisData, params: EdaParams, spec_version: str, spec_sha256: str) -> EdaResult:
    df = data.frame
    n = data.n_draws

    metrics = stat_eda.draw_metrics(df)
    dist = stat_eda.draw_metric_distribution(metrics, n)
    null_pmfs = stat_eda.null_pmfs_table()
    summary_tbl = stat_eda.draw_metric_summary(metrics, n)

    freq = stat_eda.number_frequency(df)
    freq_period = stat_eda.number_frequency_by_period(df)

    rolling_tables: dict[int, pd.DataFrame] = {}
    rolling_extremes: dict[int, pd.DataFrame] = {}
    for w in params.windows:
        if w > n:
            continue
        rolling_tables[w] = stat_eda.rolling_number_counts(df, w)
        rolling_extremes[w] = stat_eda.rolling_number_extremes(rolling_tables[w])

    interarrival = stat_eda.interarrival_gaps(df)
    appearance = stat_eda.appearance_summary(df)
    cumulative = stat_eda.cumulative_counts(df)
    special = stat_eda.special_frequency(df)
    n_nonmissing = int(df["special_number"].notna().sum())

    pairs = stat_eda.pair_cooccurrence(df)
    pair_dist = stat_eda.pair_count_distribution(pairs, n)
    stability = stat_eda.block_stability(df, params.n_blocks)

    mc_df = mc_reference.replicate_references(
        n=n, windows=[w for w in params.windows if w <= n], n_blocks=params.n_blocks,
        reps=params.mc_reps, seed=params.seed, n_special=n_nonmissing,
    )

    freq = freq.copy()
    freq["sim_lo"] = _mc_value(mc_df, "number_frequency_min", "", 0.025)
    freq["sim_hi"] = _mc_value(mc_df, "number_frequency_max", "", 0.975)

    special = special.copy()
    special["sim_lo"] = _mc_value(mc_df, "special_frequency_min", "", 0.025)
    special["sim_hi"] = _mc_value(mc_df, "special_frequency_max", "", 0.975)

    pairs = pairs.copy()
    pairs["sim_lo"] = _mc_value(mc_df, "pair_count_min", "", 0.025)
    pairs["sim_hi"] = _mc_value(mc_df, "pair_count_max", "", 0.975)

    for w, ext in rolling_extremes.items():
        ext["mc_max_z_q975"] = _mc_value(mc_df, "rolling_max_z", str(w), 0.975)
        ext["mc_min_z_q025"] = _mc_value(mc_df, "rolling_min_z", str(w), 0.025)

    def stability_stat(level: str) -> str:
        return "stability_number" if level == "number" else "stability_pair"

    stability = stability.copy()
    stability["mc_mean_r"] = stability.apply(
        lambda r: _mc_value(mc_df, stability_stat(r["level"]), f"{r['block_a']}-{r['block_b']}", "mean"), axis=1)
    stability["mc_lo_r"] = stability.apply(
        lambda r: _mc_value(mc_df, stability_stat(r["level"]), f"{r['block_a']}-{r['block_b']}", 0.025), axis=1)
    stability["mc_hi_r"] = stability.apply(
        lambda r: _mc_value(mc_df, stability_stat(r["level"]), f"{r['block_a']}-{r['block_b']}", 0.975), axis=1)

    csv_tables: dict[str, pd.DataFrame] = {
        "draw_metrics": metrics,
        "draw_metric_distribution": dist,
        "null_pmfs": null_pmfs,
        "draw_metric_summary": summary_tbl,
        "number_frequency": freq,
        "number_frequency_by_period": freq_period,
        "number_interarrival": interarrival,
        "number_appearance": appearance,
        "number_cumulative": cumulative,
        "special_frequency": special,
        "pair_cooccurrence": pairs,
        "pair_count_distribution": pair_dist,
        "stability_blocks": stability,
        "mc_reference": mc_df,
    }
    for w, rt in rolling_tables.items():
        csv_tables[f"number_rolling_W{w}"] = rt
    for w, ext in rolling_extremes.items():
        csv_tables[f"number_rolling_extremes_W{w}"] = ext

    csv_tables = {name: _add_version_cols(tbl, data, params) for name, tbl in csv_tables.items()}

    summary_text = render_summary_text(data, params, spec_version, spec_sha256, dist, summary_tbl, freq,
                                        special, pairs, rolling_extremes, stability)

    return EdaResult(data=data, params=params, spec_version=spec_version, spec_sha256=spec_sha256,
                      csv_tables=csv_tables, summary_text=summary_text)


# ---------------------------------------------------------------------------
# Section 5: eda_summary.md (fixed text + templated count sentences only)
# ---------------------------------------------------------------------------

_METRIC_ORDER = ["sum", "min", "max", "range", "odd_count", "low_count", "consecutive_pairs", "gap", "max_gap", "min_gap"]

# F6 (spec Rev 3.2 §5): the D6 metrics always carry the within_draw_ prefix in the summary text
# (the CSV `metric` column itself is unchanged: it stays `gap`/`max_gap`/`min_gap`).
_METRIC_SUMMARY_LABEL = {
    "gap": "within_draw_gap",
    "max_gap": "within_draw_max_gap",
    "min_gap": "within_draw_min_gap",
}

_LIMITATIONS = [
    "There is no inference here; M4 decides.",
    "Pointwise bands and the envelope are exceeded about 5% of the time by chance.",
    "Rolling windows overlap and are autocorrelated.",
    "Inter-arrival gaps are memoryless under the null.",
    "The drawing order is hidden.",
    "MC references carry Monte Carlo error.",
    "2017 and 2025 are partial years.",
    "The M4 confirmatory tests use the same draws.",
    "Nothing here is evidence that future draws can be forecast.",
]

TPL_METRIC = re.compile(r"^[a-z_]+: observed mean -?\d+(\.\d+)? \(null -?\d+(\.\d+)?\); \d+ of \d+ cells outside the pointwise band \(-?\d+(\.\d+)? expected\)\.$")
TPL_NUMBERS = re.compile(r"^(main|special): \d+ of 55 numbers outside the pointwise band \(-?\d+(\.\d+)? expected; nominal 2\.75\); \d+ outside the simultaneous band\.$")
TPL_PAIRS = re.compile(r"^\d+ of 1,485 pairs outside the pointwise band \(-?\d+(\.\d+)? expected; nominal 74\); \d+ outside the simultaneous band\.$")
TPL_ROLLING = re.compile(r"^W=\d+: \d+ of \d+ windows above and \d+ below the pointwise envelope \(≈2\.5% expected on each side; windows overlap\)\.$")
TPL_STABILITY = re.compile(r"^\d+ of \d+ block pairs with r outside the MC 95% interval \(-?\d+(\.\d+)? expected\)\.$")
HEADER_LINE_RE = re.compile(r"^(source_dataset_version|analysis_version|through_draw|n_draws|override_ref|spec_version|spec_sha256|windows|n_blocks|mc_reps|seed): .*$")

FIXED_LINES = {
    "# EDA summary", "## Parameters", "## Draw-level metrics", "## Number-level metrics",
    "## Pair-level metrics", "## Limitations",
} | {f"- {t}" for t in _LIMITATIONS}

# F6: TPL_GAPD6 removed from the whitelist (spec Rev 3.2 drops the separate D6 aggregate template;
# the within_draw_gap/within_draw_max_gap/within_draw_min_gap lines use TPL_METRIC instead).
ALL_TEMPLATES = [TPL_METRIC, TPL_NUMBERS, TPL_PAIRS, TPL_ROLLING, TPL_STABILITY, HEADER_LINE_RE]


def _fmt(x) -> str:
    """Fixed-point formatting (never scientific notation) so summary lines match the §5 template
    regexes, which expect plain digits."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "NA"
    if isinstance(x, (int, np.integer)):
        return str(int(x))
    val = round(float(x), 4)
    s = f"{val:.4f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def _expected_outside(n_obs: int, p_cell: float, null_lo: float, null_hi: float) -> float:
    from scipy.stats import binom
    if n_obs <= 0 or p_cell <= 0:
        return 0.0
    return float(binom.cdf(null_lo - 1, n_obs, p_cell) + (1 - binom.cdf(null_hi, n_obs, p_cell)))


def _metric_line(metric: str, dist: pd.DataFrame, summary_tbl: pd.DataFrame, n_obs: int) -> str:
    sub = dist[dist["metric"] == metric]
    m = len(sub)
    k = int(((sub["observed_count"] < sub["null_lo"]) | (sub["observed_count"] > sub["null_hi"])).sum())
    e = float(sub.apply(lambda r: _expected_outside(n_obs, r["null_prob"], r["null_lo"], r["null_hi"]), axis=1).sum())
    row = summary_tbl[summary_tbl["metric"] == metric].iloc[0]
    label = _METRIC_SUMMARY_LABEL.get(metric, metric)
    return f"{label}: observed mean {_fmt(row['obs_mean'])} (null {_fmt(row['null_mean'])}); {k} of {m} cells outside the pointwise band ({_fmt(e)} expected)."


def _numbers_line(scope: str, freq: pd.DataFrame, n_obs: int, p: float) -> str:
    k = int(((freq["count"] < freq["null_lo"]) | (freq["count"] > freq["null_hi"])).sum())
    e = 55 * _expected_outside(n_obs, p, freq["null_lo"].iloc[0], freq["null_hi"].iloc[0])
    j = int(((freq["count"] < freq["sim_lo"]) | (freq["count"] > freq["sim_hi"])).sum())
    return f"{scope}: {k} of 55 numbers outside the pointwise band ({_fmt(e)} expected; nominal 2.75); {j} outside the simultaneous band."


def _pairs_line(pairs: pd.DataFrame, n_obs: int) -> str:
    k = int(((pairs["count"] < pairs["null_lo"]) | (pairs["count"] > pairs["null_hi"])).sum())
    e = 1485 * _expected_outside(n_obs, stat_eda.Q_PAIR, pairs["null_lo"].iloc[0], pairs["null_hi"].iloc[0])
    j = int(((pairs["count"] < pairs["sim_lo"]) | (pairs["count"] > pairs["sim_hi"])).sum())
    return f"{k} of 1,485 pairs outside the pointwise band ({_fmt(e)} expected; nominal 74); {j} outside the simultaneous band."


def _rolling_line(w: int, ext: pd.DataFrame) -> str:
    m = len(ext)
    k = int((ext["max_z"] > ext["mc_max_z_q975"]).sum())
    j = int((ext["min_z"] < ext["mc_min_z_q025"]).sum())
    return f"W={w}: {k} of {m} windows above and {j} below the pointwise envelope (≈2.5% expected on each side; windows overlap)."


def _stability_line(stability: pd.DataFrame) -> str:
    m = len(stability)
    k = int(((stability["pearson_r"] < stability["mc_lo_r"]) | (stability["pearson_r"] > stability["mc_hi_r"])).sum())
    e = 0.05 * m
    return f"{k} of {m} block pairs with r outside the MC 95% interval ({_fmt(e)} expected)."


def render_summary_text(data: AnalysisData, params: EdaParams, spec_version: str, spec_sha256: str,
                         dist: pd.DataFrame, summary_tbl: pd.DataFrame, freq: pd.DataFrame,
                         special: pd.DataFrame, pairs: pd.DataFrame, rolling_extremes: dict[int, pd.DataFrame],
                         stability: pd.DataFrame) -> str:
    lines: list[str] = ["# EDA summary", ""]
    header = {
        "source_dataset_version": data.source_dataset_version,
        "analysis_version": data.analysis_version,
        "through_draw": data.through_draw,
        "n_draws": data.n_draws,
        "override_ref": params.override_ref,
        "spec_version": spec_version,
        "spec_sha256": spec_sha256,
        "windows": ",".join(str(w) for w in params.windows),
        "n_blocks": params.n_blocks,
        "mc_reps": params.mc_reps,
        "seed": params.seed,
    }
    lines.append("## Parameters")
    for k, v in header.items():
        lines.append(f"{k}: {v}")
    lines.append("")

    lines.append("## Draw-level metrics")
    n_obs_by_metric = {m: (data.n_draws * 5 if m == "gap" else data.n_draws) for m in _METRIC_ORDER}
    for metric in _METRIC_ORDER:
        lines.append(_metric_line(metric, dist, summary_tbl, n_obs_by_metric[metric]))
    lines.append("")

    lines.append("## Number-level metrics")
    lines.append(_numbers_line("main", freq, data.n_draws, stat_eda.P_NUMBER))
    n_nonmissing = int(special["n_nonmissing"].iloc[0]) if "n_nonmissing" in special.columns else data.n_draws
    lines.append(_numbers_line("special", special, n_nonmissing, 1 / 55))
    for w in sorted(rolling_extremes):
        lines.append(_rolling_line(w, rolling_extremes[w]))
    lines.append("")

    lines.append("## Pair-level metrics")
    lines.append(_pairs_line(pairs, data.n_draws))
    lines.append(_stability_line(stability))
    lines.append("")

    lines.append("## Limitations")
    for t in _LIMITATIONS:
        lines.append(f"- {t}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Section 5: write outputs (CSV, PNG, md, manifest), atomically
# ---------------------------------------------------------------------------

CSV_KWARGS = dict(index=False, lineterminator="\n", float_format="%.10g", encoding="utf-8")


def _library_versions() -> dict:
    import matplotlib
    return {"numpy": np.__version__, "scipy": scipy.__version__, "pandas": pd.__version__, "matplotlib": matplotlib.__version__}


def write_eda(result: EdaResult, out_dir: Path) -> Path:
    from src.reporting import eda_charts

    data, params = result.data, result.params
    dirname = f"through_{data.through_draw}" + ("_override" if params.override_ref else "")
    final_dir = Path(out_dir) / dirname
    tmp_dir = Path(out_dir) / (dirname + ".tmp")
    if tmp_dir.exists():
        for p in sorted(tmp_dir.glob("*"), reverse=True):
            p.unlink()
        tmp_dir.rmdir()
    tmp_dir.mkdir(parents=True, exist_ok=True)

    file_hashes: dict[str, str] = {}

    for name, tbl in result.csv_tables.items():
        path = tmp_dir / f"{name}.csv"
        tbl.to_csv(path, **CSV_KWARGS)
        file_hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()

    summary_path = tmp_dir / "eda_summary.md"
    summary_bytes = result.summary_text.encode("utf-8")
    summary_path.write_bytes(summary_bytes)
    file_hashes[summary_path.name] = hashlib.sha256(summary_bytes).hexdigest()

    chart_paths = eda_charts.render_all(result, tmp_dir)
    for p in chart_paths:
        file_hashes[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()

    manifest = {
        "spec_version": result.spec_version,
        "spec_sha256": result.spec_sha256,
        "source_dataset_version": data.source_dataset_version,
        "analysis_version": data.analysis_version,
        "through_draw": data.through_draw,
        "n_draws": data.n_draws,
        "override_ref": params.override_ref,
        "params": {
            "windows": params.windows, "n_blocks": params.n_blocks, "mc_reps": params.mc_reps,
        },
        "seed": params.seed,
        "streams": {"main": 1, "special": 2},
        "library_versions": _library_versions(),
        "files": {k: file_hashes[k] for k in sorted(file_hashes)},
    }
    manifest_bytes = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode("utf-8")
    manifest_path = tmp_dir / "eda_manifest.json"
    manifest_path.write_bytes(manifest_bytes)

    if final_dir.exists():
        for p in sorted(final_dir.glob("*"), reverse=True):
            p.unlink()
        final_dir.rmdir()
    os.replace(tmp_dir, final_dir)
    return final_dir


# ---------------------------------------------------------------------------
# Top-level orchestration used by the CLI
# ---------------------------------------------------------------------------

def run_eda(paths: Paths, through_draw: str, out_dir: Path, windows: list[int], n_blocks: int,
            mc_reps: int, override_ref: str | None) -> int:
    if not _THROUGH_DRAW_RE.match(through_draw or ""):
        log.error("eda_bad_through_draw", extra={"through_draw": through_draw})
        return 2

    try:
        spec_version, spec_sha256 = check_spec_approval(paths.root)
    except EdaSpecNotApproved as exc:
        log.warning("eda_spec_not_approved", extra={"detail": str(exc)})
        return 2

    taskboard_path = paths.root / "docs" / "TASKBOARD.md"
    try:
        used_override_ref = check_ceiling(through_draw, override_ref, taskboard_path)
    except EdaCeilingRefused as exc:
        log.warning("eda_ceiling_refused", extra={"through_draw": through_draw, "detail": str(exc)})
        return 2
    if used_override_ref:
        log.warning("eda_ceiling_override", extra={"override_ref": used_override_ref, "through_draw": through_draw})

    try:
        data = load_analysis_draws(paths.curated, through_draw)
    except EdaLoadError as exc:
        log.error("eda_load_error", extra={"detail": str(exc)})
        return 2

    params = EdaParams(windows=windows, n_blocks=n_blocks, mc_reps=mc_reps, override_ref=used_override_ref)
    result = build_eda(data, params, spec_version, spec_sha256)
    write_eda(result, out_dir)
    return 0
