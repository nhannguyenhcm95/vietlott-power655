# Data quality report — 2026-09-25

Overall status: **PASS** (as of 2026-09-25T09:29:49+07:00, run_context=refresh)

Summary: missing=0 duplicate=0 invalid_ranges=0 schema_errors=0 ingestion_failures=0 accepted=4 proposed=0

Dataset: ds_aa8808303afa — 1402 draws, 00001 (2017-08-01) .. 01402 (2026-09-24)

## known_issues.file — PASS — 0 accepted, 0 proposed

No findings.

## curated.schema — PASS — 0 accepted, 0 proposed

No findings.

## curated.lineage — PASS — 0 accepted, 0 proposed

No findings.

## curated.missing — PASS — 0 accepted, 0 proposed

No findings.

## curated.duplicates — PASS — 0 accepted, 0 proposed

No findings.

## curated.ranges — PASS — 0 accepted, 0 proposed

No findings.

## coverage.gaps — PASS — 0 accepted, 0 proposed

| source | draw_id | draw_date | rule | level | accepted | detail |
|---|---|---|---|---|---|---|
| vietlott_official |  | 2018-02-17 | draw_cadence | INFO | False | gap from 2018-02-13 to 2018-02-17 skips at least one scheduled draw date |
| vietlott_official |  | 2019-02-07 | draw_cadence | INFO | False | gap from 2019-02-02 to 2019-02-07 skips at least one scheduled draw date |
| vietlott_official |  | 2020-01-28 | draw_cadence | INFO | False | gap from 2020-01-23 to 2020-01-28 skips at least one scheduled draw date |
| vietlott_official |  | 2020-04-25 | draw_cadence | INFO | False | gap from 2020-03-31 to 2020-04-25 skips at least one scheduled draw date |
| vietlott_official |  | 2020-08-29 | draw_cadence | INFO | False | gap from 2020-08-25 to 2020-08-29 skips at least one scheduled draw date |
| vietlott_official |  | 2021-02-13 | draw_cadence | INFO | False | gap from 2021-02-09 to 2021-02-13 skips at least one scheduled draw date |
| vietlott_official |  | 2021-08-19 | draw_cadence | INFO | False | gap from 2021-07-22 to 2021-08-19 skips at least one scheduled draw date |
| vietlott_official |  | 2022-02-03 | draw_cadence | INFO | False | gap from 2022-01-29 to 2022-02-03 skips at least one scheduled draw date |
| vietlott_official |  | 2023-01-24 | draw_cadence | INFO | False | gap from 2023-01-19 to 2023-01-24 skips at least one scheduled draw date |
| vietlott_official |  | 2024-02-13 | draw_cadence | INFO | False | gap from 2024-02-08 to 2024-02-13 skips at least one scheduled draw date |
| vietlott_official |  | 2025-01-30 | draw_cadence | INFO | False | gap from 2025-01-25 to 2025-01-30 skips at least one scheduled draw date |
| vietlott_official |  | 2026-02-19 | draw_cadence | INFO | False | gap from 2026-02-14 to 2026-02-19 skips at least one scheduled draw date |

## coverage.freshness — PASS — 0 accepted, 0 proposed

| source | draw_id | draw_date | rule | level | accepted | detail |
|---|---|---|---|---|---|---|
| vietlott_official |  | 2026-09-26 | freshness_pending | INFO | False | draw scheduled for 2026-09-26 has not yet reached its 21:00 ICT publication deadline |

## staging.schema — PASS — 0 accepted, 0 proposed

No findings.

## ingestion.runs — PASS — 0 accepted, 0 proposed

| source | draw_id | draw_date | rule | level | accepted | detail |
|---|---|---|---|---|---|---|
| github_mirror |  |  | run_partial | INFO | False | latest github_mirror run 20260925T022951Z_bc9ed3 is partial |

## quality_log.open — PASS — 3 accepted, 0 proposed

| source | draw_id | draw_date | rule | level | accepted | detail |
|---|---|---|---|---|---|---|
| github_mirror | 00944 |  | chronological_order | WARN | True | open: chronological_order on draw 00944 (draw 00944 dated 2022-09-23 not after draw 00943 dated 2023-10-12) |
| github_mirror | 00944 |  | chronological_order | WARN | True | open: chronological_order on draw 00944 (draw 00944 dated 2022-09-23 not after draw 00943 dated 2023-10-12) |
| github_mirror | 00944 |  | chronological_order | WARN | True | open: chronological_order on draw 00944 (draw 00944 dated 2022-09-23 not after draw 00943 dated 2023-10-12) |

## reconcile.sources — PASS — 1 accepted, 0 proposed

| source | draw_id | draw_date | rule | level | accepted | detail |
|---|---|---|---|---|---|---|
| github_mirror | 00944 |  | reconcile.only_left | WARN | True | draw 00944 is in vietlott_official but not in github_mirror |

## raw.checksums — PASS — 0 accepted, 0 proposed

No findings.

## refresh.history — PASS — 0 accepted, 0 proposed

| source | draw_id | draw_date | rule | level | accepted | detail |
|---|---|---|---|---|---|---|
| system |  |  | refresh_history | INFO | False | refresh 20260924T050212Z_9ceb4f: exit=0 status=PASS |

## Ingestion runs (last 20)

| run_id | source | mode | status | received | inserted | skipped | rejected |
|---|---|---|---|---|---|---|---|
| 20260924T030626Z_00d6df | vietlott_official | full | success | 1401 | 1401 | 0 | 0 |
| 20260924T031012Z_13d471 | github_mirror | full | partial | 1401 | 1400 | 1 | 1 |
| 20260924T031030Z_82a958 | vietlott_official | incremental | success | 8 | 0 | 8 | 0 |
| 20260924T050212Z_85fdba | vietlott_official | incremental | success | 8 | 0 | 8 | 0 |
| 20260924T050219Z_4ce417 | github_mirror | incremental | partial | 1401 | 0 | 1401 | 1 |
| 20260925T022949Z_4bf63c | vietlott_official | incremental | success | 8 | 1 | 7 | 0 |
| 20260925T022951Z_bc9ed3 | github_mirror | incremental | partial | 1402 | 1 | 1401 | 1 |

## Known issues: accepted / proposed / expired

| id | state | matched |
|---|---|---|
| KI-001 | active | {'chronological_order': 3, 'reconcile.only_left': 1} |

