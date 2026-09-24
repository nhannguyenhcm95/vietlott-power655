# M0 — Specification (pre-code checklist)

This file fills the Pre-Code Checklist in `PROJECT_STEPS.md` §16. Modeling work (M5+) must follow it;
changes to this file must be made before, not after, looking at test-period results.

## 1. API source / adapter strategy — DONE

- Interface: `DrawSource.iter_raw_pages(start_date, end_date, stop_at_draw_id)` (I/O) + `DrawSource.parse(page)` (pure).
  Raw pages are archived before parsing.
- Primary: `vietlott_official`, which uses the vietlott.vn AjaxPro endpoint `Game655CompareWebPart.ServerSideDrawResult`.
  Pagination uses `PageIndex` from 0, with 8 draws per page, newest first. An empty page ends the history.
  The `Key` argument is read from the results page, with a configured fallback.
- Secondary: `github_mirror`, from vietvudanh/vietlott-data `power655.jsonl`. Used only to reconcile against the primary.
- HTTP controls: timeout, bounded retries (4) with exponential backoff and jitter, `Retry-After` on 429, 1 s minimum interval between requests.
- Incremental mode stops paginating when a page reaches the newest stored draw.

## 2. Historical coverage target — DONE

All draws from 00001 (2017-08-01) to the latest published draw. First full load: 1,401 draws (00001–01401, up to 2026-09-22).
Draws are held on Tue/Thu/Sat, so a refresh after each draw night keeps coverage current.

## 3. Schema — DONE

`PROJECT_STEPS.md` §5, as implemented in `src/transformation/tables.py`:
`fact_draw`, `fact_draw_number` (positions 1–6 main, 7 special), `dim_number`, `ingestion_log`, `quality_log`.
Main numbers are stored in ascending order, because the official source publishes them sorted and does not expose drawing order.

## 4. Validation rules — DONE (`src/validation/rules.py`)

| rule | severity |
|---|---|
| draw_id is 5 digits; unique; no conflicting duplicate | error |
| draw_date parseable, not after today (Asia/Ho_Chi_Minh) | error |
| exactly 6 integer main numbers in 1..55, all distinct | error |
| special number in 1..55 and not among main numbers | error |
| draw_id order matches strictly increasing draw_date | error |
| stored row changed by source (history is never rewritten) | error |
| special number missing; draw not on Tue/Thu/Sat; unsorted main; gap in draw_id | warning |
| duplicate content: same sorted main numbers + special as an earlier draw (date not compared) | warning |

### 4a. Data quality report — DONE (M2-T2, `src/reporting/data_quality.py`)

`python -m src.cli quality-report [--as-of ISO8601] [--out-dir reports] [--known-issues configs/known_issues.json]`
is a pure, offline, deterministic generator: curated + staging + raw + logs + `configs/known_issues.json` in,
`reports/data_quality_<date>.md` + `.json` out, with one overall PASS/WARN/FAIL. It never touches the network and
never writes outside `--out-dir`. Full rule table, check list and known-issue mechanism:
`docs/design/M2-data-quality-and-refresh.md` §1 (binding design note).

Additional integrity rules beyond §4, checked only by the report (not by ingestion):

| rule | level | definition |
|---|---|---|
| `retrieved_after_draw` | FAIL | `retrieved_at` must be at or after the draw's 18:00 ICT |
| `frozen_prefix` | FAIL, never acceptable | draws up to `01401` must always hash to `ds_cbdf3834368e` |
| `raw_lineage` | FAIL (official) / WARN (mirror) | every staging row must match a record re-parsed offline from its archived raw run |
| `curated_matches_staging`, `manifest_consistency`, `first_draw` | FAIL | curated/staging/manifest agree; history starts at 00001 on 2017-08-01 |
| `freshness` | WARN (1–6 missed scheduled draws) / FAIL (>6) | draws expected by the Tue/Thu/Sat 18:00 ICT schedule, 21:00 deadline |
| `incremental_empty_fetch`, `mirror_shrink`, `log_integrity` | see design §1.3/§1.4 | ingestion-run and log-integrity checks |

Known issues (`configs/known_issues.json`) let a reviewed, approved entry mark a specific finding as `accepted`
without hiding it — the finding is still listed, and integrity rules (schema, lineage, checksums, `frozen_prefix`,
`retrieved_after_draw`, official duplicates) can never be accepted. Approval fields may only be filled by copying
a decision recorded under `docs/TASKBOARD.md` "Decisions"; see `docs/design/M2-data-quality-and-refresh.md` §1.5.

