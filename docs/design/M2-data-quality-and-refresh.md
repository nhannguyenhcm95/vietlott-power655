# M2 design — data quality report (M2-T2) and scheduled refresh (M2-T3)

Author: data-architect · Revision 3 · 2026-09-24 · STATUS: NEEDS_REVIEW (goes back to methodology-auditor, then data-qa).
Implementer: data-engineer. Report statuses PASS/WARN/FAIL are *data* statuses; they are not task statuses (AI-agent.md §20).
Binding inputs: `docs/design/M2-audit-2026-09-24.md` (findings 1–19) and TASKBOARD Decisions (KI-001, D1–D6).

## Revision 2 and 3 changelog

| finding | decision | change | section |
|---|---|---|---|
| 1 BLOCKER | KI-001 | KI-001 seeded as approved; transcription rule with `approval_ref`; real-data ACs expect PASS / exit 0 | §1.5, §1.8-4, §2.9-6 |
| 2 MAJOR | D4 | allowlist; never-acceptable rules; date ranges ≤ 60 d matched per missed date; pins for FAIL-level; expiry; future `approved_on`; absent vs malformed file | §1.4, §1.5 |
| 3 MAJOR | – | rule/source vocabulary table, in `known_issues.py` | §1.4 |
| 4 MAJOR | D3 | official empty fetch = FAIL (30), mirror = WARN; "has stored rows" defined; `--start/--end` rejected in incremental mode | §1.3, §2.2, §0 |
| 5 MAJOR | D1 | exit codes 0/10/30/40/50; scheduler action, working directory, PS 5.1 stderr handling, battery settings, wrapper maps unknown codes to 50 | §2.3, §2.7 |
| 6 MAJOR | – | `main(argv, paths=None)`; CLI tests use the `paths` fixture; guard that real `data/` is untouched | §2.5, §1.9, §2.10 |
| 7 MAJOR | D2 | curate is blocked only when a mismatched id is in the set about to be published; tests use the realistic 20:00 → 08:30 sequence | §2.1, §2.2, §2.10 |
| 8 MAJOR | D5 | `raw_lineage` re-parses raw and compares content; `frozen_prefix`; wrong first draw = FAIL | §1.3, §1.6 |
| 9 MAJOR | – | fixtures built through `run_ingestion` + FakeSession for both sources; absent-input table | §1.2, §1.9 |
| 10 MINOR | – | O4 closed; AC9 replaced (no `--log-level` in wrapper; `refresh_start`/`refresh_finished` events; handlers restored) | §0, §2.5, §2.9-9 |
| 11 MINOR | – | O3 wording corrected | §0 |
| 12 MINOR | – | `duplicate_content` keyed on (sorted main, special); flags the later id; 00647/00993 does not fire | §1.6 |
| 13 MINOR | – | `retrieved_after_draw` compares with draw date 18:00 ICT | §1.6 |
| 14 MINOR | D6 | `as_of` normalised to ICT seconds; full sort key; shared Int64 reader; temp + `os.replace` for every output, manifest last; PermissionError retry; `report_sha256`; summary counts defined | §1.2, §1.7, §2.1, §2.6 |
| 15 MINOR | – | stale lock broken by `os.replace`; lock taken only at CLI/refresh level; exit 40 leaves ALERT alone; "started, not finished" alert; `lock_held` in report | §2.4 |
| 16 MINOR | – | mirror down = WARN from `ingestion.runs` only; catch `Exception` in every step; `mirror_shrink` = FAIL (superseded by R3 N1) | §1.3, §2.1, §2.2 |
| 17 MINOR | – | KI-001 covers only `chronological_order` and `reconcile.only_left`; `matched` reported per rule | §1.5, §1.7 |
| 18 MINOR | D6 | `configs/` directory; field `approved_on` | throughout |
| 19 MINOR | – | all 16 named tests added | §1.9, §2.10 |
| R3 N1–N9 (re-audit) | D3 (N1) | N1 `mirror_shrink` = WARN (exit 10), evaluated only when `received` is non-empty; N2 official `stored_row_conflict` never acceptable, mirror without pin, RESOLVED rule; N3 recursive file snapshot guard; N4 `frozen_prefix` gates the `curate` CLI; N5 `refresh --as-of` restricted; N6 missing quality_log vs partial runs; N7 published ids = `read_fact_draw(curated)` ids; N8 pins match exact JSON with string values; N9 elapsed date-range KI = INFO, register script rejects `\WindowsApps\` python and checks imports | N1 §1.3, §1.4, §1.6, §1.9, §2.2, §2.10; N2 §1.3, §1.4, §1.9; N3 §1.9; N4 §1.6, §2.5, §2.10; N5 §2.5, §2.10; N6 §1.2, §1.4, §1.6, §1.9; N7 §2.1; N8 §1.4, §1.5, §1.9; N9 §1.4, §1.5, §1.9, §2.7, §2.9, §2.10 |

## 0. Impact analysis (approved by the human 2026-09-24; revision 2 additions marked R2)

| change | kind | impact |
|---|---|---|
| new `data/logs/refresh_log.csv` (§2.6), including `report_sha256` (R2) | schema, additive | new file only |
| new `configs/known_issues.json` (§1.5) | contract, additive | the report and the refresh curate gate read it; ingestion ignores it |
| `validate_dataset` gains warning `duplicate_content` | rule | adds quality_log warning rows only; nothing new is rejected |
| `frozen_prefix` constant: draws ≤ 01401 ⇒ `ds_cbdf3834368e` (R2, D5) | integrity contract | FAIL if history before the freeze ever changes |
| `Paths` gains `config` (= root/configs) and `reports` (= root/reports) | config | additive |
| curated files written temp + `os.replace`, manifest last (R2) | behaviour-preserving | same bytes; the manifest is the commit marker |
| `ingest`, `curate`, `refresh` take the run lock | CLI behaviour | a manual command exits 40 while a refresh runs |
| `cli.main(argv, paths: Paths \| None = None)` (R2) | API of the CLI entry | default behaviour unchanged |
| `ingest` rejects `--start/--end` without `--full` (R2, finding 4) | CLI behaviour | incremental runs are always unfiltered, so an empty fetch is meaningful |

Unchanged: the `DrawSource` contract; staging/curated columns; the `dataset_version` algorithm; the `ingestion_log`/`quality_log` columns; the exit codes of the existing `ingest`, `reconcile` and `verify-raw` commands.
If implementation needs any of these to change, stop and escalate. Update SPECIFICATION §4 with the rules in §1.6.

Observations in current data:
- **O1.** The mirror is one file, so `stop_at_draw_id` does not apply. Every mirror run re-reads bad row 00944. The run is logged `partial` and adds 3 quality_log rows, every time.
- **O2.** If official page 0 is empty, the run is logged `success` with `rows_received=0` (a silent failure).
- **O3 (reworded).** Official draws are 2–3 days apart. Twelve gaps skip at least one scheduled Tue/Thu/Sat:
  - ten skip exactly one draw: nine at Tết and one in Aug 2020 (00468 → 00469)
  - two are suspensions, skipping 10 draws (00415 → 00416, 2020) and 11 draws (00608 → 00609, 2021)
- **O4 (closed).** `app.log` was empty because the earlier runs used `--log-level WARNING`. The `configure_logging` unit test is task M2-T4.
- **O5.** The mirror's `process_time` is about 00:01 on the day after the draw. So mirror lag is 1 draw at the 20:00 run and 0 at the 08:30 retry.

---

## 1. Task Card M2-T2

```text
TASK_ID: M2-T2
TITLE: Deterministic data quality report (md + JSON)
TYPE: DATA   RISK: MEDIUM (+ additive schema items in §0)
PRIMARY_MODEL: data-architect (Opus)   IMPLEMENTATION_MODEL: data-engineer (Sonnet, medium)
REVIEWER: data-qa, then qa-runner; methodology-auditor for §1.4–1.6
OBJECTIVE: One pure, offline generator turns curated + staging + raw + logs + known issues into
  reports/data_quality_<YYYY-MM-DD>.md and .json, with an overall PASS/WARN/FAIL (PROJECT_STEPS §6, §13 p2).
