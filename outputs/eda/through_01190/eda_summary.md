# EDA summary

## Parameters
source_dataset_version: ds_cbdf3834368e
analysis_version: ds_16b6be697acb
through_draw: 01190
n_draws: 1190
override_ref: 
spec_version: 1.2.1
spec_sha256: e41f63ef47ea066f14e5effb41bf9f4b7ebd8d79641604b69a10323837e09474
windows: 50,100,200
n_blocks: 5
mc_reps: 10000
seed: 20260924

## Draw-level metrics
sum: observed mean 170.0538 (null 168); 0 of 20 cells outside the pointwise band (0.8409 expected).
min: observed mean 8.1765 (null 8); 0 of 26 cells outside the pointwise band (1.0098 expected).
max: observed mean 47.9689 (null 48); 0 of 26 cells outside the pointwise band (1.0098 expected).
range: observed mean 39.7924 (null 40); 1 of 36 cells outside the pointwise band (1.4126 expected).
odd_count: observed mean 3.0874 (null 3.0545); 1 of 7 cells outside the pointwise band (0.3005 expected).
low_count: observed mean 2.8916 (null 2.9455); 1 of 7 cells outside the pointwise band (0.3005 expected).
consecutive_pairs: observed mean 0.5336 (null 0.5455); 1 of 4 cells outside the pointwise band (0.1717 expected).
within_draw_gap: observed mean 7.9585 (null 8); 2 of 34 cells outside the pointwise band (1.4515 expected).
within_draw_max_gap: observed mean 17.3748 (null 17.6032); 4 of 30 cells outside the pointwise band (1.1429 expected).
within_draw_min_gap: observed mean 2.0798 (null 2.0456); 0 of 7 cells outside the pointwise band (0.3035 expected).

## Number-level metrics
main: 2 of 55 numbers outside the pointwise band (2.4962 expected; nominal 2.75); 0 outside the simultaneous band.
special: 1 of 55 numbers outside the pointwise band (2.0956 expected; nominal 2.75); 0 outside the simultaneous band.
W=50: 13 of 1141 windows above and 0 below the pointwise envelope (≈2.5% expected on each side; windows overlap).
W=100: 6 of 1091 windows above and 0 below the pointwise envelope (≈2.5% expected on each side; windows overlap).
W=200: 0 of 991 windows above and 0 below the pointwise envelope (≈2.5% expected on each side; windows overlap).

## Pair-level metrics
64 of 1,485 pairs outside the pointwise band (60.4 expected; nominal 74); 0 outside the simultaneous band.
0 of 20 block pairs with r outside the MC 95% interval (1 expected).

## Limitations
- There is no inference here; M4 decides.
- Pointwise bands and the envelope are exceeded about 5% of the time by chance.
- Rolling windows overlap and are autocorrelated.
- Inter-arrival gaps are memoryless under the null.
- The drawing order is hidden.
- MC references carry Monte Carlo error.
- 2017 and 2025 are partial years.
- The M4 confirmatory tests use the same draws.
- Nothing here is evidence that future draws can be forecast.
