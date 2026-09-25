# M4 confirmatory summary

## Parameters
source_dataset_version: ds_aa8808303afa
analysis_version: ds_16b6be697acb
frozen_dataset_version: ds_cbdf3834368e
frozen_prefix_status: source_dataset_version is ds_aa8808303afa, differing from the frozen split ds_cbdf3834368e because later live draws were ingested. The frozen_prefix rule for draws <=01401 is verified by the M2 quality report, not recomputed here, because the M4 loader is ceiling-limited to draws <=01190. analysis_version ds_16b6be697acb covers only draws <=01190, which the ceiling guarantees.
through_draw: 01190
n_draws: 1190
spec_version: 1.2.1
spec_sha256: e41f63ef47ea066f14e5effb41bf9f4b7ebd8d79641604b69a10323837e09474
code_version: 2fb9ee8b7563a609382add947396f4e059652c81
seed: 20260924
R: 10000
streams: {'fresh': 101, 'perm': 102}
runtime_seconds: 49.2
escalated: False

## OBSERVED
Draw-level, number-level and year/window statistics were computed on the 00001-01190 analysis draws, as defined in SPECIFICATION section 6.2 (C1-C13). Observed effect sizes, per test:
C1: dispersion ratio 0.9279 (null approx 1); max|z| across numbers 2.1556.
C2: ratio 0.9935 (null approx 1).
C3: overlap minus null, min -0.0429 to max 0.0259 across lags 1-10 (per-lag values and CIs in the follow-up table).
C4: overlap minus the PERM mean, min -0.0424 to max 0.0264 across lags 1-10 (per-lag values in the follow-up table).
C5: max|r_h| across lags 1-10 is 0.0395 (per-lag CI half-width 0.0568).
C6: 596 runs (mu=584.50, n_plus=636, n_minus=539, ties dropped=15).
C7: Cramer's V 0.0796 (PERM mean 0.0828, PERM 95% quantile 0.0875).
C8: V_roll 0.2266 (PERM mean 0.2340).
C9: observed mean sum minus 168 is 2.0538 (95% CI 167.9209 to 172.1867).
C10: observed mean range minus 40 is -0.2076 (95% CI 39.3039 to 40.2810).
C11: w=0.0997; observed mean minus expected 0.0328.
C12: w=0.0943; observed mean minus expected -0.0539.
C13: w=0.0892; observed mean minus expected -0.0118.

## STATISTICAL EVIDENCE
C1 (H1): n 1190, N 7140, statistic 45.4650, replicate mean 48.9492, null FRESH, R 10000, p_sim 0.62064, p_holm 1.00000, decision not_reject.
C2 (H2): n 1190, N 7140, statistic 53.6471, replicate mean 53.9914, null FRESH, R 10000, p_sim 0.48615, p_holm 1.00000, decision not_reject.
C3 (H3): n 1190, N 7140, statistic 12.0408, replicate mean 9.8989, null FRESH, R 10000, p_sim 0.27027, p_holm 1.00000, decision not_reject.
C4 (H3): n 1190, N 7140, statistic 11.8991, replicate mean 10.0000, null PERM, R 10000, p_sim 0.29187, p_holm 1.00000, decision not_reject.
C5 (H3): n 1190, N 7140, statistic 7.1205, replicate mean 10.0131, null FRESH, R 10000, p_sim 0.71403, p_holm 1.00000, decision not_reject.
C6 (H3): n 1190, N 7140, statistic 11.5038, replicate mean 13.5813, null FRESH, R 10000, p_sim 0.49895, p_holm 1.00000, decision not_reject.
C7 (H4): n 1190, N 7140, statistic 362.3395, replicate mean 392.2308, null PERM, R 10000, p_sim 0.86991, p_holm 1.00000, decision not_reject.
C8 (H4): n 1190, N 7140, statistic 52.3523, replicate mean 56.0097, null PERM, R 10000, p_sim 0.71933, p_holm 1.00000, decision not_reject.
C9 (H5): n 1190, N 7140, statistic 0.0426, replicate mean 0.0236, null FRESH, R 10000, p_sim 0.02030, p_holm 0.26387, decision not_reject.
C10 (H5): n 1190, N 7140, statistic 0.0154, replicate mean 0.0219, null FRESH, R 10000, p_sim 0.80392, p_holm 1.00000, decision not_reject.
C11 (H5): n 1190, N 7140, statistic 11.8282, replicate mean 6.0481, null FRESH, R 10000, p_sim 0.06999, p_holm 0.76992, decision not_reject.
C12 (H5): n 1190, N 7140, statistic 10.5807, replicate mean 5.9741, null FRESH, R 10000, p_sim 0.09629, p_holm 0.96290, decision not_reject.
C13 (H5): n 1190, N 7140, statistic 9.4760, replicate mean 3.0037, null FRESH, R 10000, p_sim 0.02320, p_holm 0.27837, decision not_reject.

## INTERPRETATION
No confirmatory evidence against H1-H5 on 00001-01190 at family-wise error rate 0.05 (Holm).
Non-rejection is not proof that the null hypotheses hold.
The smallest raw p in the family is 0.020 (C9); its Holm-adjusted p is 0.264; it does not survive the pre-registered multiplicity control. Under 13 tests in the family, a raw p this small occurring somewhere by chance alone has probability approximately 0.23.

## LIMITATION
- This is a confirmatory run of pre-registered null hypotheses; a non-rejection is reported plainly and is not evidence that future draws can be forecast.
- No individual number or pair is named. Follow-up CSVs are always written for every parent test (not only when it rejects); each row carries an interpretation label, and only rows whose parent test rejected are interpreted, sorted by number, with no ordered list of numbers.
- Exploratory items (section 6.4) are unadjusted and are never a claim on their own.
- The MC escalation rerun (R=100000) applies only when triggered; both runs are reported when it is, and the R=100000 decisions are then final.
- This run uses draws 00001-01190 only; the replication on 01191-01401 and 00001-01401 happens once, after the M6 lock, and never changes this result.
- Nothing here is evidence that future draws can be forecast, and it never orders or selects numbers.
