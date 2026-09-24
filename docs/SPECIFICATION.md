# M0 — Specification (pre-code checklist)

This file fills the Pre-Code Checklist in `PROJECT_STEPS.md` §16. Modeling work (M5+) must follow it;
changes to this file must be made before, not after, looking at test-period results.

## Spec version / changelog

Freeze rule: before the M6 test run, the SHA-256 of this file is recorded under `docs/TASKBOARD.md` "Decisions",
together with the human approval. The M6 run records that hash, and it must match. After the freeze, any change
needs a new EXPERIMENT_ID and a change request (AI-agent.md §12, §14). Such a change can never alter the primary
result of a test run that has already been produced.

| version | date | author | change |
|---|---|---|---|
| v1.0 | 2026-09-24 | main session | First pre-code checklist. |
| v1.1 | 2026-09-24 | ml-researcher | Rework after audit `docs/design/M0-audit-2026-09-24.md`. Findings addressed: **1** (§8 dev folds end at 01190; per-phase data-access rule), **2** (§5 H6 and §9.3 decision rule), **8** (§9 bootstrap, Baseline 0 degeneracy, Σp, set-level score, MAE/RMSE), **9** (§7 α, Baseline 2 short history, features vs fitted parameters), **10** (changelog and freeze, experiment record fields, live holdout). **PENDING: findings 3–7 (§5 H1–H5 and §6) belong to the statistician and are NOT yet addressed. §6 must not be used for M4 until v1.2 is audited.** |
| v1.2 | 2026-09-24 | statistician | Findings **3** (§6.2 confirmatory family of 13 tests with Holm FWER 0.05; §6.3 parent-gated follow-ups with Holm within each set; §6.4 exploratory label), **4** (C7/C8: whole-draw permutation null, never fixed-margin; W = 170, step 85; global max statistic; Cramér's V with PERM null mean and N = 6n), **5** (C9–C13: exact DP sum pmf with MC D statistic; low = 1–27; consecutive pairs pooled to {0,1,2,≥3}), **6** (C2: χ²(54)/simulated reference, no 54/49 scaling; conditional test exploratory), **7** (C3 overlap statistic; C6 tie rule, y = 168 dropped; Ljung–Box lag fixed at 10; simulated p = (1+#)/(R+1)). Also: §5 H1–H5 made concrete; R = 10,000, seed 20260924, streams 101/102, MC escalation rule; §7 Baseline 2 W selection frozen and `validation-exposed` flag (Project Lead authorisation, TASKBOARD E2; the only §7 edit); §9.4 code_version = git SHA, clean tree required for M6. |
| v1.2.1 | 2026-09-24 | statistician | Re-audit line fixes. **S1** (§7 fitted quantities vs configuration choices; §8.3 hyperparameter vs configuration definitions; §8.4 no-op refit for Baselines 1 and 2; auditor's wording, Project Lead authorisation), **S2** (§6.2 C7 "not 8·54 = 432"), **S3** (§6.1 overlap moments stated directly), **S4** (§6.5 calibration bounds [0.0175, 0.090], fixed seed, failure → investigation). |

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
H2 (special). The special number is uniform on 1..55 at the margin. It is drawn from the 49 numbers not drawn as main, which is still marginally uniform.
H3 (independence). The main-number set S_t is independent of S_{t−1}, …, S_{t−10}, and the draw-sum series has no serial dependence up to lag 10.
H4 (stability). Draws are exchangeable in time: per-number inclusion probabilities are the same across calendar years and across the pre-registered rolling windows (W = 170, step 85; §6.2 C8).
H5 (draw-level aggregates). The sum, range, odd count, low count (low = 1–27) and consecutive-pair count follow their exact distributions under uniform 6-of-55 sampling without replacement.
H6 (model). Let Δⱼ(t) = LLⱼ(t) − LL₀(t) be the per-draw mean log loss of finalist *j* minus that of Baseline 0, over test draws 01191–01401 (§9.1). For each finalist *j* = 1..K (K ≤ 4, §9.3), the null is H6ⱼ: E[Δⱼ] ≥ 0, meaning the finalist is no better than Baseline 0. The alternative is one-sided: E[Δⱼ] < 0. The pre-registered decision rule, multiplicity control and stopping rule are in §9.3.

All of these are null hypotheses. Failing to reject them is a valid result and will be reported.

## 6. Statistical tests (v1.2; pre-registered before any M4 statistic is computed)

### 6.1 Common rules

- **Data (§8.2).** The primary run uses 00001–01190 (n = 1,190). The replication runs once, after the M6 lock, on 01191–01401 and on 00001–01401.
  It uses the same procedures as its own Holm family and is reported separately. It never changes M4 conclusions.
- **Null generators.** Seed 20260924, with `np.random.default_rng(np.random.SeedSequence([20260924, stream]))`. This is the same seed as the M3 spec; M3 uses stream 1.
  - **FRESH (stream 101):** R = 10,000 datasets of n fresh draws from the real mechanism: 6 of 55 without replacement, plus a special from the remaining 49.
    The generator is `simulate_draws` (`docs/design/M3-eda-spec.md` §3.2). It is a whole-draw simulation, never fixed-margin (`r2dtable`-style) tables.
  - **PERM (stream 102):** R = 10,000 uniform permutations of the observed draw order. Whole draws are moved, so the observed multiset of draws is kept.
  - One set of R replicates per generator serves every test that uses it.
- **Simulated p** = (1 + #{r : T_r ≥ T_obs}) / (R + 1). Every statistic T is a nonnegative discrepancy, so two-sided departures fall in the upper tail.
- **Multiplicity.** Holm at FWER α = 0.05 over the confirmatory family (§6.2). Holm-adjusted p for sorted p₍ᵢ₎ is max_{j≤i} min(1, (m−j+1)·p₍ⱼ₎).
  A family test is rejected iff its adjusted p ≤ 0.05.
- **MC escalation (pre-registered).** If any family member's Holm-adjusted p lies in [0.04, 0.06], the whole family is recomputed once with R = 100,000
  (streams 1101 FRESH and 1102 PERM). Those values are final, and both runs are reported.
- **Exact references.** The pmfs of sum, range, odd, low and consecutive pairs are the closed forms in `docs/design/M3-eda-spec.md` §3.1 ("Null references"),
  checked against brute-force enumeration. Overlap ~ Hypergeometric(55, 6, 6): mean 36/55, var 6·(6/55)·(49/55)·(49/54) = 0.529146.
  Low = 1–27 and high = 28–55. Odd numbers: 28 (1, 3, …, 55).

### 6.2 Confirmatory family (m = 13; Holm across all 13)

Notation: S_t is the main-number set of draw t; f_k is the main count of k; s_k is the special count, over n' draws with a special; y_t is the draw sum.

| id | H | statistic T (upper tail) | null | effect size reported |
|---|---|---|---|---|
| C1 | H1 | X²_main = Σ_k (f_k − 6n/55)² / (6n/55) | FRESH | dispersion ratio X²/49 (null ≈ 1); max_k \|z_k\|; Wilson 95% CI per number |
| C2 | H2 | X²_spec = Σ_k (s_k − n'/55)² / (n'/55); the reference is χ²(54) (E = 54). **No 54/49 scaling.** | FRESH | ratio X²/54 |
| C3 | H3 | overlap omnibus: Ō_j = mean over t = j+1..n of \|S_t ∩ S_{t−j}\|; Z_j = (Ō_j − 36/55) / √(0.529146/(n−j)); T = Σ_{j=1..10} Z_j² | FRESH | Ō_j − 36/55 (shared numbers per draw pair) ± 1.96·√(0.529146/(n−j)), per lag |
| C4 | H3 | overlap under permutation: the same Ō_j, standardised by the PERM mean and SD of Ō_j; T = Σ_{j=1..10} Z*_j². Valid whether or not H1 holds | PERM | Ō_j − PERM mean of Ō_j |
| C5 | H3 | Ljung–Box Q(10) = n(n+2) Σ_{h=1..10} r_h²/(n−h) on y_t (sample-mean-centred ACF). **Lag set fixed at h = 10** | FRESH | r_1..r_10 with ±1.96/√n; max_h \|r_h\| |
| C6 | H3 | runs: a_t = 1 if y_t > 168, 0 if y_t < 168. **Tie rule: draws with y_t = 168 are dropped** (order kept; 168 is the exact median of the symmetric null pmf, fixed, not the sample median). R_runs = number of runs; μ = 1 + 2n₊n₋/(n₊+n₋) of the same series; T = \|R_runs − μ\|. Replicates apply the same tie rule | FRESH | R_runs, μ, n₊, n₋, n_ties |
| C7 | H4 | year homogeneity: a G × 55 table of main counts by calendar year (primary run: G = 9, 2017–2025; partial years kept as is). X² = Σ (O_gk − E_gk)²/E_gk with E_gk = n_g·F_k/n. Null mean ≈ (G−1)·49 = 392, not 8·54 = 432 | PERM (year sizes fixed) | Cramér's V = √(X² / (N·(G−1))), **N = 6n = 7,140 number-slots** (not independent, hence the simulation), with PERM mean and 95% quantile of V |
| C8 | H4 | rolling global max: windows of **W = 170 draws, step 85**, from ordinal 1 (primary: 13 windows covering 1..1190 exactly). X²_w = Σ_k (O_wk − W·F_k/n)² / (W·F_k/n); **T = max_w X²_w** (simultaneous). Null mean of X²_w ≈ 49(1 − W/n) = 42 | PERM | V_roll = √(T/(6W)) with PERM mean; pointwise X²_w envelope is descriptive only |
| C9 | H5 | sum: D = max_{s=21..315} \|F̂(s) − F₀(s)\|, where F₀ is the CDF of the **exact DP pmf** (not KS asymptotics) | FRESH | ȳ − 168 ± 1.96·sd/√n; D |
| C10 | H5 | range: D as C9 over support 5..54, exact pmf | FRESH | mean − 40 ± CI; D |
| C11 | H5 | odd count: Pearson X² on cells 0..6 vs Hypergeometric(55, 28, 6) | FRESH | w = √(X²/n); mean − 168/55 |
| C12 | H5 | low count (1–27): as C11 vs Hypergeometric(55, 27, 6) | FRESH | w; mean − 162/55 |
| C13 | H5 | consecutive pairs: X² on **pooled cells {0, 1, 2, ≥3}** (exact P = 0.548150, 0.365434, 0.079442, 0.006974) | FRESH | w; mean − 6/11 |

Cell pooling (C11–C13) is decided from null probabilities and n only: tail cells merge inward until n·P ≥ 5. At n = 1,190, C11 and C12 need no pooling.
*Why W = 170 and step 85:* 7 × 170 = 1,190, so no draw is left uncovered. The expected count per number per window is 18.5, the windows half-overlap, and one window is about 1.1 years of draws.
In the replication, windows start at ordinal 1 and uncovered tail draws are reported. If fewer than 3 windows fit (01191–01401 fits 1), C8 is not applicable and m = 12.

### 6.3 Parent-gated follow-ups

Follow-ups are always computed, but they are **interpreted only if the parent's Holm-adjusted p ≤ 0.05**. Holm is applied within each follow-up set at FWER 0.05.
Otherwise the table is labelled "parent not rejected; not interpreted".

| parent | follow-up set |
|---|---|
| C1 | 55 exact two-sided binomial tests f_k vs Binomial(n, 6/55) (`scipy.stats.binomtest`) |
| C2 | 55 exact binomial tests s_k vs Binomial(n', 1/55) |
| C3 / C4 | 10 per-lag \|Z_j\| (C3: FRESH p) or \|Z*_j\| (C4: PERM p) |
| C5 | 10 per-lag \|r_h\|, FRESH p |
| C7 | G per-year contributions Σ_k (O_gk − E_gk)²/E_gk, PERM p |
| C8 | per-window X²_w, PERM p |
| C11–C13 | per-cell \|standardised residual\|, FRESH p, within the aggregate |

C6, C9 and C10 have no follow-up. The location of the maximum CDF gap is described without a test.

### 6.4 Exploratory (label "exploratory, unadjusted"; never a claim)

- χ² approximations: C1 scaled by 54/49 against χ²(54); C5 against χ²(10).
- Ljung–Box Q(5) and Q(20).
- The optional conditional H2 test: the rank of the special among the 49 numbers not drawn as main, X² over 49 cells (E = n'/49), FRESH p.
- Per-(year, number) cells and quarter tables.
- Pair co-occurrence.
- Sum χ² on the M3 bins.
- Min, max and gap metrics.
- Anything suggested by M3 EDA (`docs/design/M3-eda-spec.md` §0), and any other window, lag or statistic.

### 6.5 Reporting and acceptance

- **Per test:** T, n (and N = 6n where used), the replicate mean of T, raw simulated p, Holm-adjusted p, R, stream, and the effect size with CI where defined.
  Text follows OBSERVED / STATISTICAL EVIDENCE / INTERPRETATION / LIMITATION (AI-agent.md §13). A non-rejection is reported plainly.
  No result is presented as predictability or number selection.
- **Acceptance criteria for `src/statistics` (null-only tests):**
  - FRESH mean of X²_main is 49 ± 0.3, and of X²_spec is 54 ± 0.35 (R = 10,000, n = 1,190).
  - Overlap mean 36/55 and variance 0.529146, matching hypergeometric enumeration.
  - PERM mean of C7's X² within 2% of (G−1)·49, and mean X²_w within 2% of 49(1 − W/n), both on a FRESH null dataset.
  - Calibration (slow): on 400 FRESH null datasets with n = 300, inner R = 199 and proportional synthetic year labels, each C-test rejects at 0.05 at a rate in [0.0175, 0.090] (99.9% binomial bounds), and the Holm family FWER is ≤ 0.090. The seed is fixed in the test file; a failure triggers an investigation, never a seed change.
  - The p formula never returns 0; with T_obs above every replicate, p = 1/(R+1).
  - Holm on (0.01, 0.04, 0.03, 0.005) gives (0.03, 0.06, 0.06, 0.02).
  - Fixed streams give bit-identical results, invariant to chunk size.
  - Loaders truncate per §8.2.

## 7. Baseline definitions

Each target *t* and number *k* has a binary target `y[t,k] = 1` if *k* is among the main numbers of draw *t*.
Let n_t be the number of draws with draw_id < *t*, and c_k(t) the number of those draws that contain *k* as a main number.

- **Baseline 0 (theoretical):** p = 6/55 for every *k*. Every draw has exactly six 1s, so its per-draw log loss (0.344610) and Brier score (0.097190) are constants (§9.3).
- **Baseline 1 (historical frequency):** p_k(t) = 6·(c_k(t) + α) / (6·n_t + 55·α), with **α = 1 fixed** (not tuned). This gives Σₖ p = 6 exactly and 0 < p < 1, so no capping is needed. With n_t = 0 it equals Baseline 0.
  *Why α = 1:* a fixed α removes one tuned parameter, and at n_t ≥ 500 (every scored draw) its effect is negligible.
- **Baseline 2 (rolling window):** the Baseline 1 formula (α = 1) over the last m_t = min(W, n_t) draws before *t*. **If fewer than W draws exist, it uses all available draws.** It then equals Baseline 1 on that history, and Baseline 0 when n_t = 0.
  This short-history case never arises in scored draws (the earliest inner-validation draw is 00401). The rule exists so the behaviour is defined and testable.
  **W selection (frozen in v1.2; TASKBOARD "Data-exposure record" E2).**
  - The candidate set is exactly {50, 100, 200}. It can never change.
  - W is not inner-tuned. Each candidate is a Baseline 2 configuration.
  - W is chosen mechanically as the argmin of mean per-draw log loss over validation 00981–01190. That loss comes from the out-of-sample fold predictions used for §8.3 finalist selection.
  - If two candidates are within 1e-12 of each other, the larger W is chosen. W then stays frozen through M6 (§8.4).
- **Validation exposure (E2).** M3 EDA inspects 00981–01190, including rolling counts at W = 50/100/200.
  Every model or feature designed after M3 carries the flag `validation-exposed` in its EXP record, and its validation scores are reported as optimistic.
  Only the frozen test period can support an H6 claim.
- **Aggregate target:** the draw sum, where the baseline forecast is the theoretical mean 6·28 = 168.
- **Features vs fitted parameters:** history counts such as c_k(t), n_t and the window of the last m_t draws are *features*. They may use all draws before *t*, including earlier test draws during the M6 run.
  Weights, scalers, encoders, inner-tuned hyperparameters and every other *fitted* quantity use only the fold's fit window (§8.3). α (fixed at 1) and Baseline 2's W are not fitted quantities: W is a configuration choice made only by the §7 W-selection rule. No fitted quantity or configuration choice ever uses a draw after 01190.

## 8. Temporal split and data access

### 8.1 Frozen split

- Ordering is by draw_id. There is no shuffling.
- The split is frozen on `dataset_version = ds_cbdf3834368e` (1,401 draws). Train, validation and test are 980, 210 and 211 draws:
  - train: 00001–00980 (to 2024-01-06)
  - validation: 00981–01190 (to 2025-05-15)
  - test: 01191–01401 (2025-05-17 to 2026-09-22)
- Development means train ∪ validation = 00001–01190.

### 8.2 Data access per phase (binding; audit "Ruling")

| phase | draws that may be read | permitted use |
|---|---|---|
| M2 data quality | 00001–01401 | Structural and data-quality checks only. Number outcomes are not used. |
| M3 EDA | 00001–01190 | Outcome statistics. 2025 is labelled *partial* (it ends 2025-05-15). |
| M4 confirmatory H1–H5 | 00001–01190 | Primary confirmatory run, done now. |
| M4 replication | 01191–01401 and 00001–01401 | Runs once, only after the M6 result is locked. Reported as a replication. It never feeds back into models or into M4 conclusions. |
| M5 model development | 00001–01190 | Development folds (§8.3), hyperparameters and finalist selection. |
| M6 final test | features: all draws < *t*; fitted quantities: ≤ 01190; scored: 01191–01401 | Runs once, with frozen finalists only (§8.4, §9.3). H6 is decided here only. |
| Live holdout | ≥ 01402 | Frozen finalists only, under a separate dataset_version (§8.5). |

- Requirement for the implementation: the M3, M4-primary and M5 loaders truncate at 01190. They raise an error if any draw above 01190 reaches them. Tests must cover this.
- Anyone who sees test-period outcome statistics before the M6 lock records it under TASKBOARD "Decisions" as a limitation. No such exposure has occurred as of 2026-09-24.

### 8.3 Development folds (M5)

- The window expands from an initial 500 draws, with a 50-draw step and a 50-draw horizon. It is **restricted to 00001–01190**.
  - Fold *i* (i = 1..13) fits on 00001–(500+50(i−1)) and scores the next 50 draws, from 00501–00550 up to 01101–01150.
  - **Fold 14 is partial and is kept.** It fits on 00001–01150 and scores 01151–01190 (40 draws).
  - *Why keep fold 14:* dropping it would discard the 40 development draws closest to the test period, and it is needed to cover the whole validation block.
- Every fold is reported with its n. Pooled means are weighted by draws. Rolling evaluation over the test period happens only in the single M6 run.
- **Hyperparameters are nested per fold** (not fixed once on validation). A *hyperparameter* is a quantity declared as inner-tuned in the family's EXP grid. A *configuration* is a fully specified family member with no inner-tuned quantity (e.g. Baseline 2 with W ∈ {50, 100, 200}). Every configuration is scored in every fold; configurations are chosen only by the finalist-selection rule below, never nested.
  - The fold's fit window is 00001–(s−1). Inner-train is 00001–(s−101), and inner-validation is (s−100)–(s−1).
  - The grid point with the lowest inner mean per-draw log loss wins. Ties go to the simpler or more regularised point, as declared in the EXP spec.
  - The winner is then refit on the full fit window.
  - *Why nested:* no fold's hyperparameters see later draws, and M6 applies the identical rule, so development and test scores are comparable.
- Scalers and encoders are fit on the fit window only (inner-train during inner validation).
- **Finalist selection:** within each family, the chosen configuration is the one with the lowest mean per-draw log loss over the validation block 00981–01190. This uses the out-of-sample fold predictions from folds 10–14; fold 10 contributes only 00981–01000.
  - Folds 1–9 are used for development and reported, but they are not used for selection.
  - Each family sends **exactly one finalist** to M6, whether or not it beats Baseline 0 on validation. K is therefore fixed by the family list, not by results.
  - Finalists' validation scores are labelled selection-biased.
- **Development stopping:** each family's candidate grid is written in its EXP spec before any fit. M5 ends when the finalist list and each finalist's frozen configuration are recorded under TASKBOARD "Decisions", together with the spec SHA-256.

### 8.4 Final test run (M6)

- **Refit before test: yes, once.** Each finalist is refit on 00001–01190 under the nested rule, with inner-validation 01091–01190. For finalists without fitted quantities (Baselines 1 and 2) the refit is a no-op; W stays at its §7 frozen value.
  *Why:* this uses all development data, and no fitted quantity sees a test draw.
- There is no refit during the test period. Features for test draw *t* use all draws < *t*, as in real-time forecasting. For example, Baseline 1 and 2 counts update, while W stays frozen.
- The scored draws are 01191–01401 (211 draws). Five consecutive blocks are also reported, as descriptive results only: 01191–01240, 01241–01290, 01291–01340, 01341–01390 and 01391–01401 (11 draws). The H6 decision uses only the pooled 211 draws.

### 8.5 Live holdout

- Draws ≥ 01402 are never merged into the frozen test set. They form the live holdout, which has its own dataset_version, not `ds_cbdf3834368e`.
- It is scored only with the frozen M6 finalists. There is no refit, no re-selection, and the same feature rule applies.
- It uses the metrics in §9.1–9.2 and is reported separately from M6. It has no decision rule unless a new EXP spec pre-registers one before its first draw is scored.

## 9. Evaluation metrics

### 9.1 Probabilistic targets (55 marginals)

- **Primary: per-draw mean log loss**, LL(t) = −(1/55) Σₖ [y log p + (1−y) log(1−p)]. The score for a period is the mean of LL(t) over its scored draws.
  p is clipped to [1e−6, 1−1e−6], and the number of clipped cells is reported.
- Secondary: per-draw mean Brier score, defined the same way.
- Both are proper scores for the **marginals only**. They do not assess dependence within a draw. H6 concerns marginals.
- **Σp:** the evaluator never renormalises. A model may renormalise to Σₖ p = 6 as part of its own definition, if its EXP spec declares it. The per-draw Σₖ p (mean, min, max) is reported for every model.
- Calibration uses a reliability diagram and ECE. Both use 10 equal-frequency bins of p, pooled over (t, k) in the period, with ECE = Σ_b (n_b/N)·|ȳ_b − p̄_b|.
  Baseline 0 has constant p: that gives one bin and ECE = 0 by construction. This is not evidence of calibration.
- Set-level log score, for joint models only (models that output a probability for each 6-set): −ln P(S_t). For Baseline 0 it is ln C(55,6) = 17.182. It is secondary and not part of H6.

### 9.2 Aggregate target (draw sum)

- MAE and RMSE are reported against the baseline forecast 168. The paired difference (model − baseline) comes with a bootstrap CI using the §9.3 scheme. This is secondary and not part of H6.

### 9.3 Uncertainty, H6 decision rule, stopping

- **Bootstrap:** a circular block bootstrap that resamples whole draws, so all 55 cells of a draw stay together. Every model uses the same resampled indices, which makes the comparisons paired.
  - **Block length L = 10 draws.** *Why:* it is above n^(1/3) ≈ 6 for n = 211, and it covers about 3 weeks of draws. That allows for serial correlation in the predictions of history-based models, erring on the wide side.
  - **B = 10,000.**
  - **Seed = 20260924** (`numpy.random.default_rng`) for every bootstrap. Model-training seeds default to the same value and are recorded.
- CIs are two-sided 95% percentile intervals, for every metric and for every paired difference against Baseline 0. They are given per fold, per M6 block and pooled. Development-fold CIs are descriptive only: no hypothesis is decided on development data.
- Baseline 0's per-draw LL (0.344610) and Brier (0.097190) are constant, so its own CI has zero width. Δⱼ(t) is then the model's series shifted by a constant. This is expected, not an error.
- **H6 decision (M6 only).**
  - For finalist *j*, Δ̄ⱼ is the mean of Δⱼ(t) = LLⱼ(t) − LL₀(t) over the 211 test draws.
  - The bootstrap p-value is pⱼ = (1 + #{b : Δ̄*ⱼ,b ≥ 0}) / (B + 1).
  - Holm is applied across the K finalists at FWER 0.05. **H6ⱼ is rejected only if its Holm-adjusted pⱼ ≤ 0.05.** For K = 1 this is the rule "the one-sided upper 95% bound of Δ̄ⱼ is below 0".
- **K ≤ 4, with one finalist per pre-registered family:**
  - (1) Baseline 1
  - (2) Baseline 2
  - (3) one penalised-linear family
  - (4) one tree-ensemble family

  No family can be added or substituted. A family not implemented by the M5 finalist freeze is dropped, which lowers K.
- **Stopping rule:** M6 runs **exactly once**, against the frozen spec hash and the frozen finalist list.
  - If the run crashes before any metric is written, it may be restarted after a logged fix that does not change the configuration.
  - Once any metric exists, there is no rerun. A later correction gets a new EXPERIMENT_ID and is reported next to the original result, never in place of it.
  - A result with no rejection is reported plainly as a negative result.
- **Positive result:** any rejection triggers a mandatory leakage audit by methodology-auditor. It covers feature timestamps, fit windows, loader truncation and the split and dataset hashes.
  Until that audit passes, the result is reported as "provisional, under leakage audit". Even after it passes, the result is reported as an effect size in LL units with its CI. It is not a claim of predictability, and it is never presented as number selection.

### 9.4 Experiment record

Each `docs/experiments/EXP-###.md` is written before any code for it and records:

- experiment_id
- spec version and SHA-256
- dataset_version
- code_version: the git commit SHA of HEAD (the repository is under git and pushed to GitHub). **M6 requires a clean working tree** (`git status --porcelain` empty) and aborts otherwise. Development runs on a dirty tree record `<SHA>-dirty`.
- feature_version, model_version and model family
- parameters and grid
- seed
- train, validation and test periods, and the fold list
- metrics for every fold, block and pooled, with CIs
- status (AI-agent.md §20 vocabulary)
- notes
- limitations

## 10. Repository structure — DONE

This follows `PROJECT_STEPS.md` §14. `src/` contains `api`, `ingestion`, `validation`, `transformation`, `features`, `statistics`, `models`, `evaluation` and `reporting`, and `tests/` mirrors it.

## 11. Definition of Done (per milestone)

- The code is covered by the targeted tests, and the full `pytest` suite passes.
- Data outputs are reproducible from raw data plus code, and `dataset_version` is recorded.
- Documentation is updated (this file and the README).
- The completion report states the files changed, a summary, the tests run, the results, the limitations and the next task.
