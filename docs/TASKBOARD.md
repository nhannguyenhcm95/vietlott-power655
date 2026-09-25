# Task board

Status vocabulary: AI-agent.md §20. The Project Lead (main session) keeps this file current.

## Done

| ID | Title | Type / Risk | Status | Notes |
|---|---|---|---|---|
| M0 | Specification (pre-code checklist) | DOC / HIGH | DONE | `docs/SPECIFICATION.md` v1.2.1, audited (M0-R) and approved by the human on 2026-09-24. |
| M1 | API / data ingestion | API / MEDIUM | DONE | data-qa PASSED, then qa-runner regression PASSED (2026-09-24). |
| M2 | Data quality (T1–T4) | DATA / MEDIUM | DONE | data-qa PASSED on every task, then qa-runner regression PASSED on 2026-09-24 (219 tests, deterministic outputs, DoD met). |

## Next

| ID | Title | Type / Risk | Status | Notes |
|---|---|---|---|---|
| HUMAN-1 | Register the scheduled refresh task | OPS | READY | The human runs `scripts/register_refresh_task.ps1` (see README). Agents never run it. |
| M0-R | methodology-auditor pass on `docs/SPECIFICATION.md` | DOC / HIGH | DONE | SPECIFICATION v1.2.1 approved by the human (sha256 e41f63ef…09474). |
| M5 | Baselines 0–2 on development folds (EXP-001) | ML / HIGH | IN_PROGRESS | ml-researcher writes `docs/experiments/EXP-001.md` before any fit, ml-engineer implements it, and methodology-auditor reviews. Rules: loader truncated at 01190 with a test, the validation-exposed flag (E2), commit before every recorded run (A-F2), and K ≤ 4 families (§9.3). |
| M4 | Confirmatory tests H1–H5 (§6, 13 tests with Holm, range 00001–01190) | STAT / HIGH | DONE | 0 of 13 rejected at FWER 0.05, so there is no confirmatory evidence against H1–H5 on the development draws. Official run: code 2fb9ee8, outputs in `outputs/m4/through_01190/`. Statistician re-review PASSED, methodology-auditor final audit PASSED, human approval 2026-09-25. |
| M4-F | M4 follow-ups | STAT / LOW | BACKLOG | F1: add a slow calibration run for C8 alone at n = 510; it is required before the replication. F2: merge the two pooling implementations when M3-R1 is fixed. Nits: fix the C9/C10 CI label (either give the CI of the difference, −0.08 to 4.19, or relabel it), show N only for C7, test the "parent rejected" label, and add the independence caveat to the ≈0.23 line. |
| M3-R1 | EDA follow-ups | STAT / LOW | BACKLOG | R1: collapse the pooling leftover when n ≤ 106, and extend T13 to n = 10/60/100. A1: add tests pinning `exact_pmf_approx_band` and the `within_draw_` labels. A2: the `draw_gaps.png` caption should read "exact expected counts; approximate band". stat-analyst implements, qa-runner reviews. Real outputs are unaffected. |
| M3 | EDA | STAT / MEDIUM | DONE | Statistician review PASSED, Rev 3.2 audit PASSED, and the qa-runner points are resolved (2026-09-25). Outputs are in `outputs/eda/through_01190/`. |

## M2 — Data quality

### M2-T1 — Independent review of M1
- TYPE: QA · RISK: MEDIUM · PRIMARY: data-qa · REVIEWER: qa-runner
- OBJECTIVE: verify that the M1 data and the ingestion guarantees are correct.
- INPUT:
  - `data/raw`, `data/staging`, `data/curated`, `data/logs`
  - `src/api`, `src/ingestion`, `src/validation`
  - `tests/`
- OUTPUT: `reports/data_quality_2026-09-24_M1-review.md` with a verdict of PASSED or REWORK.
- ACCEPTANCE_CRITERIA:
  - At least 5 random curated draws are checked against the archived raw HTML, parsed independently of `src/`.
  - The draw 00944 mirror defect is assessed.
  - Each API rule in agent.md is mapped to the code that implements it and the test that covers it. Rules without a test are flagged.
  - `pytest` passes.
- CONSTRAINTS:
  - No edits to `src/` or `tests/`.
  - No `--full` ingest. At most one incremental ingest of `vietlott_official`.
- STATUS: DONE (data-qa, 2026-09-24). Finding #3 moved to M2-T4.

### M2-T2 — Data quality report
- TYPE: DATA · RISK: MEDIUM · DESIGN: data-architect · IMPLEMENTATION: data-engineer · REVIEWER: data-qa, then qa-runner
- OBJECTIVE: generate the report deterministically from curated data, staging data and logs.
  - `reports/data_quality_<date>.md` for people to read.
  - A JSON version for the dashboard (PROJECT_STEPS §13, page 2).
