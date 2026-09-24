# SKILL: POWER 6/55 STATISTICAL RESEARCH

## Purpose
Reusable agent skill for building a disciplined historical lottery-data research pipeline.

## Operating modes

### Mode A — Data Engineering
Use when:
- collecting data
- integrating API sources
- validating schema
- normalizing records
- scheduling ingestion

Workflow:
SOURCE -> RAW -> VALIDATE -> STAGING -> CURATED -> QUALITY REPORT

### Mode B — Statistical Analysis
Use when:
- profiling data
- checking distributions
- testing independence
- investigating stability

Workflow:
QUESTION -> NULL HYPOTHESIS -> TEST -> EFFECT SIZE -> ROBUSTNESS -> INTERPRETATION

### Mode C — Model Research
Use when:
- creating baselines
- adding features
- comparing models
- running backtests

Workflow:
TARGET -> FEATURES -> TEMPORAL SPLIT -> BASELINE -> MODEL -> TEST -> COMPARE -> REPORT

## Required algorithm families

### 1. Combinatorial / validation logic
- validate six distinct main numbers in 1..55
- canonicalize each draw into ascending main-number representation where source semantics allow
- map long format with one row per drawn number

### 2. Frequency / distribution
- empirical frequency
- relative frequency
- expected frequency under a simple theoretical baseline
- chi-square goodness-of-fit when assumptions are suitable
- standardized residuals

### 3. Dependence diagnostics
- lagged indicators
- runs-style tests
- autocorrelation diagnostics on aggregate series
- permutation/randomization tests when appropriate

### 4. Temporal stability
- rolling windows
- expanding windows
- calendar-period comparison
- change-point/anomaly diagnostics when justified

### 5. Feature engineering
Allowed features must be computable using information available strictly before the target/evaluation timestamp.
Examples:
- historical counts
- rolling counts
- rolling sums
- inter-arrival gaps
- calendar features

### 6. Backtesting
Primary patterns:
- expanding window
- rolling window
- train/validation/test
- optional gap between train and validation/test when domain logic requires it

Never leak future observations into preprocessing or feature creation.

### 7. Model evaluation
Probabilistic:
- log loss
- Brier score
- calibration

Continuous aggregate targets:
- MAE
- RMSE

Always compare with a baseline.

## API engineering skill

Implement an adapter interface:

```python
class DrawSource:
    def fetch(self, start_date, end_date):
        ...
```

The concrete source is replaceable.

Required controls:
- request timeout
- bounded retries
- exponential backoff
- rate-limit handling
- pagination
- parser validation
- structured logging
- idempotency
- raw response archival

Never put credentials directly in source code.

## Research integrity rules

1. Do not turn historical patterns into claims of guaranteed future prediction.
2. Do not use test data for model selection.
3. Do not report only the best backtest window.
4. Report failures and negative results.
5. Separate:
   - observed fact
   - statistical evidence
   - interpretation
   - limitation
6. Prefer the simplest adequate model.
7. Every experiment has an ID and dataset version.
8. Every production result must be reproducible.

## Suggested implementation order

1. source adapter
2. raw archive
3. parser
4. validation
5. curated dataset
6. EDA
7. statistical test module
8. baseline module
9. temporal splitter
10. evaluation module
11. experiment registry
12. reporting/dashboard
13. scheduler/monitoring

## Reference patterns used

The skill is informed by established open-source patterns:
- scikit-learn model-splitting architecture for clean train/test separation.
- SciPy statistics APIs for hypothesis testing.
- vectorbt-style rolling/expanding split concepts for time-aware evaluation.
- Lottery-BestCombination was inspected only as a domain-relevant reference for historical lottery analysis; its betting-oriented methodology is NOT adopted into this skill.

## Task completion report

At the end of each implementation task, report:
- changed files
- what was implemented
- tests run
- test status
- known limitations
- next dependency/task
