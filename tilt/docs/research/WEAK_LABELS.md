# Behavioural proxies and the weak-label model (sections 2.4–2.6)

**These are weak behavioural proxies, not measured emotions. No human labels
validate their thresholds, latent LF accuracies, probabilities or scores.**
Weak outputs remain `weak_tilt_prob` and `weak_tilt_label` in separate
`out/weak_*.parquet` files. They never enter `labels/labels.sqlite`.

The supplied round-2.5 run has 196 sampled players. Both saved train outcome
gates fail: non-loss weak-TILT rates are about 3%, below the required 10%.
Round 2.6 fixes clock missingness, adds an LF-provenance proxy audit to every
variant, and narrows conflicting LF scopes. Revised real-data labels and metrics
remain unmeasured; the saved outputs are preserved as evidence. Regenerate
features, weak labels, training and evaluation on Colab. The failure banner stays
until a new run actually passes the unchanged gate.

## Units and scopes

The primary unit is a sampled player–game, predicted at game completion.
Whole-game features are retrospective. Outcomes/status and all LF source families
are excluded from deployable predictors. `--users-file` defines the target
cohort; opponents enter only if independently sampled. The supplied cohort has
196 sampled human accounts, from the October 2026 monthly dump, in 200-point blitz
rating bands from 400 through 3000, excluding bots/ToS-flagged accounts upstream.
Eligibility required at least 12 blitz games in approximately the first 600,000
monthly games. This favours active players and cannot represent all Lichess users.

Every LF declares current, past and future source quantities in `weak_labels.LFS`.
Identifiers and timestamps used to construct context are metadata, never inputs.
Personal baselines are same-speed and strictly prior: conservative game end must
precede current start. Missing required inputs cause abstention. TILT = 1,
NOT_TILT = 0, ABSTAIN = −1; these names denote weak classes only.

| LF | Vote | Scope and exact trigger |
|---|---|---|
| `abandon` | TILT | Current game: loss and status `timeout`, final player-view evaluation >−150 cp, no mate score, and an adverse event within six plies of the final position. Ordinary time forfeit (`outoftime`) and abandonment of a clearly lost position do not fire. Requires behavioural evidence beyond connectivity/status alone. |
| `early_resign` | TILT | Current game: resignation loss, ≤60 board plies, final player-view evaluation >−150 cp, no mate score, and adverse event within six plies of final position. Evaluation includes the opponent's last move. |
| `carryover` | TILT | **Current game**, any result: follows a completed loss in the same session within 0–60 seconds of its conservative end, and current `deviation_mean_cpl_z` ≥1.5. Reads the previous outcome and current play, never next-game play. |
| `session_spiral` | TILT | Current game, any result: ≥3 consecutive completed prior losses in the same session; the last two prior rest gaps followed by the current conservative rest gap are nonnegative and strictly decreasing; current CPL deviation z ≥1.5. No future rating drop or current-result condition. |
| `normal_accuracy` | NOT_TILT | Current game, any result, within the orderly-completion scope below: mean move accuracy ≥prior personal median and absolute current CPL deviation z ≤1. Replaces win-conditioned `accurate_win`. |
| `rest_and_recover` | NOT_TILT | Labels current game, any result within the orderly-completion scope, using aftermath: next game starts 300–1800 seconds after current conservative end and absolute next-game CPL deviation z ≤1. |
| `calm_play` | NOT_TILT | Current game, any result within the orderly-completion scope: zero detected adverse events and mean move accuracy ≥prior personal median. Replaces outcome-conditioned `calm_result`; the name is only a proxy shorthand. |
| `composed_loss` | NOT_TILT | Current resignation loss, ≥80 board plies, clearly lost final position (≤−500 cp or negative mate score), then next game after 300–1800 seconds with absolute CPL deviation z ≤1. |
| `expected_loss` | NOT_TILT | Current loss within the orderly-completion scope: opponent ≥200 rating points stronger, mean accuracy ≥prior median minus 5 accuracy points, absolute current CPL deviation z ≤1. |
| `fast_erratic_after_loss` | TILT | Current game, any result: follows a completed same-session loss within 0–120 seconds; current mean think time ≤65% of strictly prior personal median (which must be positive); current CPL deviation z ≥1. |