INPUT: §1.2.   OUTPUT: §1.1, §1.7.   DEPENDENCIES: M1 code; M2-T1 PASSED; KI-001 decision (TASKBOARD).
ACCEPTANCE_CRITERIA / TEST_PLAN: §1.8 / §1.9.   RISKS / ESCALATION_CONDITION: §3.
STATUS: NEEDS_REVIEW (design, revision 3)
```

### 1.1 Modules and CLI
- **`src/validation/known_issues.py`**:
  - `KnownIssue` (frozen dataclass)
  - `KnownIssuesError`
  - `RULES: dict[str, RuleSpec]`, the vocabulary in §1.4. `RuleSpec` has `check`, `acceptable_sources` and `needs_pin`.
  - `load_known_issues(path) -> list[KnownIssue]`. It returns `[]` if the file is absent and raises on a malformed file.
  - `issue_state(ki, as_of) -> "active" | "proposed" | "expired"`
  - `match_known_issue(finding, issues, as_of) -> KnownIssue | None`
- **`src/validation/schedule.py`**:
  - constants `DRAW_TIME_LOCAL = time(18, 0)` and `PUBLICATION_DEADLINE_LOCAL = time(21, 0)`
  - `scheduled_draw_dates(start, end) -> list[date]`
  - `expected_latest_draw_date(as_of) -> date`: the latest Tue/Thu/Sat d where d at 21:00 ICT ≤ as_of
  - `missed_scheduled_draws(last_draw_date, as_of) -> list[date]`
- **`src/validation/lineage.py`**:
  - constants `FROZEN_LAST_DRAW = "01401"` and `FROZEN_VERSION = "ds_cbdf3834368e"`
  - `check_frozen_prefix(df) -> list[Finding]`
  - `check_raw_lineage(staging, paths, source) -> list[Finding]`
  - `received_ids(paths, source, run_id) -> set[str]`
  - Re-parsing uses `RawArchive.read_pages(source, run_id) -> list[RawPage]`, a new method in `raw_archive.py` that rebuilds each page from `manifest.jsonl` plus its file, and `get_source(name).parse`. Constructing a source does no I/O. This is fully offline.
- **`src/validation/reconcile.py`** (add) `assess_reconcile(rep, issues, as_of, published_ids) -> ReconcileAssessment`. Fields:
  - `status`, `findings`
  - `unaccepted_mismatch_ids`
  - `mirror_lag_draws`
  - `blocking_ids`: `unaccepted_mismatch_ids` ∩ the set about to be published

  The report and refresh both use it, so they cannot disagree.
- **`src/transformation/tables.py`** (add) `read_fact_draw(path) -> DataFrame`. It reads with dtypes `{draw_id: str, draw_date: str, special_number: "Int64"}`. It is the only reader of curated fact_draw; the report and `frozen_prefix` use it.
- **`src/reporting/data_quality.py`**:
  - `Finding` and `CheckResult` dataclasses
  - one `check_<id>(ctx) -> CheckResult` per row of §1.3
  - `build_quality_report(paths, as_of, known_issues_path=None, run_context="standalone") -> dict`
  - `render_markdown(report) -> str`
  - `write_quality_report(report, out_dir) -> tuple[Path, Path, str]`, which returns the md path, the JSON path and the JSON sha256
- **CLI** `python -m src.cli quality-report [--as-of ISO8601] [--out-dir reports] [--known-issues configs/known_issues.json]`:
  - `--as-of` must include a timezone offset; a value without one is rejected.
  - The command prints `{overall_status, json, md}` and exits 0 PASS / 10 WARN / 30 FAIL / 50 internal error.
- **Output files**:
  - `reports/data_quality_<report_date>.md` and `.json`
  - `reports/data_quality_latest.json`, a byte copy
  - A rerun on the same day overwrites these files. They are derived, and `inputs` fingerprints them.

### 1.2 Inputs, determinism, absent inputs
Determinism:
- `as_of` is converted to Asia/Ho_Chi_Minh with microseconds dropped. `report_date = as_of.date()` in ICT. There is no other clock and no `generated_at`.
- `json.dumps(sort_keys=True, indent=2, ensure_ascii=False)` with `\n` line endings.
- Checks follow the §1.3 order.
- Findings are sorted by `(source, draw_id or "", rule, draw_date or "", detail)`.
- Paths are relative POSIX paths.
- Every file is written as a temp file followed by `os.replace`.

Absent inputs:

| input absent | check / rule | status |
|---|---|---|
| `data/curated/*` (any file or the manifest) | curated.schema / `input_missing` | FAIL |
| `data/staging/vietlott_official/draws.csv` | staging.schema / `input_missing` | FAIL |
| `data/staging/github_mirror/draws.csv` | staging.schema / `input_missing` and reconcile.sources / `reconcile.not_run` | WARN |
| `data/logs/ingestion_log.csv` | ingestion.runs / `input_missing` | FAIL |
| `data/logs/quality_log.csv` (R2 addition; R3 N6) | quality_log.open / `input_missing` | INFO only if no ingestion run is `partial`. Otherwise `log_integrity`: WARN if the partial run is from the mirror, FAIL if it is from the official source |
| `data/logs/refresh_log.csv` | refresh.history / `input_missing` | INFO |
| `configs/known_issues.json` | known_issues.file / `known_issues_absent` | INFO |
| raw run dir referenced by staging (R2 addition) | curated.lineage / `raw_lineage` | FAIL (official), WARN (mirror) |

A check whose input is absent runs no other logic; it must not crash.

### 1.3 Checks (fixed order) and status rules
Each finding has a `level`, which is FAIL, WARN or INFO when unaccepted. A check's status is the highest unaccepted level among its findings, otherwise PASS.
Overall status is FAIL if any check is FAIL, else WARN if any is WARN, else PASS.
Accepted findings never raise a status, but they are always listed. The md headline shows e.g. `PASS — 2 accepted, 0 proposed`.

| check_id | what it checks (rule names in §1.4) |
|---|---|
| known_issues.file | parse and validate `configs/known_issues.json` (§1.5) |
| curated.schema | exact columns and dtypes of fact_draw, fact_draw_number and dim_number; manifest keys |
| curated.lineage | `curated_matches_staging`; `manifest_consistency`; `raw_lineage`; `frozen_prefix` on curated **and** official staging |
| curated.missing | null count per column |
| curated.duplicates | draw_id; draw_date; (draw_id, position); `duplicate_content` |
| curated.ranges | `validate_record` + `validate_dataset` over fact_draw; `retrieved_after_draw` |
| coverage.gaps | `first_draw` (00001 on 2017-08-01); draw_id gaps; `draw_cadence` |
| coverage.freshness | one `freshness` finding per missed scheduled date. Status comes from the count of unaccepted missed dates: 0 → PASS, 1–6 → WARN, more than 6 → FAIL. A date not yet past its 21:00 deadline gives `freshness_pending` INFO |
| staging.schema | columns = `STAGING_COLS`, per source |
| ingestion.runs | latest run per source: `run_failed`, `run_partial`, `incremental_empty_fetch`; `mirror_shrink`; `log_integrity` |
| quality_log.open | open items, defined below |
| reconcile.sources | `assess_reconcile(official, mirror)` |
| raw.checksums | `RawArchive.verify` on every manifest. A missing file is `raw_checksum` FAIL: catch the error, do not crash |
| refresh.history | the last 10 refresh_log rows; INFO only |

Definitions:
- **The source "has stored rows"** if an earlier ingestion_log run of that source had `rows_inserted > 0`. `incremental_empty_fetch` fires when the latest run of a source is `mode=incremental`, has `rows_received == 0`, and the source has stored rows.
- **`mirror_shrink`** (R3 N1, D3): `received` = `received_ids()` of the latest mirror run that has a raw manifest. Evaluated only when `received` is non-empty (an empty fetch is `incremental_empty_fetch`). WARN if `max(received) < max(staged)` or if the staged ids are not a subset of `received`.
- **`rows_rejected(run_id)`** is the number of distinct draw_ids with error severity in quality_log for that run. It is derived, so the ingestion_log columns are unchanged.
- **Open quality_log items**:
  - Items are keyed by (source, draw_id, rule). The source comes from joining to ingestion_log on run_id; an orphan run_id is `log_integrity`.
  - An error item is OPEN if its draw_id is absent from that source's staging. A `stored_row_conflict` item is OPEN until a later run of the same source includes that draw_id in `received_ids()` and logs no conflict for it (R3 N2). Otherwise it is RESOLVED (listed only).
  - Open error on the official source → FAIL. Open error on the mirror → WARN.
  - Warnings are shown as counts only; the status of current-data warnings comes from `curated.ranges`.
- **Reconcile findings** are one per draw_id:
  - `reconcile.field_mismatch` has observed = `{field: {vietlott_official: v, github_mirror: v}}` for each differing field.
  - `only_left` inside the mirror's id range → `reconcile.only_left`. Above the mirror's maximum → `reconcile.mirror_lag` (per draw).
  - Mirror absent or not run → `reconcile.not_run`.
  - When the mirror is down, reconcile uses the previous mirror staging. The draw it lacks shows as lag INFO, so the WARN comes from `ingestion.runs` only.

### 1.4 Rule / source vocabulary (defined in `known_issues.RULES`)
Source column:
- **off** = `vietlott_official`
- **mir** = `github_mirror`
- **sys** = `system` (not a data source)
- **as run** = the source of the ingestion run
- Curated findings use the manifest source (off).

Reconcile findings take the source that is missing or disagreeing: `only_left` → mir, `only_right` → off, `field_mismatch` → mir.

"Never" means the rule can never be accepted by a known issue (D4, D5). "pin" means acceptance needs `pins[rule]` equal to the finding's `observed` as exact JSON with string values (R3 N8).

| rule | check | source | unaccepted level | KI-acceptable |
|---|---|---|---|---|
| `known_issues_file` | known_issues.file | sys | FAIL | never |
| `known_issue_proposed`, `known_issue_expired`, `known_issue_unused` | known_issues.file | sys | WARN (INFO for a date-range entry once `as_of` > `draw_date_to`, R3 N9) | never |
| `known_issue_rule_unused`, `known_issues_absent` | known_issues.file | sys | INFO | never |
| `input_missing` | per §1.2 table | per input | per §1.2 table | never |
| `curated_schema` | curated.schema | off | FAIL | never |
| `curated_matches_staging`, `manifest_consistency`, `frozen_prefix` | curated.lineage | off | FAIL | never |
| `raw_lineage` | curated.lineage | off / mir | FAIL / WARN | never |
| `null_required` | curated.missing | off | FAIL | never |
| `special_present` | curated.missing, quality_log | off / mir | WARN | off, mir |
| `draw_id_unique`, `draw_date_unique` | curated.duplicates, quality_log | off / mir | FAIL / WARN | mir only (never for off) |
| `position_unique` | curated.duplicates | off | FAIL | never |
| `duplicate_content` | curated.duplicates | off / mir | WARN | off, mir |
| `draw_id_format`, `draw_date_parseable`, `not_future_dated`, `main_count`, `main_integer`, `main_range`, `main_unique`, `special_range`, `special_not_in_main`, `chronological_order` | curated.ranges, quality_log | off / mir | FAIL / WARN | mir only |
| `draw_weekday`, `main_sorted`, `draw_id_continuity` | curated.ranges, coverage.gaps, quality_log | off / mir | WARN | off, mir |
| `retrieved_after_draw` | curated.ranges | off | FAIL | never |
| `first_draw` | coverage.gaps | off | FAIL | never |
| `draw_cadence` | coverage.gaps | off | INFO | – |
| `freshness` | coverage.freshness | off | WARN / FAIL (by count) | off, date range only |
| `freshness_pending` | coverage.freshness | off | INFO | – |
| `staging_schema` | staging.schema | off / mir | FAIL / WARN | never |
| `run_failed` | ingestion.runs | off / mir | FAIL / WARN | never |
| `run_partial` | ingestion.runs | off / mir | WARN / INFO | never |
| `incremental_empty_fetch` | ingestion.runs | off / mir | FAIL / WARN | never |
| `mirror_shrink` | ingestion.runs | mir | WARN (only when `received` is non-empty) | never |
| `log_integrity` | ingestion.runs, quality_log.open | sys (as run, for a missing quality_log) | WARN; FAIL for a missing quality_log with a partial official run (R3 N6) | never |
| `stored_row_conflict` | quality_log.open | off / mir | FAIL / WARN | mir only, no pin (never for off, R3 N2) |
| `reconcile.field_mismatch` | reconcile.sources | mir | FAIL | mir, with pin |
| `reconcile.only_left` | reconcile.sources | mir | WARN | mir |
| `reconcile.only_right` | reconcile.sources | off | WARN | off |
| `reconcile.mirror_lag` | reconcile.sources | mir | INFO if lag ≤ 3 draws, else WARN | never |
| `reconcile.not_run` | reconcile.sources | mir | WARN | never |
| `raw_checksum` | raw.checksums | as run | FAIL | never |
| `raw_manifest_missing` | raw.checksums | as run | WARN | never |
| `refresh_history` | refresh.history | sys | INFO | – |

A rejected official row (an official error in quality_log) or an official `stored_row_conflict` cannot be accepted. It stays FAIL until data-architect designs a fix; this is an escalation.

### 1.5 Known issues (`configs/known_issues.json`): accept visibly, never suppress
Format: `{"schema_version": "1.0", "issues": [...]}`.

Fields of each entry:
- `id` (`^KI-\d{3}$`, unique)
- `source` (must be in `SOURCES`)
- `rules` (a non-empty list; each rule must be KI-acceptable for that source in §1.4)
- exactly one of:
  - `draw_id` (`^\d{5}$`)
  - `draw_date_from` + `draw_date_to`: allowed only when `rules == ["freshness"]`; to − from ≤ 60 days; `draw_date_to` ≤ `review_by`
- `pins` (an object keyed by rule; required for every rule marked "pin" in §1.4)
- `reason`, `evidence`
- `approved_by`, `approved_on` (ISO date), `approval_ref`
- `review_by` (ISO date)

Validation:
1. Any violation of the allowlist above is `known_issues_file` FAIL. This includes wildcards, regexes, empty values, unknown keys and a duplicate id. The file fails closed.
2. Entry state at `as_of`:
   - **proposed**: `approved_by`, `approved_on` or `approval_ref` is empty, or `approved_on` > the ICT date of `as_of`. WARN.
   - **expired**: `review_by` < the ICT date of `as_of`. WARN.
   - **active**: otherwise.
   Only active entries accept findings. Proposed and expired entries annotate matching findings (`known_issue_id`, `known_issue_state`) without accepting them.
3. An entry matches a finding if:
   - the sources are equal, and the finding's rule is in `rules`, and
   - (`draw_id` is equal) or (the rule is `freshness` and the finding's `draw_date` is within the range)
   - For pinned rules, `pins[rule]` must equal `finding.observed` as exact JSON, with every value a string (`"10"`, not `10`). A mismatch, including a type mismatch, is not accepted, and the finding is annotated `pin_mismatch` (R3 N8).
   Freshness levels are computed after matching. The date range is the pin, and each missed date is matched on its own.
4. `matched` is reported per rule. An active entry with 0 matches in total → `known_issue_unused` WARN (the source may have fixed the issue). A rule with 0 matches → `known_issue_rule_unused` INFO.
5. A date-range entry whose range has elapsed (`as_of` > `draw_date_to`) reports `known_issue_proposed`, `known_issue_expired` and `known_issue_unused` as INFO, not WARN (R3 N9).

**Transcription rule (finding 1).** An agent may fill `approved_by`, `approved_on` and `approval_ref` only by copying a decision recorded under TASKBOARD "Decisions". `approval_ref` must name that section. data-qa cross-checks every approved entry against TASKBOARD, and an entry without a matching decision is a review failure. Agents never invent approvals; any other entry they add must stay proposed.

Seed entry. data-engineer creates it exactly as follows (TASKBOARD Decisions 2026-09-24):
```json
{"id": "KI-001", "source": "github_mirror", "draw_id": "00944",
 "rules": ["chronological_order", "reconcile.only_left"], "pins": {},
 "reason": "Mirror row 00944 is dated 2022-09-23 (Fri), has 6 numbers and no special; likely a Mega 6/45 row. Official 00944 is 2023-10-14.",
 "evidence": "reports/data_quality_2026-09-24_M1-review.md",
 "approved_by": "project-lead (human)", "approved_on": "2026-09-24",
 "approval_ref": "TASKBOARD Decisions 2026-09-24", "review_by": "2027-03-31"}
```
The mirror warnings on 00944 (`special_present`, `draw_weekday`) are not covered. They appear only in the quality_log warning counts and do not affect status.

### 1.6 Validation rule additions (methodology-auditor to review)

| rule | where | level | definition |
|---|---|---|---|
| `duplicate_content` | `validate_dataset` (warning) and curated.duplicates | WARN | key = (sorted main numbers, special), without the date. The later draw_id is flagged and the detail names the earlier one. Chance of any match ≈ 6.9e-4 at n = 1401. The real pair 00647/00993 shares only the main set, so it must not fire |
| `retrieved_after_draw` | report, curated | FAIL | `retrieved_at` ≥ draw_date at 18:00 ICT |
| `frozen_prefix` | report (curated + official staging), the refresh curate gate and the manual `curate` CLI (exit 30, nothing written; R3 N4) | FAIL, never acceptable | rows with draw_id ≤ `FROZEN_LAST_DRAW`, read via `read_fact_draw`, must give `dataset_version == FROZEN_VERSION`, and there must be exactly 1401 such rows |
| `raw_lineage` | report | FAIL off / WARN mir | every staging row must equal (CONTENT_COLS, main sorted) a record parsed offline from its `raw_run_id`; a missing raw run also fails |
| `curated_matches_staging` | report | FAIL | manifest version = `dataset_version(read_fact_draw)` = `dataset_version(official staging)` |
| `manifest_consistency` | report | FAIL | manifest counts = file rows; fact_draw_number = 6·n + n_special; a single `dataset_version`; the source column equals the manifest source |
| `first_draw` | report | FAIL | the first curated row is 00001 on 2017-08-01 |
| `draw_cadence` | report | INFO | a gap that skips at least one scheduled date (documents O3) |
| `freshness` | report | WARN/FAIL | §1.3 |
| `incremental_empty_fetch` | report + refresh | FAIL off / WARN mir | fixes O2 (D3) |
| `mirror_shrink` | report | WARN | §1.3 (D3; only when `received` is non-empty) |
| `log_integrity` | report | WARN / FAIL | an orphan quality_log run_id, `finished_at` < `started_at`, or an unparseable row (WARN); a missing quality_log while a run is partial (WARN mirror, FAIL official; R3 N6) |
| `known_issues_file` | report | FAIL | the file fails closed |

Already covered, so no new rule: `draw_date_unique` in staging (strict `chronological_order` implies it; the curated check is explicit); special present (existing rule).

### 1.7 JSON schema (`schema_version` "1.0")
Top-level keys:
- `schema_version`, `report_date`, `as_of`, `run_context` ("refresh" | "standalone"), `lock_held` (bool), `overall_status`
- `summary`
- `dataset`: `{dataset_version, source, draws, first_draw_id, first_draw_date, last_draw_id, last_draw_date}`
- `inputs`: `[{path, sha256, rows}]` for every file read, with raw summarised per run dir
- `checks`: `[{check_id, status, summary, metrics, findings}]`
- `ingestion_runs`: every ingestion_log row, plus `rows_rejected`
- `known_issues`: `[{id, state, matched: {rule: n}}]`

Each finding has:
- `source`, `draw_id`, `draw_date`, `rule`, `level`, `detail`, `observed`
- `accepted`, `known_issue_id`, `known_issue_state`

`summary` counts (integers; the first five count **unaccepted** WARN/FAIL findings):
- `missing`: from curated.missing
- `duplicate`: from curated.duplicates
- `invalid_ranges`: from curated.ranges
- `schema_errors`: from curated.schema + staging.schema
- `ingestion_failures`: ingestion_log rows with `status == "failed"` (all time) + unaccepted `incremental_empty_fetch` findings
- `accepted`: findings with `accepted = true`
- `proposed`: findings annotated by a proposed or expired entry

The md has one section per check, with tables capped at 20 findings ("+N more; see JSON"). It also lists the last 20 ingestion runs and has a mandatory **Known issues: accepted / proposed / expired** section.

### 1.8 Acceptance criteria
1. Two runs with the same inputs and the same `as_of` give byte-identical md and JSON. An `as_of` given in UTC and the equivalent ICT instant give identical output.
2. The report makes no network calls and writes only under `--out-dir`.
3. Every rule in §1.4 has a test for its non-PASS level and for PASS. Every never-acceptable rule has a test showing that a KI cannot accept it.
4. Real data, with `--as-of 2026-09-24T12:00:00+07:00` and KI-001 as seeded in §1.5:
   - overall **PASS**, exit 0
   - `known_issues.matched` = `{chronological_order: 1, reconcile.only_left: 1}`
   - the md lists both 00944 findings as accepted
   On a temporary copy of the file with the approval fields blanked (tests only; never edit the real file), the result is **WARN** on exactly `known_issues.file`, `quality_log.open` and `reconcile.sources`.
5. `frozen_prefix` passes on real data and fails if any draw ≤ 01401 is altered in a copy.
6. The JSON has the §1.7 keys and all 7 summary counts.
7. SPECIFICATION §4 and the README are updated, and the full `python -m pytest` passes.

### 1.9 Test plan (`tests/test_quality_report.py`, `tests/test_known_issues.py`, `tests/test_schedule.py`, `tests/test_lineage.py`)
**Fixtures.** A `build_fixture(paths, draws, mirror_draws)` helper:
- runs `run_ingestion` for **both** `vietlott_official` (FakeSession returning `official_html` pages) and `github_mirror` (jsonl text)
- then runs `build_curated`
- `as_of` is the last fixture draw date at 21:30 ICT

Tests use a `frozen` fixture that patches `FROZEN_LAST_DRAW`/`FROZEN_VERSION` to the fixture's prefix. A session-scoped autouse guard in `conftest.py` takes a recursive snapshot of every file under the real `data/` and `reports/` (relative path, size, `mtime_ns`) and asserts at session end that it is identical; directory mtimes are not enough (R3 N3). Tests never touch real `data/`.

Tests by group:
- **Determinism and output:** `test_clean_fixture_passes`, `test_byte_deterministic`, `test_as_of_utc_equals_ict`, `test_findings_sort_with_null_draw_id`, `test_json_top_level_keys`, `test_summary_counts`, `test_cli_quality_report_exit_codes` (0/10/30), `test_cli_uses_injected_paths`.
- **Absent inputs:** `test_absent_inputs_table` (parametrised over §1.2).
- **Curated checks:**
  - `test_duplicate_draw_id_fail`, `test_duplicate_content_warn`, `test_duplicate_main_only_not_flagged`
  - `test_out_of_range_fail`, `test_null_required_fail_null_special_warn`, `test_missing_column_fail`
  - `test_curated_stale_vs_staging_fail`, `test_manifest_count_mismatch_fail`
  - `test_retrieved_before_draw_fail` (retrieved 17:00 ICT on the draw day)
  - `test_first_draw_wrong_fail`
- **Lineage:** `test_frozen_prefix_fail`, `test_staging_row_not_in_raw_fail`, `test_missing_raw_run_fail`.
- **Raw and ingestion:**
  - `test_corrupt_raw_fail`, `test_missing_raw_file_fail_not_crash`
  - `test_latest_official_failed_fail`, `test_latest_mirror_failed_warn`
  - `test_official_empty_fetch_fail`, `test_mirror_empty_fetch_warn`, `test_mirror_shrink_warn` (both conditions; not evaluated when `received` is empty)
  - `test_orphan_quality_log_warn`, `test_quality_log_open_vs_resolved`, `test_stored_row_conflict_resolved_by_clean_rerun`, `test_missing_quality_log_with_partial_run` (mirror WARN, official FAIL)
- **Reconcile:** `test_reconcile_mismatch_fail`, `test_mirror_lag_info_then_warn`, `test_only_right_warn`.
- **Known issues:**
  - `test_ki_accepts_but_lists` (the 00944 scenario), `test_ki_proposed_does_not_accept`, `test_ki_future_approved_on_is_proposed`
  - `test_ki_expired_stops_accepting`, `test_ki_unused_warn`, `test_ki_matched_per_rule`
  - `test_ki_allowlist_violations_fail` (parametrised: wildcard, bad source, bad draw_id, unknown rule, unknown key, duplicate id)
  - `test_ki_malformed_fail_absent_info`
  - `test_ki_cannot_accept_integrity_rule` (parametrised over the never-acceptable rules)
  - `test_ki_mismatch_pin_mismatch_not_accepted`, `test_ki_mismatch_pinned_accepted`, `test_ki_pin_integer_not_accepted`
  - `test_ki_range_does_not_cover_later_missed_dates`, `test_ki_range_over_60_days_fail`, `test_ki_range_beyond_review_by_fail`, `test_ki_elapsed_range_is_info`
- **Freshness and schedule:**
  - `test_freshness_pending_before_deadline`, `test_freshness_warn`, `test_freshness_fail_over_6`
  - `test_expected_latest_draw_date`: Tue 17:59, Tue 21:00, Wed 08:30, Sun 08:30 and Sat→Tue

---

## 2. Task Card M2-T3

```text
TASK_ID: M2-T3
TITLE: `refresh` command, run lock, Windows Task Scheduler scripts, monitoring
TYPE: DATA   RISK: MEDIUM (+ refresh_log schema, §0)
PRIMARY_MODEL: data-architect   IMPLEMENTATION_MODEL: data-engineer   REVIEWER: data-qa, then qa-runner
OBJECTIVE: One idempotent command that brings staging/curated/report up to date after each draw, with explicit
  failure semantics and exit codes, and makes every failed or partial run visible without reading code.
INPUT: M2-T2 modules; src/ingestion/loader.py; src/api/registry.py.
OUTPUT: src/ingestion/lock.py, src/ingestion/refresh.py, CLI `refresh` and `status`, data/logs/refresh_log.csv,
  data/logs/ALERT.txt, scripts/run_refresh.ps1, scripts/register_refresh_task.ps1, scripts/unregister_refresh_task.ps1.
DEPENDENCIES: M2-T2 done; M2-T4 batched.   ACCEPTANCE_CRITERIA / TEST_PLAN: §2.9 / §2.10.
RISKS / ESCALATION_CONDITION: §3.   STATUS: NEEDS_REVIEW (design, revision 3)
```

### 2.1 Flow: `run_refresh(paths, as_of=None, source_factory=get_source, known_issues_path=None) -> RefreshResult`
The CLI acquires the lock (§2.4) *before* calling `run_refresh`. The function itself never locks.

Each numbered step is wrapped in `try/except Exception`. A failure is recorded in the result and the remaining steps still run, with one exception: step 4 is skipped if its inputs are unusable.

0. Write ALERT.txt: `started, not finished <refresh_id> <started_at>`. Log `refresh_start` with `refresh_id` and `as_of`. Record `version_before` from the manifest.
1. Official: `run_ingestion(official, "incremental", today=as_of ICT date)`. The result is `official_status`: success | partial | failed | empty. `empty` is `incremental_empty_fetch` (D3).
2. Mirror: always attempted, even if step 1 failed. The result is `mirror_status` (the same values).
3. Reconcile: if both staging files exist, run `assess_reconcile(...)` with `published_ids` = the draw_ids of `read_fact_draw(curated)` (R3 N7). Otherwise `reconcile_status=skipped`.
4. Curate: take the first matching `curate_action`.
   - `skipped`: `official_status` is failed or empty.
   - `blocked`:
     - `frozen_prefix` fails on the official staging, or
     - `blocking_ids` is non-empty, i.e. an unaccepted mismatched id is in the set about to be published (official staging ids minus the draw_ids of `read_fact_draw(curated)`) (D2, R3 N7).
     Otherwise curate proceeds, and the report FAILs on `reconcile.sources`.
   - `unchanged`: the official staging version equals the manifest version (no rewrite, so `built_at` stays stable).
   - `rebuilt`: `build_curated`. Each file is written temp + `os.replace`, with `dataset_manifest.json` last.
     - On Windows, a `PermissionError` is retried 3 times with 1 s sleeps.
     - After that, or on any other exception, the action is `failed`. The manifest is not written, so `curated_matches_staging` reveals the half-state.
5. Report: `build_quality_report(run_context="refresh", as_of=refresh start)` + `write_quality_report`. Always run.
6. Compute the exit code (§2.3).
   - Append the refresh_log row.
   - Replace ALERT.txt with the final alert if exit ≠ 0, or delete it if exit = 0.
   - Log `refresh_finished` with `refresh_id` and `exit_code`.
   - The CLI prints the final stdout line `REFRESH_RESULT <compact json>`.

### 2.2 Failure semantics

| situation | curated | report | exit |
|---|---|---|---|
| mirror down, official OK | updated | WARN from `ingestion.runs` only (`run_failed` mir); reconcile shows lag INFO against the previous mirror staging | 10 |
| official down (the mirror still ingests) | untouched | FAIL `run_failed` | 30 |
| official empty fetch (O2, D3) | untouched | FAIL `incremental_empty_fetch` | 30 |
| mirror empty fetch or shrink | updated | WARN (`incremental_empty_fetch` / `mirror_shrink`, R3 N1) | 10 |
| realistic mismatch: 20:00 publishes 01402 (mirror lags), 08:30 mirror disagrees on 01402 | unchanged (01402 already published; not blocked) | FAIL `reconcile.field_mismatch` | 30 |
| mismatch on a draw not yet published (both sources gain it in the same run and disagree) | blocked (previous version kept) | FAIL `reconcile.field_mismatch` + `curated_matches_staging` | 30 |
| mismatch covered by an active, pinned KI | updated | the finding is listed as accepted | 0 / 10 |
| new draw not yet published, before 21:00 ICT | unchanged | PASS (`freshness_pending` INFO) | 0 |
| draw still missing after 21:00 ICT | unchanged | WARN, or FAIL beyond 6 missed draws | 10 / 30 |
| mirror row 00944 recurs (O1) | n/a | accepted by KI-001 | 0 |
| another run holds the lock | untouched | not generated; refresh_log row only; ALERT untouched | 40 |
| an unexpected exception outside the steps | as left | attempted | 50 |

### 2.3 Exit codes (D1)
`0` PASS · `10` WARN · `30` FAIL (report FAIL, official failed or empty, or curate blocked/failed) · `40` LOCKED · `50` INTERNAL (an uncaught exception, or no report was written).
- Precedence: 50 > 30 > 10 > 0. 40 applies on its own.
- Code 1 is never a data status. Argparse usage errors are 2, and the wrapper maps them to 50.
- `quality-report` uses 0/10/30/50. `status` uses 0 (healthy) or 10 (needs attention).

### 2.4 Lock and ALERT (`src/ingestion/lock.py`)
- `RunLock(path=paths.data/".refresh.lock", stale_after=timedelta(minutes=120), command=...)` is a context manager.
  - It creates the lock with `os.open(O_CREAT | O_EXCL | O_WRONLY)` and writes JSON `{pid, refresh_id, command, started_at}`.
  - If the lock is held, it raises `LockHeldError(holder)`.
- **Stale lock**: `started_at` is older than `stale_after`. If the JSON is unreadable, the file mtime is used. The Task Scheduler limit is 60 min, so a lock this old cannot belong to a live run.
  - To break it, run `os.replace(lock, f"{lock}.stale.{os.getpid()}")`, then retry the O_EXCL create **once**.
  - If the replace raises `FileNotFoundError`, or the retry hits `FileExistsError`, another process won the race → `LockHeldError`.
  - The break is logged and written to the refresh_log `message`. **Never use `os.kill(pid, 0)`**: on Windows it terminates the process.
- The lock is taken only in the CLI handlers for `refresh`, `ingest` and `curate`, never inside `run_ingestion` or `build_curated`. Library calls and tests stay lock-free. `quality-report` does not lock. It records `lock_held` (whether the lock file exists) in the JSON, so a standalone report taken during a refresh is flagged.
- An exit-40 run appends a refresh_log row (`exit_code=40`, run columns empty) and **does not touch ALERT.txt**.

### 2.5 CLI and logging
- `main(argv: list[str] | None = None, paths: Paths | None = None) -> int`. `paths` defaults to `Paths()`, and every command uses the injected paths.
- `ingest` exits 2 (argparse error) if `--start` or `--end` is given without `--full`.
- `curate` runs `check_frozen_prefix` on the official staging first. On failure it exits 30 and writes nothing (R3 N4).
- `python -m src.cli refresh [--lock-timeout-minutes 120] [--as-of ISO8601]`. `--as-of` is accepted without limits only when `main` is given injected `paths` or `run_refresh` an injected `source_factory` (tests). Otherwise an `as_of` earlier than now − 1 h is rejected (argparse error, exit 2) (R3 N5).
- `python -m src.cli status` prints:
  - the last refresh_log row and its age
  - consecutive non-zero exits
  - the latest report's `overall_status`
  - the next scheduled draw
  - whether ALERT.txt exists

  It exits 10 if the last refresh is older than 4 days, if there is no row, if the last exit was not 0, or if ALERT.txt exists. Otherwise it exits 0.
- Logging: the default level is INFO. `refresh_start` has `refresh_id` and `as_of`. `refresh_finished` has `refresh_id`, `exit_code`, `curate_action` and `overall_status`. Both go to `app.log` as JSON lines.

### 2.6 `data/logs/refresh_log.csv` (new, additive)
Columns:
- `refresh_id`, `started_at`, `finished_at`, `exit_code`, `overall_status`
- `official_run_id`, `official_status`, `official_new_draws`
- `mirror_run_id`, `mirror_status`
- `reconcile_status`, `curate_action`
- `dataset_version_before`, `dataset_version_after`
- `report_json`, `report_sha256` (sha256 of the JSON report bytes, D6)
- `message`

Rows are appended. A lock-contention run appends a row with `exit_code=40` and empty run columns.

### 2.7 Scheduling scripts (agents never execute any `.ps1`)
**`scripts/run_refresh.ps1 -PythonExe <path>`** is the Task Scheduler action.
- `Set-Location "$PSScriptRoot\.."`, then set `$env:PYTHONIOENCODING = "utf-8"`.
- Set `$ErrorActionPreference = 'Continue'` around the native call. In PS 5.1, stderr combined with `Stop` throws.
- Run `& $PythonExe -m src.cli refresh 2>&1 | Tee-Object -FilePath data\logs\scheduler\refresh_<yyyyMMdd_HHmmss>.log`, then capture `$code = $LASTEXITCODE`.
- Pass **no `--log-level`** (finding 10).
- If `$code` is not in {0, 10, 30, 40, 50}, or the log lacks a `REFRESH_RESULT ` line (except when `$code` is 40), set `$code = 50`.
- Keep only the newest 60 scheduler logs, then `exit $code`.

**`scripts/register_refresh_task.ps1 [-PythonExe <path>] [-DrawRunTime 20:00] [-RetryTime 08:30] [-Replace] [-Force]`**:
- Task `\Power655\Refresh`. `-PythonExe` defaults to `(Get-Command python).Source` and is resolved to an absolute path.
- Reject a `-PythonExe` path containing `\WindowsApps\` (the Store alias). From the project root, run `& $PythonExe -c "import pandas, bs4, src.cli"` and abort if it fails (R3 N9).
- Action: `powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "<abs root>\scripts\run_refresh.ps1" -PythonExe "<abs python>"`, with `-WorkingDirectory <abs root>`.
- Triggers:
  - weekly Tue/Thu/Sat at 20:00 (draw night)
  - weekly Wed/Fri/Sun at 08:30 (next-day retry; it always runs, which is safe because refresh is idempotent)
- Timezone: if the local UTC offset is not +07:00, abort unless `-Force` is given. With `-Force`, the human asserts that the times are local.
- Settings: `-StartWhenAvailable`, `-MultipleInstances IgnoreNew`, `-ExecutionTimeLimit (New-TimeSpan -Hours 1)`, `-AllowStartIfOnBatteries`, `-DontStopIfGoingOnBatteries`. Current user, interactive (no stored password).
- If the task already exists, fail unless `-Replace` is given. No hard-coded user paths.

**`scripts/unregister_refresh_task.ps1`** removes `\Power655\Refresh`. It is idempotent and prints "not registered" if the task is absent.

### 2.8 Monitoring: how a failed or partial run becomes visible
1. Task Scheduler "Last Run Result" shows 10, 30, 40 or 50.
2. `data/logs/ALERT.txt` holds either "started, not finished" (a crash or kill) or the final cause with the report path.
3. `refresh_log.csv` keeps the full history, with the report hash.
4. `reports/data_quality_latest.json` holds `overall_status` for the dashboard (page 1 "quality status").
5. `python -m src.cli status` gives a human check. It exits 10 if refreshes have stopped.
6. The console logs in `data/logs/scheduler/` catch failures that happen before Python starts. `app.log` holds the `refresh_start`/`refresh_finished` events.

Limitation: no external watchdog exists. If the PC is off, only `status` and freshness reveal it.

### 2.9 Acceptance criteria
1. Every row of §2.2 has a mocked test (no network). It asserts `curate_action`, the exit code, the refresh_log row (including `report_sha256`) and the ALERT.txt state.
2. A second refresh with no new data inserts 0 rows, keeps the manifest bytes and `dataset_version`, and gives the same exit code.
3. Lock:
   - When the lock is held, no source is called and the exit code is 40.
   - A stale lock is broken via `os.replace`, and the race loser gets 40.
   - The lock is released after exceptions.
   - `ingest` and `curate` respect the lock.
4. A failure injected between the curated file writes leaves the old manifest in place, and the report FAILs `curated_matches_staging`.
5. `.ps1` files:
   - They pass a parse-only check (`[System.Management.Automation.Language.Parser]::ParseFile` reports no errors). The test is skipped if PowerShell is missing and **never executes** a script.
   - They contain no `C:\Users` literal and no `--log-level`.
   - `run_refresh.ps1` contains `Set-Location` and `exit $code`.
   - `register_refresh_task.ps1` contains the `\WindowsApps\` rejection and the `import pandas, bs4, src.cli` check (static text check only; R3 N9).
6. At most one real `refresh`, run by data-engineer. It must exit **0** with `overall_status=PASS`. `curate_action` is `unchanged`, or `rebuilt` if draw 01402 has already been published. Any other result is an escalation.
7. README section "Scheduled refresh" covers:
   - the register and unregister commands, which the human runs
   - the exit codes
   - `status`
   - ALERT.txt
   - how to add a known issue: proposed first, approved only via TASKBOARD Decisions
8. The full `python -m pytest` passes, and the real-data guard shows `data/` unchanged by tests.
9. Logging:
   - (a) `run_refresh.ps1` passes no `--log-level` (asserted in `test_scripts`).
   - (b) `main(["refresh"], paths=tmp)` writes JSON lines `refresh_start` (with `refresh_id`) and `refresh_finished` (with `refresh_id` and `exit_code`) to `tmp/data/logs/app.log`.
   - (c) Tests restore the root logging handlers in a fixture.

### 2.10 Test plan (`tests/test_refresh.py`, `tests/test_lock.py`, `tests/test_scripts.py`)
Inject `source_factory` that returns sources built on `FakeSession`/`RoutingSession`. Use `paths=tmp`.
- **Refresh outcomes:**
  - `test_happy_new_draw_mirror_lag_exit0`
  - `test_no_new_draw_before_deadline_exit0_unchanged`, `test_missing_after_deadline_exit10`
  - `test_mirror_down_exit10_curated_updated`
  - `test_official_down_exit30_mirror_still_ingested`
  - `test_official_empty_fail_exit30`, `test_mirror_shrink_warn_exit10`
  - `test_realistic_mismatch_2000_then_0830_not_blocked_exit30`
  - `test_mismatch_on_unpublished_draw_blocks`
  - `test_mismatch_accepted_by_pinned_ki_curates`
  - `test_frozen_prefix_violation_blocks_curate`
  - `test_second_run_idempotent`
- **Failure handling and outputs:**
  - `test_refresh_catches_non_runtime_error_and_still_reports`
  - `test_curated_manifest_written_last` (inject a failure after fact_draw)
  - `test_permission_error_retried_then_failed`
  - `test_alert_started_then_final_then_cleared`
  - `test_refresh_log_has_report_sha256`
  - `test_internal_error_exit50_lock_released`
  - `test_refresh_logging_events`
- **Lock:**
  - `test_lock_held_exit40_no_source_calls`, `test_exit40_does_not_touch_alert`
  - `test_stale_lock_broken_and_logged`, `test_stale_lock_break_race`
  - `test_ingest_cli_respects_lock`, `test_ingest_rejects_start_without_full`, `test_curate_cli_frozen_prefix_exit30_writes_nothing`
- **CLI:** `test_cli_uses_injected_paths`, `test_status_exit_codes`, `test_refresh_as_of_in_past_rejected_without_injection`.
- **Scripts:** `test_ps1_parse_only`, `test_ps1_no_hardcoded_user_paths`, `test_ps1_sets_location_and_no_log_level`, `test_register_rejects_windowsapps_and_checks_imports`.

---

## 3. Risks and escalation (both tasks)

Risks:
- The 21:00 ICT publication deadline is an assumption. A late publication shows WARN only until the next-day retry. Tune the constant; do not suppress the check.
- Tết (one skipped draw) gives a freshness WARN at the next retry. A suspension FAILs beyond 6 missed draws until a ≤ 60-day date-range KI is approved via TASKBOARD.
- A mismatch on an already-published draw (D2) leaves curated as published while the report FAILs. Downstream users must check `data_quality_latest.json` before use; bi-engineer surfaces this on dashboard page 1.
- The mirror raw file (about 0.1 MB) is archived on each of about 6 runs a week, and quality_log grows by 3 rows per mirror run (O1). Both are accepted as history; revisit in M8.
- `raw_lineage` re-parses every referenced raw run on every report, about 180 pages, which takes seconds. Revisit if the archive grows large.

data-engineer escalates to data-architect and stops if any of these happen:
- the `ingestion_log`/`quality_log`/staging/curated columns, the `DrawSource` contract or the `dataset_version` algorithm would need to change
- real data gives anything other than §1.8-4 or §2.9-6
- `frozen_prefix` or `raw_lineage` fails on real data
- determinism cannot be achieved
- a source behaves differently from O1, O2 or O5
- an official row is rejected (not KI-acceptable)
- a fix touches modules outside §1.1 or §2
- anything would rewrite stored staging or curated history

Out of scope: no betting, number-selection or purchase features. The report describes data integrity only.
