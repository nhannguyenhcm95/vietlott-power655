# PROJECT STEPS — VIETLOTT POWER 6/55 DATA RESEARCH

## 1. Project Goal
Build a reproducible data platform/research pipeline around historical Vietlott Power 6/55 draw results.

Primary outcomes:
- Collect draw data through an API or replaceable data-source adapter.
- Validate and version the dataset.
- Explore statistical properties.
- Test distribution, independence and temporal stability.
- Build research baselines and experimental models.
- Evaluate models with leakage-safe temporal backtesting.
- Publish a dashboard/report.

The project does NOT generate betting recommendations, number selections, betting strategies, or automate ticket purchases.

## 2. Project Questions
1. What does the historical distribution of drawn numbers look like?
2. Does observed frequency differ materially from the theoretical baseline?
3. Are consecutive draws statistically distinguishable from an independence baseline?
4. Are there temporal changes or anomalies?
5. Do experimental models outperform simple baselines under strict out-of-sample evaluation?
6. Are apparent patterns stable across time windows?

## 3. Scope
IN:
- Historical Power 6/55 results.
- API/data ingestion.
- Raw/staging/curated layers.
- Data-quality checks.
- EDA.
- Statistical tests.
- Feature engineering for research.
- Baselines.
- ML experiments.
- Temporal backtesting.
- Model evaluation.
- Dashboard/report.
- Scheduling for data refresh.

OUT:
- Selecting numbers to play.
- Ranking numbers for betting.
- Betting optimization.
- Purchase automation.
- Claims of guaranteed prediction.

## 4. API Plan
Create an API adapter instead of coupling the project to one website.

### API Adapter Contract
Inputs:
- start_date
- end_date
- optional page / cursor

Outputs:
- draw_id
- draw_date
- main_numbers[6]
- special_number (nullable)
- source
- retrieved_at

### API Requirements
- timeout
- retry with exponential backoff
- rate-limit handling
- pagination
- schema validation
- response checksum/raw archival where appropriate
- logging
- idempotent ingestion

### API modules
1. Source discovery
2. HTTP client
3. Response parser
4. Schema validator
5. Raw archive writer
6. Deduplication
7. Incremental loader

## 5. Data Model

### fact_draw
draw_id
draw_date
n1..n6
special_number
source
retrieved_at
dataset_version

### fact_draw_number
draw_id
draw_date
position
number
is_special

### dim_number
number
parity
band
decade_group

### ingestion_log
run_id
source
started_at
finished_at
rows_received
rows_inserted
rows_skipped
status
error_message

### quality_log
check_id
run_id
draw_id
rule
status
detail

## 6. Data Quality Rules
- draw_id unique.
- draw_date parseable.
- main numbers integer.
- main numbers in 1..55.
- exactly six main numbers.
- no duplicate main number within a draw.
- draw ordering is chronological.
- no unexpected future-dated rows.
- special number follows the source schema when present.
- ingestion is idempotent.
- raw response is preserved before transformations.

## 7. EDA Plan

### Draw-level
- sum of 6 numbers
- min / max
- range
- odd/even composition
- low/high composition
- consecutive-number count
- gap statistics

### Number-level
- overall frequency
- frequency by year/quarter
- rolling frequency
- inter-arrival gap
- first/last appearance
- cumulative count

### Pair-level
- pair occurrence counts
- co-occurrence matrix
- pair stability across windows

Use these only as descriptive/statistical analyses, not betting recommendations.

## 8. Statistical Test Plan

### Distribution
- chi-square goodness-of-fit where assumptions are appropriate
- confidence intervals
- standardized residuals
- multiple-testing correction where applicable

### Dependence / randomness diagnostics
- lag-based association checks
- runs-style diagnostics
- autocorrelation diagnostics on carefully defined aggregate series
- permutation tests where an exact/randomization null is more appropriate

### Stability
Compare rolling windows and calendar periods using:
- frequency distribution
- summary statistics
- test statistics
- effect sizes
- confidence intervals

Interpret p-values together with effect size and sample size.

## 9. Baseline Plan
Baseline 0 — theoretical/random baseline.
Baseline 1 — simple historical frequency baseline.
Baseline 2 — rolling-window descriptive baseline.

Every advanced experiment must beat the relevant baseline out-of-sample to justify complexity.

## 10. Modeling Plan
Potential experimental families:
- Logistic-style binary formulations for research targets.
- Tree-based models.
- Time-window features.
- Probability calibration.

Before adding a model:
- define target
- define feature timestamp
- define leakage controls
- define train/validation/test periods
- define evaluation metric

Do not use a model merely because it is more complex.

## 11. Backtesting Plan

Use chronological splits.

Example:
TRAIN -> VALIDATION -> TEST

Then rolling/expanding evaluation:
Window 1 -> future test
Window 2 -> future test
Window 3 -> future test

No random shuffle for the main temporal evaluation.

Every feature must satisfy:
feature_time < prediction/evaluation_time

Fit transformations only on training data inside each split.

## 12. Evaluation Plan
For probabilistic outputs:
- log loss
- Brier score
- calibration diagnostics

For aggregate/continuous research targets when applicable:
- MAE
- RMSE

Always report:
- test period
- sample size
- baseline result
- model result
- confidence interval where appropriate
- limitations

## 13. Dashboard Plan

### Page 1 — Overview
- draws
- latest successful ingestion
- date coverage
- quality status

### Page 2 — Data Quality
- missing
- duplicate
- invalid ranges
- schema errors
- ingestion failures

### Page 3 — Distribution
- frequency
- expected vs observed
- distribution diagnostics

### Page 4 — Temporal
- rolling statistics
- stability
- change points/anomalies

### Page 5 — Statistical Tests
- hypothesis
- test
- statistic
- p-value
- effect size
- interpretation

### Page 6 — Model Evaluation
- baseline
- model metrics
- rolling results
- calibration

## 14. Repository Structure

project/
├── agent.md
├── PROJECT_STEPS.md
├── README.md
├── requirements.txt
├── .env.example
├── configs/
├── data/
│   ├── raw/
│   ├── staging/
│   └── curated/
├── src/
│   ├── api/
│   ├── ingestion/
│   ├── validation/
│   ├── transformation/
│   ├── features/
│   ├── statistics/
│   ├── models/
│   ├── evaluation/
│   └── reporting/
├── notebooks/
├── tests/
├── reports/
└── outputs/

## 15. Milestones

M0 — Specification
- research questions
- scope
- schema
- API contract
- acceptance criteria

M1 — API/Data Ingestion
- source adapter
- raw archival
- parser
- incremental ingestion

M2 — Data Quality
- validation
- quality report
- curated dataset

M3 — EDA
- notebooks/scripts
- charts
- summary tables

M4 — Statistical Research
- hypotheses
- tests
- robustness checks

M5 — Baselines
- baseline models
- evaluation framework

M6 — Experimental Modeling
- candidate models
- feature experiments
- rolling backtests

M7 — Dashboard/Report
- dashboard
- methodology
- findings
- limitations

M8 — Productionization
- scheduled refresh
- logging
- monitoring
- regression tests

## 16. Pre-Code Checklist
Do not start modeling code until these are defined:
[ ] API source/adapter strategy
[ ] historical coverage target
[ ] schema
[ ] validation rules
[ ] research hypotheses
[ ] statistical tests
[ ] baseline definitions
[ ] temporal split rules
[ ] evaluation metrics
[ ] repository structure
[ ] Definition of Done
