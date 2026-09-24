# M3 design — EDA specification

Author: statistician · Revision 3.1 · 2026-09-24 · STATUS: NEEDS_REVIEW (methodology-auditor).
Implementer: stat-analyst. Reviewers: statistician (numbers), qa-runner (tests). Binding inputs: `PROJECT_STEPS.md` §7, `docs/SPECIFICATION.md` **v1.2**
(§5 H1–H5, §6 tests, §7 Baseline 2 W freeze, §8.2 data access),
and the `docs/design/M0-audit-2026-09-24.md` "Ruling: EDA / M4 data range" plus findings 5 and 11 (applied in §1, §3.1, §5).
Author's integrity note: no statistic was computed on draws after 01190 while this spec was written. The only data operations were content
hashes of rows ≤ 00980 and ≤ 01190 (§1.3). The closed forms in §3 and the pooling cell probabilities were checked by pure combinatorics and
brute-force enumeration on toy (N, k), which read no data. Also read: the M0 audit's "Verified correct" list, findings 5–11 and the ruling (auditor-computed figures, not used here).

| rev | change |
|---|---|
| 2 | M0-R ruling: ceiling 01190, override, partial years, pooling (findings 5, 11). |
| 3 | M3 review REWORK 1–7: spec-approval gate (§0, §1.6, T14); templated summary (§5, T11); override matching rules (§1.2, T8); `source_dataset_version` is metadata only (§1.3, T8g); pointwise envelope, exact gap expectation, `replicate_references` chunk invariance (§3, §5, T5, T6); T11 word list; special bands use n_nonmissing (§3.1). |
| 3.1 | Re-audit: E1 limitation wording; E2 spec version compared as an integer tuple (T14); E3 interarrival chart uses exact E_g, gap-cell template names D6, special simultaneous band simulated with n'; E4 pinned SPECIFICATION v1.2.1 hash (pending approval); T11 adds wager\*. |

## 0. Purpose and framing (binding)

**Spec gate.** `eda` must not run on real data until the human has approved **SPECIFICATION v1.2.1**. Pinned: `SPEC_VERSION = "v1.2.1"`, `SPEC_SHA256` = the sha256 in the human approval line (§1.6);
current value, **pending human approval**: `e41f63ef47ea066f14e5effb41bf9f4b7ebd8d79641604b69a10323837e09474` (replaced if the file changes again). The only exception is T12, which runs in tmp; its outputs are never opened, printed or logged.

M3 is **descriptive only**. Every output reports the OBSERVED value next to its NULL REFERENCE under uniform 6-of-55 sampling
without replacement, plus 1 special number drawn from the remaining 49 (H1/H2/H5 null). M3 produces **no** p-values, test verdicts,
"significant/deviates/anomaly" language or multiplicity-corrected claims. Inference belongs to M4.

- There are no "hot/cold/overdue/due/lucky" labels and no rankings. Per-number and per-pair tables are sorted by number or pair, never
  by value, and there are no "top-N" lists. Charts use the number (1..55) on the axis in natural order.
- Every table with per-number or per-pair values includes `expected`, a pointwise null band (`null_lo`, `null_hi`) and, where
  defined, a simultaneous band (`sim_lo`, `sim_hi`, §3.3).
- Every chart draws its null reference: an expected line or bars plus a band. The caption states the reference and whether it is `exact` or `MC(R, seed)`.
- Summary language follows OBSERVED → NULL REFERENCE → LIMITATION. No INTERPRETATION section is allowed in M3 beyond "see M4".
- The M4 confirmatory tests of H1–H5 run on the same 00001–01190 draws. Any new hypothesis that EDA suggests is **exploratory**.
  It cannot join the confirmatory set on these data; it may be tested only in the post-M6 replication (ruling), or by a change request made before that.

## 1. Data range rule