- MUST COVER:
  - coverage, missing values, duplicates, invalid ranges, schema errors
  - ingestion run history and failures
  - source reconciliation and raw checksum status
  - open quality_log items
  - a known-issues mechanism (for example the mirror draw 00944) that never hides issues silently
  - PASS/WARN/FAIL rules
- STATUS: DONE (data-qa re-check 2026-09-24; reports/review_2026-09-24_M2-T2.md). qa-runner regression PASSED.

### M2-T3 — Scheduled refresh
- TYPE: DATA · RISK: MEDIUM · DESIGN: data-architect · IMPLEMENTATION: data-engineer · REVIEWER: data-qa, then qa-runner
- OBJECTIVE: add a `python -m src.cli refresh` command that runs, in order:
  1. incremental ingest from the official source and the mirror
  2. reconcile
  3. curate
  4. quality report
- MUST DEFINE:
  - failure semantics: the mirror is down, the sources disagree, the draw is not yet published, runs overlap (use a lock file)
  - exit codes
- DELIVERABLES: Windows Task Scheduler register and unregister scripts in `scripts/`. The schedule runs after the Tue/Thu/Sat 18:00 draw (Asia/Ho_Chi_Minh), with a next-day retry.
- CONSTRAINT: agents never run the registration script. The human registers the task.
- STATUS: DONE (data-qa 2026-09-24; reports/review_2026-09-24_M2-T3.md). qa-runner regression PASSED.

### M2-T4 — Structured-logging test (fast-follow from M2-T1 finding #3)
- TYPE: QA · RISK: LOW · IMPLEMENTATION: data-engineer · REVIEWER: qa-runner
- OBJECTIVE: add a test for `src/logging_utils.py`. It must check that JSON lines contain `ts`, `level`, `event` and the extra fields, and that the file handler writes to the given path.
- NOTE: the empty `app.log` is explained. Every earlier run used `--log-level WARNING` and no warning occurred, so nothing was written. This is not a bug.
- STATUS: DONE (data-qa 2026-09-24: 7 tests meet all criteria)

### Decisions (human Project Lead, 2026-09-24)
- The M2 design is APPROVED, including the §0 changes. It goes to a methodology-auditor audit before implementation.
- KI-001 (mirror draw 00944) is APPROVED as a known issue. data-engineer creates it in `configs/known_issues.json` with `"approved_by": "project-lead (human)"`, `"approved_on": "2026-09-24"` and `"approval_ref": "TASKBOARD Decisions 2026-09-24"`. It covers only the rules `chronological_order` and `reconcile.only_left`.

### Decisions after the methodology audit (human Project Lead, 2026-09-24)
The audit record is `docs/design/M2-audit-2026-09-24.md`, with verdict REWORK.
- D1 (finding 5): refresh exit codes are PASS 0, WARN 10, FAIL 30, LOCKED 40, INTERNAL 50. Code 1 is never a data status.
- D2 (finding 7): curate is blocked only when a mismatched draw_id is in the set about to be published (official staging minus the manifest). Otherwise curate proceeds, and the report FAILs on `reconcile.sources`.
- D3 (finding 4): an empty fetch from the official source is FAIL (exit 30). An empty fetch from the mirror stays WARN.
- D4 (finding 2): known issues are tightened.
  - They are validated against an allowlist.
  - Integrity rules can never be accepted.
  - A date range may cover at most 60 days, matched per missed date.
  - An entry stops accepting once it is past `review_by`.
  - A FAIL-level acceptance must pin the observed values.
- D5 (finding 8): add the `frozen_prefix` rule. It is an error that can never be accepted as a known issue: draws up to and including 01401 must always produce `ds_cbdf3834368e`. `raw_lineage` re-parses the raw data and compares content.
- D6 (findings 14 and 18): add the column `refresh_log.report_sha256`. The directory is `configs/`, not `config/`. The field name is `approved_on`.
- The remaining findings (1, 3, 6, 9–17 and 19) are accepted as recommended by the auditor.
- D7 (re-audit N1): `mirror_shrink` is WARN (exit 10), consistent with D3. Confirmed by the human.
- Design Revision 3: methodology-auditor PASSED (line-diff check). The design is final for implementation.

### Decisions — SPECIFICATION approval (human Project Lead, 2026-09-24)
SPECIFICATION v1.2.1 APPROVED sha256=e41f63ef47ea066f14e5effb41bf9f4b7ebd8d79641604b69a10323837e09474
- Approved after M0-R: the audit plus 3 re-audits, all PASSED (`docs/design/M0-audit-2026-09-24.md`). This version is binding for M3–M6. Any change needs a change request, a new version and a new approval.
- M3 EDA spec Rev 3.1 is PASSED and may be implemented. A real-data run is allowed now that this approval line exists.