## 5. Research hypotheses

H1 (distribution). Each number 1..55 appears among the main numbers with probability 6/55 per draw.
H2 (special). The special number is uniform on 1..55 at the margin.
H3 (independence). The main-number set of draw *t* is independent of draws *t−1..t−L* (L = 1..10).
H4 (stability). The per-number frequency distribution is the same across calendar years and across rolling windows.
H5 (draw-level aggregates). The sum, range, odd count, low count and consecutive-pair count follow the distributions implied by uniform 6-of-55 sampling without replacement.
H6 (model). No experimental model beats Baseline 0 out-of-sample by more than sampling noise.

All of these are null hypotheses. Failing to reject them is a valid result and will be reported.

## 6. Statistical tests

- **Exact null by simulation.** The primary null distribution comes from Monte Carlo simulation of the real mechanism: 6 of 55 without replacement, plus 1 special number from the remaining 49. Use at least 10,000 replicates with a fixed seed.
  This matters because per-number counts are negatively correlated. Under H1 the Pearson statistic has expectation 55·(1−6/55) = 49, not 54, so the naive χ²(54) reference is conservative. If a χ² approximation is reported, scale it by 54/49 and state that.
- H1/H2: Pearson χ² GOF (simulation p-value), standardized residuals per number, Holm correction across 55 numbers, and Wilson 95% CIs for per-number rates.
- H3: overlap count between draw *t* and draw *t−k* compared with its hypergeometric null (mean 36/55). Also a permutation test that shuffles draw order, runs tests on above/below-median draw sums, and the ACF of the draw-sum series with Ljung–Box.
- H4: χ² homogeneity (years × numbers, with a simulated p-value), rolling-window χ² statistics against their simulated envelope, and Cramér's V as the effect size.
- H5: compare empirical distributions with the simulated or exact ones using the KS test for sums and χ² for discrete counts.
- Each test reports its statistic, p-value, effect size, n and an interpretation. The significance level is α = 0.05 before multiplicity correction.

## 7. Baseline definitions

Each target *t* and number *k* has a binary target `y[t,k] = 1` if *k* is among the main numbers of draw *t*.

- **Baseline 0 (theoretical):** p = 6/55 for every *k*.
- **Baseline 1 (historical frequency):** the Laplace-smoothed share of past appearances of *k* over draws before *t*, then rescaled so that Σₖ p = 6.
- **Baseline 2 (rolling window):** the same as Baseline 1 over the last W draws, with W ∈ {50, 100, 200} chosen on validation only.
- **Aggregate target:** the draw sum, where the baseline forecast is the theoretical mean 6·28 = 168.

## 8. Temporal split rules

- Ordering is by draw_id. There is no shuffling.
- The split is frozen on `dataset_version = ds_cbdf3834368e` (1,401 draws):
  - train: 00001–00980 (70%)
  - validation: 00981–01190 (15%)
  - test: 01191–01401 (15%)
  The test set is evaluated once, after model selection is final.
- Rolling evaluation uses an expanding window with an initial 500 draws, a 50-draw step and a 50-draw horizon. Every fold is reported, not only the best one.
- Features for draw *t* may use only draws with draw_id < *t*. Scalers and encoders are fit inside each training fold.
- New draws published after the freeze form a later "live holdout". They are never merged into the frozen test set.

## 9. Evaluation metrics

- Probabilistic targets: log loss and Brier score, both averaged over (t, k), plus reliability diagrams and ECE. Each is reported with a block-bootstrap 95% CI and a paired difference against Baseline 0.
- Aggregate targets: MAE and RMSE compared against the baseline.
- Every experiment row records: experiment_id, dataset_version, feature_version, model, params, train/val/test periods, metrics and notes.

## 10. Repository structure — DONE

This follows `PROJECT_STEPS.md` §14. `src/` contains `api`, `ingestion`, `validation`, `transformation`, `features`, `statistics`, `models`, `evaluation` and `reporting`, and `tests/` mirrors it.

## 11. Definition of Done (per milestone)

- The code is covered by the targeted tests, and the full `pytest` suite passes.
- Data outputs are reproducible from raw data plus code, and `dataset_version` is recorded.
- Documentation is updated (this file and the README).
- The completion report states the files changed, a summary, the tests run, the results, the limitations and the next task.
