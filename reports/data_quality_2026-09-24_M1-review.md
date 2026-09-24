# Data Quality Review — M2-T1 (independent review of M1 ingestion)

Reviewer: Data QA (role 5.3, AI-agent.md). Scope: `data/`, `src/api`, `src/ingestion`, `src/validation`, `tests/`.
No edits made to `src/` or `tests/`. No `--full` ingest run. No new incremental ingest was run by this review — one incremental run of `vietlott_official` (`run_id 20260924T031030Z_82a958`) already existed in the logs before this review started and is used as the idempotency evidence below.

Verdict: **PASSED** (one non-blocking finding, see #7).

---

## 1. `python -m src.cli verify-raw`

Result: all 3 archived runs verified OK, no checksum mismatches.

```
github_mirror/20260924T031012Z_13d471: OK
vietlott_official/20260924T030626Z_00d6df: OK
vietlott_official/20260924T031030Z_82a958: OK
```

## 2. `python -m src.cli reconcile --left vietlott_official --right github_mirror`

Result: `matched=1400, only_left=1 (00944), only_right=0, mismatched_draws=0, ok=true`.
No field-level mismatches on the 1400 draws present in both staging tables. The single asymmetry (draw 00944) is investigated in §6.

## 3. Logs

- `data/logs/ingestion_log.csv` (4 lines incl. header): 3 runs — `vietlott_official` full (1401 received/inserted, success), `github_mirror` full (1401 received, 1400 inserted, 1 skipped, status `partial`), `vietlott_official` incremental (8 received, 0 inserted, 8 skipped, success). The incremental run correctly received the last page (8 rows, since the source doesn't paginate by exact draw count) but inserted 0 new rows because all 8 were already in staging — this is the idempotency evidence for the incremental path.
- `data/logs/quality_log.csv` (4 lines incl. header): all 3 issues belong to the github_mirror run and to draw 00944 only (`draw_weekday` warning, `special_present` warning, `chronological_order` error). No open quality issues against `vietlott_official`.
- `data/logs/app.log`: 0 bytes despite the ingestion runs above having executed (each `run_ingestion` call emits `log.info` at start/fetch_done/finished via `src/ingestion/loader.py`). I independently called `configure_logging()` + `log.info(..., extra={...})` and confirmed the `JsonFormatter`/file handler mechanism itself works correctly (produces a valid JSON line and appends). So the code path is not broken, but the historical run log lines from the 3 ingestion runs were not persisted to `app.log` in this environment. See finding #7.

## 4. `data/curated/fact_draw.csv` structural checks (pandas, independent script)

| Check | Result |
|---|---|
| Row count | 1401 |
| `draw_id` unique | True |
| `draw_id` contiguous (00001..01401, no gaps) | True |
| `draw_date` strictly increasing | True |
| `draw_date` weekday only Tue/Thu/Sat | True (0 rows outside {Tue,Thu,Sat}) |
| 6 distinct main numbers per row, all in 1..55 | True (min=1, max=55, all rows have 6 distinct values) |
| special number in 1..55, not among main numbers | True (min=1, max=55, 0 missing, 0 rows where special ∈ main) |

## 5. `dataset_manifest.json` vs files

| Field | Manifest | Actual |
|---|---|---|
| `draws` / `fact_draw.csv` rows | 1401 | 1401 |
| `fact_draw_number.csv` rows | 9807 | 9807 |
| `dim_number.csv` rows | 55 | 55 |
| first_draw | 00001 / 2017-08-01 | 00001 / 2017-08-01 |
| last_draw | 01401 / 2026-09-22 | 01401 / 2026-09-22 |
| `dataset_version` | ds_cbdf3834368e | matches the single value in `fact_draw.csv.dataset_version` |

Manifest agrees with the curated files on every field checked.

## 6. Draw 00944 — official vs. github_mirror

- Official staging/curated: `00944,2023-10-14,8,23,30,34,38,47,10` — consistent with its neighbours (00943 = 2023-10-12, 00945 = 2023-10-17), a normal Tue/Thu/Sat cadence.
- Mirror raw file `data/raw/github_mirror/20260924T031012Z_13d471/page_00000.txt`, line 780:
  `{"date":"2022-09-23","id":"00944","result":[1,12,21,28,30,44],"process_time":"2022-10-11 13:24:08.982356"}`
  This line sits physically between the mirror's own 00779 (2022-09-22) and 00780 (2022-09-24) entries — i.e. the mirror's source data mislabelled a 2022-09-23 row as draw id `00944` (over a year off from where 00944 actually belongs), and it only carries 6 numbers (no 7th/special value), unlike every neighbouring row.
  Separately, the mirror's real chronological neighbours of id 00944 are 00943 (2023-10-12) and 00945 (2023-10-17) — the file never contains a correctly-dated 00944 row at all.
- Assessment: this is a data-entry defect in the `github_mirror` upstream source, not a parsing or ingestion bug. `src/validation/rules.validate_dataset` correctly caught it via the `chronological_order` rule (`error`: "draw 00944 dated 2022-09-23 not after draw 00943 dated 2023-10-12") because 00944's fabricated date is earlier than 00943's real date, and it also raised `draw_weekday` and `special_present` warnings. The row was correctly excluded from `github_mirror` staging, which is exactly why `reconcile` reports it as `only_left` (present in `vietlott_official`, absent from `github_mirror`) rather than as a mismatch. No fix is needed in `src/`; this is expected, correctly-handled behaviour of the validation and reconciliation logic.

## 7. Spot-check: 7 draws parsed independently from raw archive

I wrote a standalone script (regex + `json.loads`, not importing `src/api`) to parse the AjaxPro `HtmlContent` tables directly from `data/raw/vietlott_official/20260924T030626Z_00d6df/page_*.txt` and compared to `data/curated/fact_draw.csv`. All 7 matched exactly (date, 6 main numbers, special number):

| draw_id | raw page | independent parse | fact_draw.csv | match |
|---|---|---|---|---|
| 01209 | page_00024 | 2025-06-28, [8,11,13,20,45,50], 25 | same | yes |
| 01368 | page_00004 | 2026-07-07, [4,6,25,32,33,44], 8 | same | yes |
| 01285 | page_00014 | 2025-12-23, [2,10,16,25,32,38], 3 | same | yes |
| 01012 | page_00048 | 2024-03-23, [3,10,13,30,40,52], 4 | same | yes |
| 01031 | page_00046 | 2024-05-07, [21,26,35,41,44,52], 13 | same | yes |
| 00383 | page_00127 | 2020-01-14, [3,4,17,39,50,51], 53 | same | yes |
| 01401 | page_00000 | 2026-09-22, [1,3,9,11,41,46], 10 | same | yes |

7/7 draws (5 required) match byte-for-byte on every field.

## 8. API rules (agent.md "API rules" + PROJECT_STEPS §4/§6) — code and test mapping

| Rule | Code location | Test | Covered? |
|---|---|---|---|
| Timeout | `src/api/http_client.py:69` (`kwargs.setdefault("timeout", ...)`) | `tests/test_http_client.py:8 test_returns_first_success_and_passes_timeout` | Yes |
| Bounded retry | `src/api/http_client.py:70-94` (`attempts = max_retries + 1`, raises after loop) | `tests/test_http_client.py:44 test_gives_up_after_bounded_retries` | Yes |
| Exponential backoff | `src/api/http_client.py:50-52 _backoff` | `tests/test_http_client.py:16 test_retries_5xx_with_exponential_backoff` | Yes |
| Rate-limit handling | `src/api/http_client.py:43-48 _respect_rate_limit`, `:54-66 _retry_after` (429 `Retry-After`) | `tests/test_http_client.py:30,37,62` | Yes |
| Pagination | `src/api/sources/vietlott_official.py:100-113 iter_raw_pages` | `tests/test_sources.py:82,90,98` | Yes |
| Schema validation | `src/api/sources/vietlott_official.py` (`ParseError` in `parse`/`_parse_row`) + `src/validation/rules.py validate_record/validate_dataset` | `tests/test_sources.py:44,49`, all of `tests/test_validation.py` | Yes |
| Structured logs | `src/logging_utils.py JsonFormatter/configure_logging`; `log.info(..., extra={...})` in `http_client.py` and `loader.py` | none | **No — flagged** |
| Idempotent incremental loads | `src/ingestion/loader.py run_ingestion` (`stop_at` in lines 96-97; content-key comparison lines 120-135) | `tests/test_ingestion.py:45,55,91` + real incremental run in `ingestion_log.csv` (0 inserted, 8 skipped) | Yes |
| Raw archival (immutable, checksummed, preserves source/retrieved_at/version) | `src/ingestion/raw_archive.py RawArchive.write` (`"xb"` exclusive create, sha256 manifest) | `tests/test_ingestion.py:64 test_raw_is_archived_with_checksums`, `:74 test_raw_archive_never_overwrites` | Yes |

**Finding (medium, non-blocking):** `src/logging_utils.py` (the `JsonFormatter` and `configure_logging`) has no dedicated test. I independently exercised it (direct `log.info` call) and confirmed it produces correctly-shaped JSON and appends to the target file, so the mechanism itself is not broken. However `data/logs/app.log` is 0 bytes in this environment despite 3 ingestion CLI runs having executed and logged via `log.info`, which I cannot fully explain (possibly the process/session that ran ingestion did not flush/persist the file handler, or the file was reset by the environment between runs). This does not affect data correctness — `ingestion_log.csv` and `quality_log.csv` (the authoritative structured logs used elsewhere in this report) are complete and correct — but the "structured logs" API rule has no regression test guarding it. Required fix: add a test asserting `configure_logging` + `log.info(..., extra=...)` produces valid JSON-lines output (e.g. via `caplog` or a temp file), and investigate why `app.log` ended up empty after real ingestion runs.

## 9. `python -m pytest`

Result: **59 passed, 0 failed**, 0.80s.

```
...........................................................              [100%]
59 passed in 0.80s
```

---

## Findings

1. **[INFO / no action]** `verify-raw`, `reconcile`, curated-table structural checks, manifest-vs-file agreement, and 7/7 independent spot-checks all pass. Data in `data/curated/fact_draw.csv` is correct against the archived raw pages.
2. **[INFO / no action]** Draw 00944 mirror discrepancy is a genuine upstream data-entry defect in `github_mirror` (mislabelled row, wrong date, missing special number), correctly rejected by `validate_dataset`'s `chronological_order` rule and correctly surfaced by `reconcile` as `only_left`. No `src/` change needed.
3. **[MEDIUM, non-blocking]** No test exists for `src/logging_utils.py` (structured JSON logging), and `data/logs/app.log` is empty despite completed ingestion runs. Required fix: add a logging regression test; data-engineer to investigate the empty `app.log`. This does not block the M1 milestone since the authoritative logs (`ingestion_log.csv`, `quality_log.csv`) are correct and complete, and the logging code was independently verified to function when invoked directly.
4. **[INFO]** `VIETLOTT_655_DRAW_KEY` has a hard-coded fallback default (`"d9f032a7"`, `src/config.py:60`), overridable by env var. This is a public session/draw key scraped from the page, not a credential/API key/token, so it does not violate "never hard-code API keys or tokens" — noting for completeness, no action required.

## Completion format

1. Files changed: none (`src/`, `tests/`, `data/` untouched by this review; only `reports/data_quality_2026-09-24_M1-review.md` was added).
2. Implementation summary: independent QA review of M1 ingestion — ran `verify-raw`, `reconcile`, structural/manifest checks on curated data, independently re-parsed 7 raw pages against `fact_draw.csv`, assessed the draw 00944 mirror defect, mapped each API rule to code + test, ran the full test suite.
3. Tests run: `python -m pytest` (full suite).
4. Results: 59 passed, 0 failed. `verify-raw` clean. `reconcile` clean (only expected 00944 asymmetry). All curated structural checks pass. Manifest agrees with files. 7/7 spot-checked draws match raw archive exactly.
5. Limitations: did not run any new ingest (per constraint); relied on the pre-existing incremental run in `ingestion_log.csv` for idempotency evidence. Did not independently re-derive `fact_draw_number.csv`/`dim_number.csv` cell-by-cell (only row counts vs. manifest), since the task's structural-check list did not require it.
6. Next task: data-engineer to add a structured-logging regression test and investigate the empty `app.log`; Project Lead to mark M1 DONE per `docs/TASKBOARD.md` given this PASSED verdict, and proceed with M2-T2/M2-T3.
