# Weak-label pipeline review status — round 2.6

**Weak behavioural proxies, not measured emotions. Both supplied round-2.5
train outcome gates fail. Revised real-data LF accuracies and performance are
unmeasured; retain the failure banner.**

## Read-only evidence from the supplied 196-player run

The saved exports contain 36,287 distinct games and 36,401 player-game rows, with 22,316 by_player train
rows and 25,403 by_time train rows. Diagnostics read selected Parquet columns
and existing manifests only; no pipeline command ran on real data and no saved
output was rewritten. No identifiers are reproduced here.

| Split / LF | Train votes | Rows conflicting with any NOT_TILT LF | normal_accuracy | rest_and_recover | calm_play | expected_loss |
|---|---:|---:|---:|---:|---:|---:|
| by_player / abandon | 232 | 89 | 63 | 19 | 19 | 5 |
| by_player / early_resign | 155 | 48 | 44 | 6 | 0 | 1 |
| by_time / abandon | 295 | 107 | 70 | 29 | 22 | 5 |
| by_time / early_resign | 208 | 64 | 58 | 8 | 0 | 4 |

Pair counts overlap. These are **train-only** counts, unlike the reviewer's
all-partition counts. In by_player abandonment/normal-accuracy conflicts, median
own move count is 23 and median CPL z is −0.387. Abandonment/calm-play conflicts
have median own move count 2, zero adverse events and median accuracy 93.4.
Early-resign/normal-accuracy conflicts have median own move count 16 and CPL z
−0.444. High average accuracy before an abrupt ending does not negate that ending;
a normal next game after a break also cannot refute an acute current event.
Expected-loss additionally mistakes opponent strength for evidence about the
ending. The definitions overlapped, collapsing both positive LFs to the accuracy
floor in the supplied fit.

Both positive LFs are retained. `abandon` now requires a recent adverse event,
final player-view evaluation >−150 cp and no mate score; timeout alone is too
ambiguous. `early_resign` keeps its existing trigger. Broad performance-based
NOT_TILT LFs require ≥40 board plies and an interpretable completion: mate,
stalemate, draw, ordinary time forfeit, or clearly lost resignation. This scopes
negative evidence to meaningful samples and endings; it does not set accuracies
or silence genuine conflicts with deterioration in otherwise completed games.
See WEAK_LABELS.md for exact triggers and alternative explanations. Revised
coverage/informativeness still needs the reviewer's train fit on Colab.

## Audits and estimated exclusions

Every variant now applies both audits on all train rows, including unlabelled
rows. Outcome audit: loss/time-forfeit AUC in either direction, including missing
indicators; >.70 or undefined target AUC excludes. LF-provenance audit: absolute
Spearman ≥.60 against any LF quantity excludes, using observed/imputed values
and missing indicators. LF quantities include current/past/future evidence,
length, source-move summaries, temporal differences, rating and quality signals.
Categorical status uses train-only category indicators. Both audits list removed
features, and the report gives the top 15 LF matches per split. Model selection
checks actual feature membership against both audits; unassessed inputs fail.

A bounded read-only reconstruction (27.5 seconds) estimates the following LF
exclusions on the **old feature values**, identically across the two splits:

| Feature(s) | Strongest matched LF quantity | Absolute rho: by_player / by_time |
|---|---|---:|
| `clock_missing_fraction` (old formula) | own move count | .996 / .996 |
| `phase_opening_fraction` | mean own ply | .900 / .903 |
| `phase_endgame_fraction` | maximum own ply | .848 / .847 |
| `rematch` | opponent-rating availability | .798 / .832 |
| `games_in_session_before` | previous same-session flag | .735 / .758 |
| `style_drift_in_session` | previous same-session flag | 1.000 / 1.000 |
| The 13 history/safe-score columns listed below | LF accuracy-baseline availability | 1.000 / 1.000 |

The 13 columns are `baseline_attack_rate_mad`, `baseline_attack_rate_median`,
`baseline_risk_rate_mad`, `baseline_risk_rate_median`,
`baseline_style_switch_rate_mad`, `baseline_style_switch_rate_median`,
`deviation_attack_rate_z`, `deviation_risk_rate_z`,
`deviation_style_switch_rate_z`, `historical_attack_rate_similar_fraction`,
`historical_risk_rate_similar_fraction`,
`historical_style_switch_rate_similar_fraction`, and
`behavioral_deviation_score_safe`. Their missing indicators reveal availability
of personal quality baselines read by LFs, despite their style-only values.
There is no phase exception; `phase_middlegame_fraction` did not cross the
threshold in this estimate.