The broad performance-based NOT_TILT rules (`normal_accuracy`, `calm_play`,
`expected_loss`, `rest_and_recover`) require **at least 40 board plies** and an
interpretable completion: mate, stalemate, draw, ordinary time forfeit, or
resignation from a clearly lost position (≤−500 cp or negative mate score).
Missing status/length or missing required resignation evaluation causes
abstention. Forty plies provide roughly twenty own turns; short opening samples
cannot establish normal whole-game performance. High average accuracy can
precede an abrupt viable-position ending, and later recovery cannot disprove
such an event. Those were overlapping definitions, rather than useful opposing
evidence. The ending scope is shared and declared as LF provenance. It is not
conditioned on current wins/losses or on another LF's learned accuracy. Conflicts
with post-loss deterioration in otherwise completed games remain possible.

Both `abandon` and `early_resign` are retained. The former now needs an adverse
ending from a viable position; the latter's trigger stays unchanged. No LF
accuracy is set by hand. Their revised coverage and train-fitted accuracies must
be checked on Colab; narrower scopes do not constitute validation. Connectivity
loss and rational resignation remain alternative explanations. No LF was added
or threshold loosened to force the outcome gate to pass.

The three post-loss TILT rules can fire on wins/draws; normal-accuracy,
rest-and-recover and calm-play rules can fire on losses, alongside two dedicated
loss negatives. The result-conditioned abandon/early-resign rules remain narrow
hypotheses, not a definition of tilt. Rational resignation, disconnection,
fatigue, opponent strength, forced moves and ordinary quick requeueing are
alternative explanations. Correlated LFs can still overcount the same evidence.

These thresholds are explicit behavioural hypotheses. The changes remove the
mandatory outcome condition from broad rules and define normal-performance
negatives; no real-data threshold search or held-out tuning was performed.
They must not be loosened merely to manufacture a passing gate. Any future
threshold adjustment must use train data only and be documented here; human
validation requires separate training data and an untouched human test set.

Previous games must have conservative end strictly before current start;
overlapping games cannot supply past evidence. Next-game aftermath is available
only for nonoverlapping games with known conservative ends. Current-game evidence
horizons include the next game when it starts within 30 minutes, conservatively
even if an aftermath LF ultimately abstains. Unrelated future session endpoints
no longer extend the horizon. Cohort truncation changes aftermath coverage.

Secondary player–session targets pool each LF across games: any TILT vote,
otherwise any NOT_TILT vote, otherwise abstain. A separate label model fits train
sessions only; mixed-partition sessions are purged. No session predictor or
session performance claim is made. Pooling increases coverage with session length.

## Label model and outcome gate

`LabelModel` is symmetric regularised Dawid–Skene EM **conditional on non-abstain
votes only**. Each LF has one accuracy `a`, shared across both classes:
`P(correct non-abstain vote | class) = a`, incorrect probability `1−a`.
An abstention contributes exactly zero log likelihood ratio, independently of
class or LF identity. No abstention/coverage emission is fitted.

The class prior is fixed at **0.5**, not inferred from one-sided coverage. This is
an explicit balanced evidence prior, not an estimate of prevalence. It ensures
that any row with only NOT_TILT votes is below both the prior and 0.5, while only
TILT votes put it above the prior. A freely estimated prevalence could overwhelm
a single negative even when all LF polarities are positive. Beta(6,2) accuracy
pseudocounts initialise/regularise accuracies at 0.75. Each M-step uses
`(expected correct votes + 6)/(non-abstain votes + 8)`, projected into
`[0.500001, 0.999999]`; no LF can reverse polarity. EM stops at maximum accuracy
change <1e−7 or 150 iterations. Accuracy estimates are latent assumptions, not
human-measured accuracies. Zero-coverage LFs retain their prior accuracy.

