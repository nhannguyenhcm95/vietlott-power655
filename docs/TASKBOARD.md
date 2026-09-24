# Task board

Status vocabulary: AI-agent.md §20. The Project Lead (main session) keeps this file current.

## Done

| ID | Title | Type / Risk | Status | Notes |
|---|---|---|---|---|
| M0 | Specification (pre-code checklist) | DOC / HIGH | NEEDS_REVIEW | `docs/SPECIFICATION.md`, written by the main session. Needs a methodology-auditor pass before M4/M5 start. |
| M1 | API / data ingestion | API / MEDIUM | DONE | data-qa PASSED, then qa-runner regression PASSED (2026-09-24). |
| M2 | Data quality (T1–T4) | DATA / MEDIUM | DONE | data-qa PASSED on every task, then qa-runner regression PASSED on 2026-09-24 (219 tests, deterministic outputs, DoD met). |

## Next

| ID | Title | Type / Risk | Status | Notes |
|---|---|---|---|---|
| HUMAN-1 | Register the scheduled refresh task | OPS | READY | The human runs `scripts/register_refresh_task.ps1` (see README). Agents never run it. |
| M0-R | methodology-auditor pass on `docs/SPECIFICATION.md` | DOC / HIGH | READY | Required before M4 and M5 start. |
| M3 | EDA | STAT / MEDIUM | BACKLOG | stat-analyst implements, statistician reviews. |

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

### Flow
1. **M2-T1** (data-qa) and the **M2-T2 + M2-T3 design** (data-architect, one note at `docs/design/M2-data-quality-and-refresh.md`) run in parallel.
2. The human approves the design.
3. data-engineer implements M2-T2, then M2-T3.
4. data-qa reviews the result, then qa-runner runs the full regression.
5. Update this board and the README.