### Decisions — M3 (Project Lead, 2026-09-25)
- M3 EDA spec Rev 3.2 PASSED the methodology-auditor line-diff audit (sha256 cb9561896363b626f64e1e217956a3d5a0c47c74c87ca1c8c57c98a60832a794). Rev 3.2 supersedes Rev 3.1 for M3.
- The M3 implementation passed statistician review and re-review (`reports/review_2026-09-25_M3.md`). qa-runner raised three points, all now resolved:
  - Rev 3.2 has been audited.
  - README references now point to Rev 3.2.
  - The freshness WARN is cleared: refresh ingested draw 01402, and curated data is now `ds_aa8808303afa`.
- The deliverable is `outputs/eda/through_01190/` (analysis_version `ds_16b6be697acb`, built from `ds_cbdf3834368e`). The analysis range does not depend on draws after 01190, so it stays valid.
- Draw 01402 and every later draw belong to the live holdout (SPECIFICATION §8.5). No analysis may use them now.

### Spec defects recorded for a future change request (Project Lead, 2026-09-25)
These come from the statistician's M4 re-review. The frozen spec v1.2.1 is NOT edited. Each item goes into the next change request.
- **SD-1.** In the §6.5 calibration test, the FWER check is structurally vacuous at inner R = 199: with m = 12, the minimum Holm-adjusted p is 0.06. An informative check needs inner R ≥ 999. The reported FWER of 0.0000 must never be cited as evidence. FWER control holds in substance: each p-value is exactly valid by exchangeability, and Holm controls FWER under any dependence.
- **SD-2.** C8 cannot be calibrated at n = 300, because 3 windows need at least 340 draws.
- **SD-3.** Exploratory streams 103 (conditional H2) and 104 (sum χ² on M3 bins) are not registered in v1.2.1. Neither collides with any other stream.

### Decisions — M4 (human Project Lead, 2026-09-25)
- M4 APPROVED as DONE. Result: 0 of 13 rejected on 00001–01190. Non-rejection does not prove the null hypotheses, and power against small departures is not quantified.

### M4 audit records (Project Lead, 2026-09-25; methodology-auditor final audit PASSED)
- **A-F1. Calibration.** The §6.5 FWER clause is vacuous at inner R = 199, so the value 0.0000 must never be cited (see SD-1). FWER control rests on two facts: the Monte Carlo and permutation p-values are exactly valid, and Holm controls FWER under any dependence. The marginal calibration passed, and "rejects at 0.05" is read on raw p. C8 is not calibrated (SD-2). A slow C8-only calibration at n = 510 is required before the post-M6 replication.
- **A-F2. Provisional run.** The provisional M4 code was never committed (cd4e668-dirty), and its outputs were overwritten. Only the recorded values could be checked, and they match. New rule from M5 onward: commit before any run whose result is recorded, and keep provisional outputs in a separate directory.
- **E3. Auditor data access.** During the M4 audit, the auditor printed only metadata above 01190: the draw_id of row 01191, and the draw_id and dataset_version of row 01402. No outcomes were printed. Risk: low.

### Data-exposure record (Project Lead, 2026-09-24)
- **E1. M0-R auditor access.** The auditor read metadata only over 00001–01401: dataset versions, draw ids, dates and per-year draw counts. It also read two validation-rule counts: special number missing = 0, and special number equal to a main number = 0. No outcome statistic that identifies numbers or sums was computed on draws ≥ 01191. The "≈15 draws with sum 168" figure is a null expectation (1401 × P = 14.70), not an observed count. Risk: low.
- **E2. Planned M3 exposure (O2 ruling).** M3 EDA will inspect draws 00981–01190, including rolling counts at W = 50/100/200. That is Baseline 2's candidate set and selection block. Therefore:
  - The W selection rule must be frozen in SPECIFICATION §7 before any M3 output is opened. The rule is argmin of mean validation log loss over {50, 100, 200}; on a tie within 1e-12, choose the larger W.
  - Every model or feature designed after M3 carries a "validation-exposed" flag. Its validation scores count as optimistic.
  - Only the frozen test period can support an H6 claim.

### Flow
1. **M2-T1** (data-qa) and the **M2-T2 + M2-T3 design** (data-architect, one note at `docs/design/M2-data-quality-and-refresh.md`) run in parallel.
2. The human approves the design.
3. data-engineer implements M2-T2, then M2-T3.
4. data-qa reviews the result, then qa-runner runs the full regression.
5. Update this board and the README.