1.1 **Single parameter:** `--through-draw DDDDD`. It must match `^\d{5}$`; anything else (e.g. `1190`, `abc`) means exit 2. All comparisons use `int()`. The analysis set is `fact_draw` rows with `draw_id <= through_draw`.
    It starts at 00001. Its draw_ids must be contiguous; otherwise the run stops with exit 2.
    Default `01190` (train + validation). `00980` (train only) must also work.
1.2 **Ceiling (M0-R ruling, binding):** `EDA_MAX_THROUGH_DRAW = "01190"` is a module constant in `src/reporting/eda.py`. No outcome
    statistic may be computed on the test period 01191–01401 or on live draws (≥ 01402). The full range 00001–01401 is used only by the
    M2 data-quality and structural checks, which do not use number outcomes. EDA does not call them.
    If `--through-draw` is above the ceiling, the run exits 2, writes nothing and logs `eda_ceiling_refused`,
    **unless** `--override-ceiling <REF>` is given. The ruling allows an override only after the M6 final test evaluation is locked, as a
    one-time replication that never feeds back into models. The override is accepted only if `<REF>` appears on a line inside a
    Decisions section of `<paths.root>/docs/TASKBOARD.md` and that line also contains the literal text `EDA ceiling override`. Only the human
    Project Lead writes that line. **Matching rules:**
    - A Decisions section starts at a line matching `^### Decisions\b` and runs until the next heading of level ≤ 3 (`^#{1,3} `).
    - REF must match `^[A-Z]+-\d+$`, or the run exits 2.
    - REF is matched as a whole token: `(?<![\w-])REF(?![\w-])`, so `D-1` does not match `D-12`.
    - The ceiling is checked before any data read. A refusal never calls `read_fact_draw`.
    When the override is accepted, the run logs a WARNING event `eda_ceiling_override` with the REF and through_draw,
    writes to `through_<DDDDD>_override/`, and records `override_ref` in the manifest, in every CSV and in the summary header.
    Without the override, `override_ref` is empty. An unknown REF means exit 2 and nothing written.
1.3 **Versions recorded in every output** (every CSV has the columns, and the manifest and the summary header record them too):
    `source_dataset_version` is metadata only. It is the single distinct value of the `fact_draw.dataset_version` column
    among the analysis rows, read as-is and never recomputed. If there is more than one value, exit 2.
    `analysis_version` is `tables.dataset_version(analysis rows)`. `through_draw` and `n_draws` are also recorded.
    Pinned values on `ds_cbdf3834368e`: ≤01190 gives `ds_16b6be697acb` (1,190 draws); ≤00980 gives `ds_523f687e20df` (980 draws).
1.4 **Single choke point:** `load_analysis_draws` is the only EDA code that calls `tables.read_fact_draw`. It filters immediately,
    validates the analysis rows (6 distinct ints in 1..55, ascending, special ∉ main or NA) and returns only those rows. Rows after the
    cutoff are never validated, aggregated, hashed or logged. The main numbers used are n1..n6. `fact_draw_number` and `dim_number` are not read.
    `band`/`parity` are recomputed with `tables.build_dim_number()` (low = 1..27, high = 28..55; 28 odd numbers, 27 even).
1.5 **Time index:** `t = 1..n` is the row ordinal after sorting by draw_id. Calendar periods come from `draw_date` (year `YYYY`, quarter `YYYY-Qq`).
    `partial = True` when a period starts before draw 00001's date or ends after the last analysis draw's date. With the default range,
    **2017 (from 2017-08-01) and 2025 (to 2025-05-15, draw 01190) are partial** (ruling), and so are their edge quarters. The flag is shown in tables, chart labels and the summary.
1.6 **Spec-approval gate:** `check_spec_approval(root) -> (version, sha256)` runs first, before the ceiling check and before any data read.
    It uses the §1.2 section rule to find, in a Decisions section, the last line matching `SPECIFICATION (v\d+(?:\.\d+)+) APPROVED sha256=([0-9a-f]{64})\b`.
    The version is compared as an integer tuple (v1.10 = (1, 10) > v1.2 = (1, 2); v1.2.1 = (1, 2, 1)) and must be ≥ (1, 2); the sha256 of `<root>/docs/SPECIFICATION.md` must equal the approved hash. Otherwise the run exits 2,
    writes nothing and logs `eda_spec_not_approved`. The version and sha256 go into `eda_manifest.json` and the summary header.