Fit separately on covered train rows for each split, freeze for validation/test.
All-abstain rows retain null probabilities and labels; they stay available for
scoring but are excluded from supervised fitting and weak-label metrics. Covered
rows use `probability >= .5`; majority vote reports the positive fraction among
active votes, with ties TILT. One-class training partitions are skipped honestly.
The label-model state and rule provenance are versioned in the weak manifest;
weak manifest version is now **3**. Training/evaluation reject earlier labels or
models without both audits, and exports without the current
60/20/20 and 70/85 split-policy metadata.

For **each split**, `outcome_gate` uses only train rows with a non-null weak label
and known result. Define `lost = (result_score == 0)`; draws/wins are non-losses.
Report agreement `mean(weak_tilt_label == lost)`, covered counts, and weak-TILT
and weak-NOT_TILT rates separately within losses and non-losses. Unknown outcomes
are excluded explicitly. The gate fails if:

- Agreement is **>0.75**; or
- Either outcome stratum has **<10% of either weak class**; or
- No covered known-outcome rows, or either outcome stratum is empty.

Exactly 0.75 agreement and exactly 10% minority class are permitted. A failure
prints **FAILED: label ≈ outcome** near the top of MODEL_REPORT.md and alongside
split diagnostics. Gate results are saved in both weak_manifest.json and
weak_metrics.json. Passing this gate only rejects this particular confound; it
does not validate an emotion construct. Failing runs still produce diagnostic
models/reports, and the report suppresses superiority claims.

## Model inputs and train-only proxy audits

The predictor list is an explicit allowlist. Every variant excludes:

- All declared LF current/past/future columns, ids, absolute timestamps, label
  probabilities/votes, outcome/status, and evidence horizons.
- Engine-quality families (CPL, accuracy, winning-chance loss, evaluations,
  judgements/errors, adverse/recovery/post-event/material features) and their
  baseline/deviation/similarity relatives; equal-evaluation timing and
  CPL-dependent sacrifice flags.
- Result form, losing streak, immediate-after-loss, rest gaps and their relatives.
- All rating inputs/relatives, now shared with `expected_loss`.
- All think-time inputs/relatives and phase speed change, now shared with
  `fast_erratic_after_loss`. This includes timing dispersion for conservative
  provenance closure, rather than reintroducing the LF signal through aliases.
- Original mixed BDS and deviation-feature count; any clock-fraction input,
  especially **`clock_fraction_last`**, which is no longer constructed by
  `enrich` or prefix scoring.

Retained candidates include style/risk rates, rematch context, clock missingness,
phase fractions, time-control/speed context and admissible personal history.
Phase fractions and other whole-game aggregates can still proxy outcome, so
none is presumed safe without the audit. Safe BDS is recomputed from retained
style/deviation inputs; missing personal history remains missing.

For each split, audit **every full-variant candidate input** on **all train rows,
including unlabelled rows**, never validation/test. Compute ROC-AUC for predicting
(1) loss and (2) `status == 'outoftime'` (time forfeit; `timeout` is abandonment).
Exclude unknown target rows from that target's audit. Use `max(AUC, 1−AUC)` so
reverse association also counts. Audit values use train-median imputation (zero
if completely unobserved); additionally audit each missing indicator because the
model imputer exposes missingness. Constant features with both target classes
score 0.5. Undefined target AUCs remain null.

Every variant now excludes any feature whose value or missing-indicator outcome
AUC is **>0.70** for either target. Undefined outcome audits fail closed. The
historical JSON key `exclude_strict` is retained, but applies to every variant.
Strict variants additionally remove game/session history exposure counts.
`no_history` variants remove baseline/deviation/similarity columns, safe BDS and
history counts; the LSTM still has its recent-game sequence.

