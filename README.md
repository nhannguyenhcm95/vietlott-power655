# Power 6/55 — historical data research

Reproducible data pipeline and statistical research on Vietlott Power 6/55 draw results.
Scope and rules: [agent.md](agent.md), [PROJECT_STEPS.md](PROJECT_STEPS.md), [docs/SPECIFICATION.md](docs/SPECIFICATION.md).
This project does **not** produce number selections, betting recommendations or purchase automation.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # optional, defaults work
python -m pytest
```

## Data pipeline

```
SOURCE -> data/raw (immutable, sha256 manifest) -> VALIDATE -> data/staging/<source> -> data/curated
```

```bash
python -m src.cli ingest --source vietlott_official --full   # whole history (~176 requests)
python -m src.cli ingest --source vietlott_official          # incremental: only new draws
python -m src.cli ingest --source github_mirror --full       # secondary source
python -m src.cli reconcile --left vietlott_official --right github_mirror
python -m src.cli curate --source vietlott_official          # rebuild curated tables
python -m src.cli verify-raw                                 # re-check raw checksums
python -m src.cli quality-report --as-of 2026-09-24T21:00:00+07:00  # deterministic quality report
```

### Data quality report (M2-T2)

`python -m src.cli quality-report [--as-of ISO8601] [--out-dir reports] [--known-issues configs/known_issues.json]`
is offline and deterministic: it reads curated + staging + raw + logs + `configs/known_issues.json` and writes
`reports/data_quality_<date>.md`, `data_quality_<date>.json` and a `data_quality_latest.json` copy, with one
overall status. `--as-of` must include a UTC offset. Exit codes: `0` PASS, `10` WARN, `30` FAIL, `50` internal
error. Details: `docs/design/M2-data-quality-and-refresh.md` §1, `docs/SPECIFICATION.md` §4a.

Known issues (`configs/known_issues.json`) let a reviewed finding be marked accepted without hiding it from the
report. Add a new entry as **proposed** (leave `approved_by`/`approved_on`/`approval_ref` empty); it is only
approved once a human records the decision under `docs/TASKBOARD.md` "Decisions", and an agent copies those exact
values into the entry with `approval_ref` naming that decision. Some rules (schema, lineage, raw checksums,
`frozen_prefix`, `retrieved_after_draw`, official duplicates) can never be accepted.

### Scheduled refresh (M2-T3)

`python -m src.cli refresh [--lock-timeout-minutes 120] [--as-of ISO8601]` runs, in order: official incremental
ingest, mirror incremental ingest (always attempted, even if official failed), reconcile, curate (blocked by an
unaccepted mismatch on a not-yet-published draw, or by a `frozen_prefix` violation), and the quality report.
It is idempotent: a rerun with no new data leaves the curated manifest bytes and `dataset_version` unchanged.

Exit codes: `0` PASS · `10` WARN · `30` FAIL (report FAIL, the official source failed/returned nothing, or curate
was blocked/failed) · `40` LOCKED (another `refresh`/`ingest`/`curate` is running) · `50` INTERNAL (an uncaught
error, or no report was written). `ingest` and `curate` take the same run lock and also exit 40 if `refresh` is
running.

`python -m src.cli status` prints the last refresh (and its age), consecutive non-zero exits, the latest report's
`overall_status`, the next scheduled draw and whether `data/logs/ALERT.txt` exists. It exits `10` if the last
refresh is missing, older than 4 days, did not exit 0, or `ALERT.txt` exists; otherwise `0`.

`data/logs/ALERT.txt` is the at-a-glance failure signal: it holds `started, not finished <refresh_id> ...` while a
refresh is in progress (so a crash or a killed process leaves it in that state), the final cause and report path
after any non-zero exit, or is absent after a clean (exit 0) run. `data/logs/refresh_log.csv` keeps the full
history, including `report_sha256` (the JSON report's checksum, so a report can be tied back to the run that
produced it).

**The human, never an agent, runs the registration scripts** (they create/remove a Windows Task Scheduler entry):

```powershell
# from the project root, in an elevated or normal PowerShell prompt as appropriate
scripts\register_refresh_task.ps1 [-PythonExe <path>] [-DrawRunTime 20:00] [-RetryTime 08:30] [-Replace] [-Force]
scripts\unregister_refresh_task.ps1
```

This registers `\Power655\Refresh`: a Tue/Thu/Sat 20:00 run (draw night) and a Wed/Fri/Sun 08:30 retry (safe,
because `refresh` is idempotent). It refuses a WindowsApps python alias and a non-`+07:00` machine timezone unless
`-Force` is given, and refuses to overwrite an existing task unless `-Replace` is given.

**Adding a known issue**: add the entry to `configs/known_issues.json` with `approved_by`/`approved_on`/
`approval_ref` left empty (proposed; visible in the report but not accepted). It is approved only once a human
records the decision under `docs/TASKBOARD.md` "Decisions" section, and an agent then copies those exact values in,
with `approval_ref` naming that decision (never invented). Some rules can never be accepted (schema, lineage, raw
checksums, `frozen_prefix`, `retrieved_after_draw`, official duplicates); see
`docs/design/M2-data-quality-and-refresh.md` §1.4–1.5.

### Sources (`src/api/sources/`)

| name | endpoint | role |
|---|---|---|
| `vietlott_official` | vietlott.vn AjaxPro `Game655CompareWebPart.ServerSideDrawResult`, 8 draws/page, newest first | primary |
| `github_mirror` | `vietvudanh/vietlott-data` `power655.jsonl` (daily scrape of vietlott.vn) | cross-check |

Add a source by subclassing `DrawSource` (`iter_raw_pages` + pure `parse`) and registering it in `src/api/registry.py`.

### Outputs

| path | content |
|---|---|
| `data/raw/<source>/<run_id>/` | raw responses + `manifest.jsonl` (url, params, retrieved_at, sha256) |
| `data/staging/<source>/draws.csv` | validated draws per source, main numbers ascending |
| `data/curated/fact_draw.csv` | one row per draw, with `dataset_version` |
| `data/curated/fact_draw_number.csv` | long format, positions 1–6 main, 7 special |
| `data/curated/dim_number.csv` | 1..55 with parity / band (low ≤ 27) / decade group |
| `data/curated/dataset_manifest.json` | version, coverage, row counts |
| `data/logs/ingestion_log.csv`, `quality_log.csv`, `app.log` | run log, rule violations, JSON logs |
| `reports/data_quality_<date>.md` / `.json`, `data_quality_latest.json` | deterministic data quality report |
| `data/logs/refresh_log.csv`, `data/logs/ALERT.txt` | refresh run history (with `report_sha256`), current alert state |

`dataset_version` is a hash of draw content only, so the same data always has the same version.

## Status

- M0 specification: done ([docs/SPECIFICATION.md](docs/SPECIFICATION.md))
- M1 ingestion: done
- M2 data quality: validation, quality log, curated layer, `quality-report` (M2-T2) and `refresh`/`status` (M2-T3) done
- M3+ : not started