## 2. Metric definitions

Notation: a draw is x₁<…<x₆ (main numbers only). N = 55, k = 6, p = 6/55, n = number of analysis draws.

| id | metric | definition |
|---|---|---|
| D1 | `sum` | Σxᵢ |
| D2 | `min`, `max`, `range` | x₁, x₆, x₆−x₁ |
| D3 | `odd_count` / `even_count` | #{xᵢ odd}, 6 − odd |
| D4 | `low_count` / `high_count` | #{xᵢ ≤ 27} per dim_number band, 6 − low |
| D5 | `consecutive_pairs` | #{i ∈ 1..5 : xᵢ₊₁ − xᵢ = 1} (a run 3,4,5 counts as 2) |
| D6 | `gap_1..gap_5`, `max_gap`, `min_gap` | gᵢ = xᵢ₊₁ − xᵢ; max and min over i |
| N1 | `count`, `rel_freq` | fₖ = #{t : k ∈ draw t}; fₖ/n with 95% Wilson CI (z = 1.959964, `statistics.NormalDist`) |
| N2 | by period | fₖ within each year and each quarter; `n_draws` and `partial` (§1.5) per period are shown |
| N3 | rolling | trailing window of the last W draws, inclusive of t, for t ≥ W; W ∈ `--windows` (default 50,100,200) |
| N4 | inter-arrival gap | ordinals t₁<t₂<… where k appears; gaps t_{j+1}−t_j. The first gap (t₁) and the last (n − t_last) are censored and excluded from the pooled distribution |
| N5 | first/last appearance | draw_id and ordinal of t₁ and t_last per number (no "draws since" column) |
| N6 | cumulative | cₖ(t) = appearances of k in draws 1..t; charted as the deviation cₖ(t) − pt |
| S1 | special frequency | as N1 for `special_number` (NA rows excluded and counted) |
| P1 | co-occurrence | n_ij = #{t : i, j ∈ draw t}, i<j (1,485 pairs); 55×55 matrix with diagonal fₖ |
| P2 | stability | the analysis range is split into `--n-blocks` (default 5) contiguous blocks (`numpy.array_split` on ordinals). For every block pair (a<b), Pearson r between block count vectors: level `number` (55-vector fₖ) and level `pair` (1,485-vector n_ij) |

EDA metrics are computed over the whole analysis range, including draw t in its own window. They are not features and must not be reused
as M5/M6 features: features for draw t use only draws < t (SPECIFICATION §8).

## 3. Null references

### 3.1 Exact (closed form; each checked against brute-force enumeration for (N,k) ∈ {(10,3),(12,4),(11,6)})

All functions take `N=55, k=6` as parameters so that tests can enumerate small cases. C(·,·) = `math.comb`, which is 0 outside its support.