The **LF-provenance audit** compares every candidate against every scalar LF
input on train rows, including unlabelled train rows. `lf_input__*` columns in
weak exports retain audit-only current/past/future quantities: length, result,
status, rest gaps, z-scores, personal quality/timing baselines, rating differences,
terminal evaluations and adverse-event distances. Upstream move sources also
have min/max/mean summaries; temporal differences and individual session gaps
are included alongside the LF's boolean comparisons. Future performance is only
retained inside the LF's supported 30-minute evidence horizon. These columns
never enter the predictor allowlist or human labels.

For each candidate/quantity pair compute absolute **Spearman rho**, excluding
the candidate from **every variant at |rho| ≥0.60**, in either direction. Check
pairwise observed values, train-median imputed values and the candidate's missing
indicator. Numeric quantities use their natural scale; categorical status uses
one-versus-rest indicators defined on train categories. Also check LF quantity
missingness, because the availability of LF evidence can itself leak provenance.
Constants/all-missing pairs have null rho (no measurable rank association).
There are no phase-fraction or clock-feature exceptions. The report lists the
top 15 strongest candidate matches per split, paired counts, representation and
matched LF quantity, plus explicit feature-removal lists for each audit. Full
per-feature strongest matches are saved in both manifests/metrics JSON.

Selection checks each run's actual feature list against **both** completed
audits; unassessed or excluded inputs are ineligible even in `full` variants.
Diagnostics remain intentionally exempt and cannot be selected or scored. A
variant with no admissible features is skipped with a recorded reason. Spearman
only detects monotone pairwise proxies; surviving it does not prove independence
from LF evidence or validate emotions.

`clock_missing_fraction` now measures missing telemetry among eligible own
turns. Structurally unclocked first own moves and observed zero-time/premove
intervals (including equal-clock zero-increment readings) are removed from both
numerator and denominator. Genuine missing/invalid clocks remain in the numerator;
NaN counts as missing too. No eligible moves gives null, rather than 0 or 1/N.
This change is confined to the aggregate computation; streaming FrameSink and
slim engine-cache code are preserved. Regenerated clock missingness is still
subject to both audits.

## Splits, fitting and honest evaluation

Stable player-hash split is approximately **60/20/20**; target players are disjoint.
The hash function, fixed namespace and test bucket are unchanged; the validation
bucket expands from hash fractions [0.2, 0.3) to [0.2, 0.4). Hashing a given
exported player id does not read the salt; pseudonymisation retains its existing
salt dependence. Small cohorts can still deviate substantially from expected
proportions. Human-label dataset split defaults are unchanged.
Shared predicted games and label-evidence games (past/future dependencies) purge
train before validation/test and validation before test. LSTM sequences exclude
shared-game-purged rows. Strictly prior unlabelled personal history is allowed.
Time split uses **70th/85th percentiles** of unique starts (approximately
70/15/15 before purging) and requires the full
label-evidence horizon before the next cutoff; unknown ends/crossing scopes are
excluded. All preprocessing fits labelled train rows only; audit preprocessing
uses all train rows as specified above.

Random Forest, XGBoost CPU, LightGBM and a one-layer CPU LSTM each fit hard weak
classification and soft-target regression. Default 100 trees, 12 maximum LSTM
epochs, two threads, seed 42. Classifiers use balanced training weights; soft
regression is unweighted. The LSTM uses up to eight completed recent games,
including current snapshot, observed-step padding, validation early stopping and
gradient clipping. Overlapping/unknown-end games do not enter prior context.

Validation-only Platt calibration falls back to identity with <20 validation
rows, **<10 validation weak positives**, one class, or a nonpositive slope,
with an explicit status. Model selection is **validation average
precision only**, restricted to trained trees whose actual inputs pass both
audits. Test results never select models.
The selected model is reported with its validation-positive count and a warning
below 30 positives. No eligible unseen-player validation model means scoring is
unavailable.

