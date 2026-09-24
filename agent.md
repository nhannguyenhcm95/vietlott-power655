# AGENT.MD — VIETLOTT POWER 6/55 DATA RESEARCH

## Mission
Build a reproducible historical-data/statistical research project around Power 6/55.

Read `PROJECT_STEPS.md` and `skills/power655-statistical-research/SKILL.md` before implementation.

## Scope boundary
This repository is for data engineering, statistics, research modeling, backtesting, and reporting.

Do not implement:
- betting recommendations
- number-selection recommendations
- betting optimization
- automated ticket purchasing

## First rule
Do NOT start coding a model before the pre-code checklist in PROJECT_STEPS.md is complete.

## Technical priorities
1. Replaceable API/data-source adapter.
2. Immutable raw data.
3. Strong validation.
4. Reproducible transformations.
5. Time-aware evaluation.
6. Experiment tracking.
7. Tests before declaring completion.
8. Documentation alongside code.

## Data rules
Power 6/55 main numbers:
- exactly 6
- integer
- range 1..55
- unique within draw

Preserve:
- source
- retrieval time
- dataset version

## API rules
API adapter must support:
- timeout
- bounded retry
- exponential backoff
- rate-limit handling
- pagination
- schema validation
- structured logs
- idempotent incremental loads

Never hard-code API keys or tokens.

## Leakage prevention
A feature may only use information available before the evaluated draw/time.

For every temporal split:
- preprocessing fit on train only
- feature calculation respects cutoff
- validation/test remain untouched until evaluation

## Modeling rules
Baseline first.

For every experiment record:
- experiment_id
- dataset_version
- feature_version
- model
- parameters
- train period
- validation period
- test period
- metrics
- notes

Do not cherry-pick a convenient test period.

## Testing rules
Required:
- schema tests
- range/uniqueness tests
- ingestion tests with mocked responses
- temporal split tests
- feature cutoff tests
- metric tests

Run the relevant targeted tests and the full suite before marking a milestone complete.

## Git
Use small, descriptive commits.

Examples:
- `feat: add draw source adapter`
- `feat: add schema validation`
- `test: add temporal leakage checks`
- `feat: add statistical tests`
- `docs: update research methodology`

## Completion format
Every task response must state:
1. files changed
2. implementation summary
3. tests run
4. results
5. limitations
6. next task

## Research interpretation
Never state that an observed pattern proves predictability. Distinguish:
- observed pattern
- statistical significance
- effect size
- robustness
- limitation