| metric | null pmf / moments |
|---|---|
| sum | pmf by 0/1-knapsack DP over k-subsets of 1..N, divided by C(N,k); support 21..315, symmetric; **E = 168, Var = k·(N²−1)/12·(N−k)/(N−1) = 1372** (SD 37.04) |
| min | P(x₁ = m) = C(N−m, k−1)/C(N,k); E = (N+1)/(k+1) = 8 |
| max | P(x₆ = m) = C(m−1, k−1)/C(N,k); E = k(N+1)/(k+1) = 48 |
| range | P(R = r) = (N−r)·C(r−1, k−2)/C(N,k), r = k−1..N−1; E = 40 |
| odd_count | Hypergeometric(N=55, K=28, k=6); E = 168/55 |
| low_count | Hypergeometric(N=55, K=27, k=6); E = 162/55 |
| consecutive_pairs | P(C = c) = C(k−1, c)·C(N−k+1, k−c)/C(N,k); **E = (N−1)·k(k−1)/(N(N−1)) = 6/11**; P(C=0) = C(50,6)/C(55,6) = 0.548150 |
| gap gᵢ (each i) | spacings are exchangeable: P(g = d) = C(N−d, k−1)/C(N,k), d = 1..N−k+1; E = 8 |
| min_gap | P(min_gap ≥ d) = C(N−(k−1)(d−1), k)/C(N,k); so P(min_gap ≥ 2) = P(C=0) |
| max_gap | P(max_gap ≤ g) = Σ_s c_g(s)·(N−s)/C(N,k), where c_g(s) = #(k−1)-tuples in [1,g] summing to s ≤ N−1 |
| fₖ (N1, N2, N3) | Binomial(m, p) marginally, with m = n, n_period or W; Corr(fᵢ, fⱼ) = −1/54 |
| special | Binomial(n', 1/55) marginally, with **n' = n_nonmissing** (draws with a special); all special bands and z use n' |
| inter-arrival | per number, Geometric(p): P(g) = (1−p)^{g−1}p, memoryless. **Exact expected count of uncensored gaps of length g over all 55 numbers in n draws: E_g = 55·(n−g)·p²·(1−p)^{g−1}**, for g = 1..n−1. Pooling uses E_g only: cells g = 1..g₀ with g₀ = max{g : E_g ≥ 5}; top cell `≥g₀+1` = Σ_{g>g₀} E_g (the whole tail), merged into cell g₀ if < 5. 55/6 and √74.86 are only **approximate** mean/SD (finite-n truncation) |
| cₖ(t) | Binomial(t, p) |
| n_ij | Binomial(n, q), **q = C(53,4)/C(55,6) = 1/99**; Σ_{i<j} n_ij = 15n; Σ_{j≠i} n_ij = 5fᵢ |

Pointwise band: `null_lo = binom.ppf(0.025, m, p)` and `null_hi = binom.ppf(0.975, m, p)`. These are central quantiles with coverage ≥ 95%.
The same rule applies to expected category counts of discrete draw metrics (count per category ~ Binomial(n, P(category))).
Standardized residual `z = (obs − mp)/√(mp(1−p))`. It is descriptive, and no threshold is applied.

**Cell pooling (finding 5), decided from null probabilities and n only, never from observed counts.** The table
`draw_metric_distribution.csv` merges tail cells inward until every cell has null expected count n·P ≥ 5. Each tail is handled separately,
and the resulting labels look like `≤3`, `≥12`. **Sum** uses fixed width-10 bins 21–30, 31–40, …, 311–315, and then the same tail
pooling. Their bin probabilities are sums of the **exact DP pmf**; a normal approximation is never used. **Consecutive_pairs** pools to
{0, 1, 2, ≥3}: the null P = 0.548150, 0.365434, 0.079442, 0.006974, so n·P(≥3) = 6.8 at n = 980 and 8.3 at n = 1190.
Odd and low counts need no pooling at n ≥ 980 (smallest expected count 10.0). The unpooled exact pmfs are written to `null_pmfs.csv` (metric, value, prob).

### 3.2 Monte Carlo null model (`src/statistics/null_model.py`)

`simulate_draws(n_draws, rng, N=55, k=6) -> (main[int16, n×k] ascending, special[int16, n])`:
`u = rng.random((m, N))`; `perm = np.argsort(u, axis=1, kind="stable")[:, :k+1] + 1`; `main = sort(perm[:, :k])`; `special = perm[:, k]`.
This is an exact uniform k-subset, and the special is uniform over the remaining N−k numbers.
Generate in chunks of whole draws. The output must not depend on chunk size.
The RNG is `np.random.default_rng(np.random.SeedSequence([EDA_SEED, stream_id]))` with `EDA_SEED = 20260924`. `stream_id` values are fixed
integers listed in the module (1 = replicate datasets). R = `--mc-reps`, default **10,000**. R, seed, stream and the numpy version are recorded in the manifest.

### 3.3 MC-derived references (`src/statistics/mc_reference.py`)

`replicate_references(n, windows, n_blocks, reps, seed) -> pd.DataFrame` (long form: statistic, param, quantile, value, reps, seed).
It simulates R replicate datasets of n draws, streamed in chunks of replicates; the output must be invariant to the chunk size. For each replicate it records:
min/max over k of fₖ, and of the special counts simulated over n' = n_nonmissing draws (simultaneous bands `sim_lo` = 2.5% quantile of the min, `sim_hi` = 97.5% quantile of the max);
min/max of n_ij over 1,485 pairs; max_k z and min_k z of the first W draws for each W (the rolling envelope; **pointwise per window**, so ≈2.5% of windows fall outside on each side by chance); and the Pearson r for every
block pair at both levels (mean and 2.5/97.5% quantiles). The Pearson X² of the replicate is kept only as a self-check (§6 T4), and it is not output as a test.

## 4. Code layout (pure functions in statistics; I/O in reporting)

| module | functions (all pure: DataFrame/ndarray in, DataFrame out; no I/O, no globals mutated) |
|---|---|
| `src/statistics/null_model.py` | constants `N_NUMBERS, K_MAIN, P_NUMBER, Q_PAIR, EDA_SEED`, `rng_for(stream_id, seed)`, `simulate_draws` |
| `src/statistics/null_reference.py` | `sum_pmf, min_pmf, max_pmf, range_pmf, hypergeom_pmf, consecutive_pairs_pmf, gap_pmf, min_gap_pmf, max_gap_pmf, geometric_pmf, binomial_band, wilson_ci` (all return `pd.Series` indexed by value, or a tuple) |
| `src/statistics/eda.py` | `draw_metrics, draw_metric_distribution, draw_metric_summary, number_frequency, number_frequency_by_period, rolling_number_counts, interarrival_gaps, appearance_summary, cumulative_counts, special_frequency, pair_cooccurrence, pair_count_distribution, block_stability` |
| `src/statistics/mc_reference.py` | `replicate_references` |
| `src/reporting/eda.py` | `EDA_MAX_THROUGH_DRAW`, `decision_lines(taskboard_path)` (§1.2 section rule), `check_spec_approval(root)`, `check_ceiling(through_draw, override_ref, taskboard_path) -> str` (§1.2; raises on refusal), `load_analysis_draws(curated_dir, through_draw) -> AnalysisData(frame, source_dataset_version, analysis_version)`, `build_eda(data, params) -> EdaResult`, `write_eda(result, out_dir)`, `render_summary(result) -> str` |
| `src/reporting/eda_charts.py` | one function per PNG; `matplotlib.use("Agg")`; fixed figsize/dpi = 120; `savefig(..., metadata={"Software": None})` |

CLI (`src/cli.py`, following the existing `main(argv, paths=None)` pattern):
`python -m src.cli eda [--through-draw 01190] [--out-dir outputs/eda] [--windows 50,100,200] [--n-blocks 5] [--mc-reps 10000] [--override-ceiling REF]`.
The output goes to `<out-dir>/through_<DDDDD>/`. Files are written to a temp dir and then `os.replace`d, with the manifest written last. Exit 0 = ok, 2 = bad range/params/data/spec gate. Order: parse → spec gate → ceiling → load.

## 5. Outputs (deterministic)

CSV: UTF-8, `lineterminator="\n"`, `float_format="%.10g"`, fixed column order, rows sorted by key (draw_id / number / (i,j) / value).
Every CSV carries `source_dataset_version, analysis_version, through_draw, override_ref`. No wall-clock timestamps appear anywhere.

| file | key columns (plus the version columns) |
|---|---|
| `draw_metrics.csv` | draw_id, draw_date, n1..n6, D1–D6 |
| `draw_metric_distribution.csv` | metric, cell (pooled label, §3.1), observed_count, observed_share, null_prob, expected_count, null_lo, null_hi, reference=`exact` |
| `null_pmfs.csv` | metric, value, prob (unpooled exact pmfs; null only, no observed data) |
| `draw_metric_summary.csv` | metric, n, obs_mean, obs_sd, obs_q05/q25/q50/q75/q95, null_mean, null_sd, null_q05…q95 |
| `number_frequency.csv` | number, parity, band, count, n_draws, rel_freq, wilson_lo, wilson_hi, expected, null_lo, null_hi, sim_lo, sim_hi, z |
| `number_frequency_by_period.csv` | period_type, period, partial, number, count, n_draws, expected, null_lo, null_hi, z |
| `number_rolling_W{W}.csv` | window_end_draw_id, number, count, expected, null_lo, null_hi, z |
| `number_rolling_extremes_W{W}.csv` | window_end_draw_id, max_z, min_z, mc_max_z_q975, mc_min_z_q025 |
| `number_interarrival.csv` | cell (`g` or `≥g`), observed_count, expected_count (exact E_g, §3.1), null_share = E/ΣE (uncensored gaps) |
| `number_appearance.csv` | number, first_draw_id, last_draw_id, n_gaps, mean_gap, sd_gap, approx_expected_mean_gap, approx_expected_sd_gap |
| `number_cumulative.csv` | draw_id, number, cumulative_count, expected, null_lo, null_hi |
| `special_frequency.csv` | as number_frequency (p = 1/55, n' = n_nonmissing), plus n_nonmissing, n_missing_special |
| `pair_cooccurrence.csv` | number_i, number_j, count, expected, null_lo, null_hi, sim_lo, sim_hi, z |
| `pair_count_distribution.csv` | count, observed_pairs, null_prob, expected_pairs |
| `stability_blocks.csv` | level, block_a, block_b, first/last draw_id of each, pearson_r, mc_mean_r, mc_lo_r, mc_hi_r |
| `mc_reference.csv` | output of `replicate_references` |

PNG (each chart shows the null reference named in its caption):
`draw_sum.png` (histogram in width-10 bins vs exact binned expected counts ± pointwise band), `draw_min_max_range.png`,
`draw_odd_low_consecutive.png`, `draw_gaps.png` (pooled gᵢ and max_gap vs exact), `number_frequency.png` (bars 1..55, expected line,
pointwise band and simultaneous band), `number_frequency_by_year.png` (z heatmap, fixed scale ±4, diverging), `number_rolling_W{W}.png`
(max/min z vs the MC envelope; caption: "pointwise envelope: ≈2.5% of windows outside on each side by chance"), `number_cumulative_deviation.png` (55 grey lines ± 1.96√(tp(1−p))), `number_interarrival.png` (observed vs the exact expected counts E_g, §3.1),
`special_frequency.png`, `pair_cooccurrence_heatmap.png` (z, fixed scale ±4), `pair_count_distribution.png` (vs Binomial(n,1/99)),
`stability_blocks.png` (r per block pair vs MC interval).

`eda_summary.md` is built **only** from fixed text plus templated count sentences, with the templates held as constants in `src/reporting/eda.py`.
It never names an individual number or pair and never mentions first or last appearance. Allowed templates (e = exact null expected count Σ P(outside band)):
- `{metric}: observed mean {x} (null {mu}); {k} of {m} cells outside the pointwise band ({e} expected).`
- `{k} of 55 numbers outside the pointwise band ({e} expected; nominal 2.75); {j} outside the simultaneous band.` (same form for the special numbers and year cells)
- `{k} of 1,485 pairs outside the pointwise band ({e} expected; nominal 74); {j} outside the simultaneous band.`
- `W={W}: {k} of {m} windows above and {j} below the pointwise envelope (≈2.5% expected on each side; windows overlap).`
- `{k} of {m} within-draw gap cells (D6) outside the pointwise band ({e} expected).` and `{k} of {m} block pairs with r outside the MC 95% interval ({e} expected).`

The header records the versions, the approved spec version and sha256, and the parameters. The fixed LIMITATIONS text states that:
- there is no inference, and M4 decides;
- pointwise bands and the envelope are exceeded about 5% of the time by chance;
- rolling windows overlap and are autocorrelated;
- gaps are memoryless under the null;
- the drawing order is hidden;
- MC references carry Monte Carlo error;
- 2017 and 2025 are partial years;
- the M4 confirmatory tests use the same draws;
- nothing here is evidence that future draws can be forecast.
`eda_manifest.json`: parameters, versions, `spec_version`, `spec_sha256`, seed/streams/R, library versions, and the sha256 of every file.

## 6. Tests (`tests/test_eda_*.py`; synthetic fixtures via `tmp_path` + the `paths` fixture; never write to the real `outputs/`)

| id | test | acceptance criterion |
|---|---|---|
| T1 | draw metrics, hand examples | (1,2,3,53,54,55): sum 168, min 1, max 55, range 54, odd 4, low 3, consecutive 4, gaps [1,1,50,1,1], max_gap 50, min_gap 1. (5,10,14,23,24,38): sum 114, range 33, odd 2, low 5, consecutive 1, gaps [5,4,9,1,14] |
| T2 | exact pmfs vs brute force | for (N,k) ∈ {(10,3),(12,4),(11,6)}, every §3.1 pmf equals enumeration over `itertools.combinations` (abs err < 1e-12) |
| T3 | known constants (N=55,k=6) | each pmf sums to 1 ± 1e-12; E[sum] = 168, Var[sum] = 1372; sum pmf symmetric; E[min] = 8, E[max] = 48, E[range] = 40; E[C] = 6/11; P(C=0) = C(50,6)/C(55,6); E[gap] = 8; Q_PAIR = 1/99; P_NUMBER = 6/55; geometric mean 55/6 |
| T4 | simulator correctness | 200,000 draws: rows are 6 distinct ascending values in 1..55 and the special ∉ main; each number's rate is within 5 SE of 6/55; the special's rate is within 5 SE of 1/55; mean sum within 4·√(1372/m) of 168; TV distance (consecutive pmf) < 0.01; 2,000 datasets of n = 200 have mean Pearson X² within 4 SE of **49** (not 54) |
| T5 | RNG determinism | same seed gives identical arrays; chunk sizes 1, 7 and m give identical arrays; `replicate_references` is identical for replicate-chunk sizes 1, 3 and R; different stream_id gives different arrays |
| T6 | number level, hand fixture (4–6 draws) | counts, Wilson (5/10 → [0.2366, 0.7634]; 0/10 → [0, 0.2775], 4 dp), period counts, rolling counts (Σₖ = 6W per window), gaps (appearing at t = 2,5,6 → [3,1] with censored gaps excluded; E_g matches a brute-force sum for small n; pooled cells use E_g only), first/last, cumulative |
| T7 | pair level | matrix symmetric; diagonal = fₖ; Σ_{i<j} n_ij = 15n; Σ_{j≠i} n_ij = 5fᵢ; the hand fixture matches; stability r = 1 for identical blocks |
| T8 | range respected | (a) rows after the cutoff replaced by different valid draws, and (b) rows appended with invalid content (number 99): every output byte-identical to the clean fixture, with no error; (c) no output draw_id > through_draw; (d) `--through-draw 01191` without an override, or with a REF absent from the fixture TASKBOARD (`paths.root` = tmp) → exit 2, no files written, `eda_ceiling_refused` logged; a REF only in a non-Decisions section, only after the next level ≤ 3 heading, or given as a substring (`D-1` vs a line with only `D-12`) → exit 2; a malformed REF → exit 2; a spy asserts `read_fact_draw` is never called on refusal; a heading with a suffix (`### Decisions after the audit`) counts; with a valid REF on a Decisions line containing `EDA ceiling override` → it runs, writes to `through_01191_override/` and records `override_ref` everywhere, and the real `docs/TASKBOARD.md` is never read; (e) a non-existent or non-contiguous cutoff, or a malformed `--through-draw` (`1190`, `abc`) → exit 2; (f) `read_fact_draw` is called only from `load_analysis_draws` (monkeypatch spy / grep test); (g) the fixtures in (a)/(b) keep the `dataset_version` column constant; changing only that column's value changes only `source_dataset_version` in the outputs (CSVs equal after dropping that column; manifest differs only there and in file hashes) |
| T9 | versions | every CSV has the 4 version/override columns with a single value; on the real curated data (read-only), ≤01190 gives `ds_16b6be697acb` and ≤00980 gives `ds_523f687e20df` |
| T10 | determinism | two runs (`--mc-reps 200`) give identical sha256 for all CSV/MD/JSON; PNG identical within one environment |
| T11 | framing guard | no case-insensitive whole-word match of: hot, cold, overdue, due, lucky, recommend\*, predict\*, significan\*, p-value, pvalue, rank\*, best, top, anomal\*, streak, bet/bets/betting/bettor, ticket\*, wager\*, pick/picks/picked/picking, deviat\* (\* = prefix; `deviation` allowed only in the fixed N6 chart title) in `eda_summary.md`, CSV headers or chart titles; every non-blank summary line equals a fixed line or matches a §5 template regex (whitelist), so there are no per-number rows, no number or pair identifiers and no first/last appearance; per-number/pair CSVs are sorted by key and contain `expected, null_lo, null_hi` |
| T12 | CLI smoke | real curated data (read-only), `--mc-reps 200`, tmp `paths.root` with a fixture SPECIFICATION + approval line, into `tmp_path`; outputs are never opened, printed or logged: exit 0, all §5 files exist, and the manifest hashes match the files |
| T13 | pooling and partial periods | pooled cells: null probs sum to 1 ± 1e-12 and every cell has n·P ≥ 5; the pooling is identical for two fixtures with the same n but different observed draws; consecutive_pairs cells = {0,1,2,≥3} at n ∈ {980, 1190}; sum bin probs equal the sums of the exact pmf; `partial` flags a fixture's first and last years, and on the real range 2017 and 2025 are partial and 2018–2024 are not |
| T14 | spec gate | no approval line, a version < v1.2 (e.g. v1.1, v1.1.9), or a sha mismatch → exit 2, nothing written, `eda_spec_not_approved` logged, spy: `read_fact_draw` not called; a valid line in the fixture (including v1.10 and v1.2.1, both ≥ v1.2 by tuple comparison) → it proceeds, and the manifest records version and sha |

Full suite: `python -m pytest` stays green. Runtime target: the CLI with R = 10,000 finishes in < 10 min; tests use R ≤ 2,000.

## 7. Dependencies

- `matplotlib>=3.8` is **required**. It is the only way to produce PNG charts; the Agg backend needs no GUI. It is not installed now.
- `numpy>=1.26` is listed explicitly. It is already installed transitively via pandas, but it is now imported directly.
- `scipy>=1.11` is used for `binom.ppf`, `hypergeom.pmf` and `geom.pmf`. It is already installed (1.18.1) but is not in `requirements.txt`, and M4 needs it anyway
  (KS test, χ²). Hand-rolling binomial quantiles would be more error-prone than adding scipy. Tests check the scipy-based values against `math.comb` (T2/T3).
- No seaborn, statsmodels or plotly in M3.

## 8. Open items for review

O1: resolved by the M0-R ruling (00001–01190; override only by a human decision after the M6 lock). O2: resolved by TASKBOARD E2 and
SPECIFICATION v1.2 §7 (W rule frozen before any M3 output is opened; `validation-exposed` flag).
O3: R = 10,000 matches SPECIFICATION §6. The MC standard error of a tail quantile is not reported in M3 (it is noted in the limitations).