Every trained tree and LSTM chooses a binary decision threshold on **calibrated
validation scores only**, maximising validation F1 and choosing the higher
threshold on ties. If validation has **fewer than 10 weak positives or only one
scored class**, use the labelled-train calibrated-score quantile at
`1 - train weak-positive rate`, with the higher order statistic. With untied
scores this matches the train predicted-positive rate to its weak-positive rate.
Predictions use `probability >= threshold`. A scalar threshold cannot split tied
scores, so ties (especially a constant class-prior baseline) may prevent an exact
rate match; this limitation is explicit in the fallback source. Null diagnostic
scores are excluded. Test rows never choose thresholds.

Store `threshold` and `threshold_source` in every bundle and run-manifest entry;
report them for every model and diagnostic. Older bundles without thresholds
must be retrained on Colab. Bootstrap resamples reuse the frozen threshold.

Three diagnostic baselines appear in aggregate, outcome-stratum and selected
speed/rating metrics tables: train class prior, train-fitted losing streak, and
**`result_only` (score = lost, regression = 100 × lost)**. Unknown outcomes give
null result-only predictions. Diagnostics cannot be selected or scored.
Each diagnostic selects its own threshold by the same validation-F1/train-quantile
rule on its own scores; diagnostic scores remain uncalibrated as before.

Every model has validation and test metrics **within losses and within
non-losses**, placed before aggregate test metrics in the report and saved in
weak_metrics.json. Partition tables for each split give players, rows, labelled
rows, weak positives and positive rate for train, validation and test. Player
counts include all retained rows; positive rates use labelled rows only.
Precision/recall/F1 use each run's stored decision threshold in aggregate,
outcome strata, subgroup tables and bootstrap intervals; ROC-AUC and average
precision are undefined for single-class strata. MAE/RMSE measure 0–100 soft
weak-target error; Brier/reliability use hard weak labels. Aggregate test
uncertainty uses player-cluster bootstrap percentile intervals; selected
speed/rating group intervals remain in JSON. Intervals ignore weak-label
uncertainty. Within-stratum tables show point estimates and sample sizes.

A superiority sentence requires a passing train gate and strictly higher test
PR-AUC, F1 and ROC-AUC than **all three** diagnostics, plus strictly higher
ROC-AUC than all diagnostics **within each outcome stratum**. Missing AUCs prevent
a claim. Otherwise the report explicitly states that superiority is unproven.
These point comparisons do not establish statistical significance or emotion
recognition.

Validation permutation importance and train-reference replacement sensitivities
explain the selected tree. Sensitivities are neither causal nor additive SHAP
values. Scores are 100 × calibrated agreement with the weak target, not an
emotional probability; bands are 0–25, 26–50, 51–75, 76–100. Prefix timelines
and game outputs include a weak-model binary flag using the stored threshold;
the 0–100 score and bands are unchanged. Prefix timelines
rebuild aggregates from prefix moves and frozen strictly-prior history, but remain
exploratory applications of a game-end model without window labels/calibration.

## Execution and privacy

Only run real-data pipeline commands on the designated compute machine/Colab,
after transferring the revised code. Regenerate features first: the saved clock
missingness is stale. Engine/cache and streaming code are unchanged. From that machine's repository root:

```bash
export TILT_SALT=$(cat ~/.tilt-salt)
tilt/.venv/bin/python -m tilt weak-label --users-file ~/tilt-users.txt
tilt/.venv/bin/python -m tilt train --threads 2 --epochs 12 --trees 100
tilt/.venv/bin/python -m tilt evaluate --bootstrap-repetitions 100
```

Never print/copy the salt. Persisted exports/reports use existing salted HMAC
identifiers; never raw usernames/game ids. Local `score --player <username>
[--game <id>]` prints explicitly requested identifiers only to stdout. No weak
command writes human labels. Validate against consented self-reports and expert
labels with independently held-out players/time before making emotion claims;
see the generated report's human-validation instructions.

Small synthetic/offline verification on the owner's machine:

```bash
tilt/.venv/bin/python -m pytest -q tilt/tests
```

The existing suite includes its bounded real-Stockfish integration test. Pipeline
fixtures use temporary synthetic data, tiny trees and one LSTM epoch; they do not
run weak labelling, training, evaluation or feature generation on `tilt/data/processed/`.
