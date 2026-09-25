# M5 EXP-001 summary

## Parameters
experiment_id: EXP-001
source_dataset_version: ds_aa8808303afa
analysis_version: ds_16b6be697acb
spec_version: 1.2.1
spec_sha256: e41f63ef47ea066f14e5effb41bf9f4b7ebd8d79641604b69a10323837e09474
code_version: 1465af7161a9053ca7df7d4d04572789911a5480
seed: 20260924
runtime_seconds: 440.8
provisional: False
selected_w: 200

## OBSERVED
Per-fold mean log loss and Brier score, every configuration (folds 1-9 are reported but not used for selection):
fold_01 (n=50): B0 ll=0.34461 brier=0.09719; B1 ll=0.34494 brier=0.09727; B2_W50 ll=0.35381 brier=0.09885; B2_W100 ll=0.35025 brier=0.09820; B2_W200 ll=0.34724 brier=0.09771
fold_02 (n=50): B0 ll=0.34461 brier=0.09719; B1 ll=0.34658 brier=0.09755; B2_W50 ll=0.34966 brier=0.09806; B2_W100 ll=0.34934 brier=0.09806; B2_W200 ll=0.34803 brier=0.09781
fold_03 (n=50): B0 ll=0.34461 brier=0.09719; B1 ll=0.34525 brier=0.09731; B2_W50 ll=0.35331 brier=0.09874; B2_W100 ll=0.35048 brier=0.09825; B2_W200 ll=0.34793 brier=0.09779
fold_04 (n=50): B0 ll=0.34461 brier=0.09719; B1 ll=0.34556 brier=0.09738; B2_W50 ll=0.34891 brier=0.09793; B2_W100 ll=0.34689 brier=0.09760; B2_W200 ll=0.34679 brier=0.09762
fold_05 (n=50): B0 ll=0.34461 brier=0.09719; B1 ll=0.34496 brier=0.09725; B2_W50 ll=0.35703 brier=0.09930; B2_W100 ll=0.35046 brier=0.09827; B2_W200 ll=0.34569 brier=0.09737
fold_06 (n=50): B0 ll=0.34461 brier=0.09719; B1 ll=0.34547 brier=0.09736; B2_W50 ll=0.35113 brier=0.09837; B2_W100 ll=0.35023 brier=0.09828; B2_W200 ll=0.34947 brier=0.09812
fold_07 (n=50): B0 ll=0.34461 brier=0.09719; B1 ll=0.34492 brier=0.09725; B2_W50 ll=0.35044 brier=0.09822; B2_W100 ll=0.34781 brier=0.09781; B2_W200 ll=0.34760 brier=0.09775
fold_08 (n=50): B0 ll=0.34461 brier=0.09719; B1 ll=0.34568 brier=0.09739; B2_W50 ll=0.35417 brier=0.09879; B2_W100 ll=0.35090 brier=0.09830; B2_W200 ll=0.34751 brier=0.09773
fold_09 (n=50): B0 ll=0.34461 brier=0.09719; B1 ll=0.34422 brier=0.09711; B2_W50 ll=0.35097 brier=0.09834; B2_W100 ll=0.34786 brier=0.09780; B2_W200 ll=0.34529 brier=0.09731
fold_10 (n=50): B0 ll=0.34461 brier=0.09719; B1 ll=0.34612 brier=0.09748; B2_W50 ll=0.35534 brier=0.09903; B2_W100 ll=0.35096 brier=0.09841; B2_W200 ll=0.34883 brier=0.09794
fold_11 (n=50): B0 ll=0.34461 brier=0.09719; B1 ll=0.34480 brier=0.09723; B2_W50 ll=0.35235 brier=0.09857; B2_W100 ll=0.34750 brier=0.09772; B2_W200 ll=0.34486 brier=0.09721
fold_12 (n=50): B0 ll=0.34461 brier=0.09719; B1 ll=0.34352 brier=0.09698; B2_W50 ll=0.35171 brier=0.09836; B2_W100 ll=0.34851 brier=0.09796; B2_W200 ll=0.34595 brier=0.09749
fold_13 (n=50): B0 ll=0.34461 brier=0.09719; B1 ll=0.34444 brier=0.09715; B2_W50 ll=0.35093 brier=0.09821; B2_W100 ll=0.34790 brier=0.09768; B2_W200 ll=0.34675 brier=0.09757
fold_14 (n=40): B0 ll=0.34461 brier=0.09719; B1 ll=0.34528 brier=0.09732; B2_W50 ll=0.35279 brier=0.09866; B2_W100 ll=0.34930 brier=0.09809; B2_W200 ll=0.34830 brier=0.09785

## EVIDENCE
Pooled delta vs B0 with 95% bootstrap CIs, descriptive, development data:
dev_pooled B1: delta LL 0.00051 (95% CI 0.00019 to 0.00084).
dev_pooled B2_W200: delta LL 0.00253 (95% CI 0.00179 to 0.00329).
validation B1: delta LL -0.00013 (95% CI -0.00061 to 0.00036).
validation B2_W200: delta LL 0.00170 (95% CI 0.00027 to 0.00312).

## INTERPRETATION
Under the null, every B1/B2 configuration is expected to score slightly worse than B0, and B1 is expected to be the closest; a realised delta below 0 on development data is not evidence against the null (section 9). Validation scores are selection-biased/optimistic and validation-exposed (section 8); only M6 can support an H6 claim.
W=50: mean validation log loss 0.352010, L_W - L* = 5.70e-03, in_tie_set=False, selected=False.
W=100: mean validation log loss 0.348158, L_W - L* = 1.85e-03, in_tie_set=False, selected=False.
W=200: mean validation log loss 0.346309, L_W - L* = 0.00e+00, in_tie_set=True, selected=True.
Selected W* = 200 (SPECIFICATION section 7 rule, tie measured against the minimum only).

## LIMITATION
- Every development draw (00001-01190) was already seen descriptively in M3 and M4, so validation is exposed.
- LL and Brier assess marginals only. Within-draw dependence is not scored, and B1/B2 have no set-level score.
- Per-fold CIs rest on 4-5 blocks of length 10, so they are very rough and descriptive.
- Fold scores for B0-B2 come from one continuous scored series, then split by fold. They are not independent replications.
- Only M6 (01191-01401, run once) can decide H6.