The outcome audit removes old `clock_missing_fraction` too: maximum AUC .707
(by_player) and .704 (by_time), against time forfeit. The reconstruction included
available scalar/move/terminal sources and adjacent-game context. Session loss-run
and shrinking-gap magnitudes were unavailable in old exports; overlapping prior
games were conservatively omitted rather than reconstructed. New exports audit
the exact context, so these estimates can miss additional exclusions.

## Clock computation and compatibility

Only `aggregate`'s clock-missingness computation changed in features.py.
Structurally unclocked first own moves and observed zero-time/premove readings
(including zero-increment equal-clock artefacts) are excluded from numerator and
denominator. Missing/invalid telemetry still counts as missing, including NaN.
No eligible intervals yields null. The streaming FrameSink and all other
features.py code, plus engine.py, were verified unchanged against start-of-task
copies.

A separate read-only aggregation of existing move outputs estimates fixed
missingness: train median 0 on both splits, zero in 99.72% / 99.62% of train rows,
and Spearman rho with own move count .0121 / .0120. This verifies removal of the
structural 1/N effect; it does not certify the feature against every LF quantity.
The reviewer must regenerate features and apply both audits to the fixed values.

Weak manifest version is now **3**. Train/evaluate reject earlier weak exports;
evaluate also requires LF audit metadata. Score refuses stale versions and
selected features failing either audit. Future performance audit metadata is
limited to the LF's supported 30-minute evidence horizon. Symmetric EM,
60/20/20 and 70/85 splits/purging, validation calibration and thresholds,
result_only diagnostics, strata metrics and the outcome gate remain intact.

## Gate, verification and remaining work

| Saved train gate | Label vs lost agreement | TILT within losses | TILT within non-losses | Status |
|---|---:|---:|---:|---|
| by_player | .607 | 18.24% | 3.34% | FAILED |
| by_time | .595 | 17.76% | 3.11% | FAILED |

The saved gates fail because non-loss weak-TILT is below 10%. No new LF or
prevalence-targeting threshold was added. The outcome gate and failure banner
are unchanged. A new gate result cannot be claimed before Colab regeneration.

The required test command is `tilt/.venv/bin/python -m pytest -q tilt/tests`.
Tests cover inverse-length exclusion in every variant, train-only auditing,
missingness/category proxies, LF scopes, audit-safe selection, stale versions,
clock edge cases, report removal lists and existing round-2.4–2.5 behavior.
The complete suite passed with **107 tests in 36.20 seconds** on the latest
verification run. Fixtures use temporary synthetic data, tiny trees and one
LSTM epoch. One existing Starlette/AnyIO deprecation warning remains.

No commit was made. No real-data features, weak labels, models or metrics were
regenerated. **Still required on Colab:** regenerate features, weak-label, train
and evaluate, then inspect LF coverage/estimated accuracies, exact audit removals
and both unchanged outcome gates. Human validation remains required regardless
of gate outcome.

## Round 2.6 Colab regeneration (2026-11-14)

Features, weak labels, training and evaluation were regenerated on Colab with the
local pins (xgboost 2.1.4, scikit-learn 1.6.1, lightgbm 4.6.0). Features are
byte-identical to the previous export; weak labels and both audits are identical
to an earlier 2.6 run that used xgboost 3.4.1.

| Train gate | Label vs lost agreement | TILT within losses | TILT within non-losses | Status |
|---|---:|---:|---:|---|
| by_player | .503 | 21.05% | 6.89% | FAILED |
| by_time | .496 | 20.68% | 6.39% | FAILED |

Non-loss weak-TILT rose from about 3% to 6.4–6.9%, still below 10%. Coverage is
28.8% of rows; `calm_play` never votes. Exact audit removals: 19 LF-provenance,
0 outcome. Validation selected `by_player__full__xgboost` (test PR-AUC .509,
cluster CI .420–.615) and `by_time__lf_ablated__random_forest` (.548). The
16-feature `by_player__lf_ablated__xgboost` scores .509. Diagnostic test
baselines: losing_streak .246, class prior .140. The failure banner stays.

Phase-0 audit (read-only) is in `tilt/reports/`. Main findings: the top
feature `phase_middlegame_fraction` equals 1 − opening − endgame and is a
non-monotonic proxy of game length (an LF input) that the Spearman audit cannot
see; the 13 history columns are excluded only through the shared cold-start
missing indicator, which affects 5 labelled train rows.
