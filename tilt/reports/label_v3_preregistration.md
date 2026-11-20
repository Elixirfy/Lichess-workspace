# Label v3 pre-registration

Status: locked on approval of S0. Scope of this lock: label design (§1–§5) and S1 deliverables (§6). Nothing in §2–§5 may change after the first S1 number is computed (see §8).

## 0. Purpose and limitation

- **Purpose.** Replace v1/v2 weak labels with a deterministic, rule-based label for "behavioural tilt": a game played in a context of recent in-session losses that also shows degraded behaviour against the player's own baseline.
- **Use.** Later stages train a model that predicts this label early, from prior games and the first 20 plies ("rule distillation").
- **Limitation.** The label is a rule, not a measurement of emotion. Any model result means "predicts the v3 rule early and calibrated" and nothing more.
- **Decided by the user.** Rule labels only; this overrides the L2 stop rule.

### Changes from the approved sketch (made before any number was computed)

| Item | Sketch | This document | Reason |
|---|---|---|---|
| C3 threshold | 1.5 | 2.0 | At 1.5, a loss run of 2 fires C1 and C3 together, so "strong" would equal "loss run ≥ 2". |
| NOT after losses | 0 evidence | ≤ 1 evidence and CPL z ≤ 0 | "0 of 7" would leave almost no NOT games after losses. |
| E3/E4 move window | skip first 5 own moves | all own moves | One minimum (5 own moves) for every per-move LF, so short games are not short of evidence by construction. |
| Context level | none / weak / strong | adds `stale` | Covers "earlier session loss, no C fires, g−1 not lost". |
| E7 | below player's 20th-percentile gap | also ≤ 60 s | A slow player's 20th percentile can be minutes. |

## 1. Data and time split

### 1.1 Rows
- Existing cohort: 196 players, 36,401 blitz games, aligned splits `by_player` and `by_time`.
- **S1 labels and gates use train rows only**: `by_player` train and `by_time` train (22,316 each), evaluated separately.
- S1 must not compute label statistics on validation, the old test, or the 465 purged rows. The old test becomes development data from S3 on.
- Feature inputs (prior games, the next game's start time) may come from any row of the same player regardless of split. Under `by_time`, prior games are always earlier.

### 1.2 Definitions
- **Game g**: one cohort player's side of one game. "Own moves" are that player's moves.
- **Loss / draw / win**: `result_score` 0 / 0.5 / 1.
- **Session**: the existing `session_id` (new session when `start_ms(g) − end_ms(previous game) > 30 min`). Do not recompute.
- **S(g)**: games of the same player with the same `session_id` and an earlier `start_ms`, most recent first. Empty for the first game of a session.
- **g−1**: the first element of S(g). It must be in the same session; otherwise it does not exist.
- **gap(x)** for a game x that is not first in its session: `start_ms(x) − end_ms(previous game)`, in seconds, using the same end timestamp as the session code.
- **Length bucket**: `short` if `plies < 40`, else `long`.

### 1.3 Baselines
Reuse `robust/score_baseline` logic:
- candidate games: same player, same speed, `end_upper_ms < start_ms(g)`;
- **bucketed window**: the last ≤ 200 candidates in the same length bucket as g, if there are ≥ 20;
- **pooled window** otherwise: the last ≤ 200 candidates of any length, requiring ≥ 5;
- fewer than 5 candidates: no baseline;
- `z = (x − median) / max(1.4826·MAD, unit_floor)`;
- record `baseline_kind ∈ {bucketed, pooled, none}`.

Unit floors:

| Feature | Unit floor |
|---|---|
| `cpl_mean_w300` | 5.0 |
| `blunders_per20` | 0.2 |
| `think_frac_median` | 0.002 |
| `think_cv` | 0.10 |
| `risk_rate` | existing (.05) |
| `attack_rate` | existing if defined, else .05 |
| `sacrifice_rate` | existing if defined, else .02 |

### 1.4 Label-only versus model-side fields
- **Label-only (never a model input in any later stage):**
  - any per-move data of g after ply 20, and every whole-game aggregate of g;
  - g's `result_score`, `status`, `plies`, length bucket and `baseline_kind`;
  - anything after g: next-game gap, later games;
  - all E values, `n_fired`, `n_missing`, and the label.
- **Model-side:**
  - all games before g with their full data;
  - the context quantities of §2.1 (they use only games before g);
  - baselines; time control; g's rating;
  - per-move data of g's first 20 plies.

## 2. Labelling functions

### 2.1 Context LFs (boolean; inputs are S(g) only; missing input means "does not fire")

| LF | Fires when |
|---|---|
| C1 | `L(g) ≥ 2` |
| C2 | losses among the first 5 of S(g) ≥ 3, **or** among the first 10 ≥ 5 |
| C3 | `D(g) ≥ 2.0` |
| C4 | `rating(g) − rating(first game of the session) ≤ −30` |
| C5 | recency **and** shrinking gaps (below) |

- **L(g), in-session loss run.** Scan S(g) from most recent: a loss adds 1, a draw is skipped, a win stops the scan. The session start also stops it.
- **C2.** Draws and wins occupy slots and are not losses. With fewer than 5 (or 10) games, use those available against the same absolute thresholds.
- **D(g), decayed loss load.** `D = Σ_{k=1..K} loss_k · 0.5^((k−1)/2)`, K = min(|S(g)|, 10), k = 1 is g−1, `loss_k = 1` for a loss and 0 for a draw or win.
- **C4.** `rating` is the player's rating before each game. The first game of a session has delta 0.
- **C5 recency.** `start_ms(g) − end_ms(most recent loss in S(g)) ≤ 120 s`.
- **C5 shrinking.** Needs |S(g)| ≥ 3, so that gap(g), gap(g−1), gap(g−2) all exist. Condition: `gap(g) ≤ gap(g−1) ≤ gap(g−2)` and `gap(g) < gap(g−2)`. With fewer than 3 gaps, C5 does not fire.

**Context level** (`n_C` = number of C1–C5 firing; `prev_lost` = g−1 exists and was lost; `recent_loss` = any loss among the first 5 of S(g)):

| Level | Condition |
|---|---|
| `strong` | `n_C ≥ 2` |
| `weak` | not strong, and (`n_C = 1` or `prev_lost`) |
| `none` | `n_C = 0` and not `recent_loss` (includes every first game of a session) |
| `stale` | everything else: `n_C = 0`, g−1 not lost, but a loss among the last 5 session games |

### 2.2 Eligibility
g is eligible only if all hold; otherwise the label is ABSTAIN with the reason code.
- ≥ 5 own moves (`short_game`);
- ≥ 5 own moves with non-null `cpl` (`no_eval`);
- a baseline exists and `z_cpl` is computable (`no_baseline`).

### 2.3 Evidence LFs (each is `fired`, `not_fired` or `missing`)

| LF | Value x | Fires | Minimum data, else `missing` |
|---|---|---|---|
| E1 `centipawn_loss` | `cpl_mean_w300` = mean of `min(cpl, 300)` over own moves | `z ≥ 1.0` | guaranteed by eligibility |
| E2 `blunder_count` | `blunders_per20` = 20 · (own moves with `judgement == blunder`) / (own moves with non-null `cpl`) | `z ≥ 1.0` | ≥ 5 own moves with `cpl` |
| E3 `move_time` | `think_frac_median` = median own `think_seconds` / (`initial_seconds` + 40·`increment_seconds`) | `z ≤ −1.0` | ≥ 5 own moves with `think_seconds`; denominator > 0 |
| E4 `time_variance` | `think_cv` = population std / mean of own `think_seconds` | `z ≥ 1.0` | ≥ 5 own moves with `think_seconds`; mean > 0 |
| E5 `aggression_score` | mean of `z(risk_rate)`, `z(attack_rate)`, `z(sacrifice_rate)`; each rate = share of own moves with the flag | score ≥ 1.0 | all three z computable |
| E6 `resign_behavior` | see below | see below | see below |
| E7 rage requeue | see below | see below | see below |

`z_cpl` is E1's z. A z is `missing` when the baseline window has fewer than 5 games with that feature non-null.

**E6.** Applies only if g was lost; otherwise `not_fired`. Fires if (a) or (b):
- (a) `status == resign` and the player's win chance at the final position ≥ 20%.
  - Final eval = `eval_after_cp` / `eval_after_mate` of the last ply of the game; if null, of the ply before it.
  - Convert to the player's point of view (verify the stored sign convention in the code), then apply `formulas.win_percent`.
  - If both evals are null, (a) is undetermined.
- (b) `status == timeout` (abandonment); **or** `status == outoftime` and the player's last recorded `clock_seconds ≥ 0.20 · initial_seconds`. No clock data means this sub-condition is false.
- E6 is `missing` only when (b) is false and (a) is undetermined on a resigned game.

**E7.** Applies only if g was lost; otherwise `not_fired`.
- Next game = the player's next game by `start_ms`. It counts only if it has the same `session_id`.
- `q20` = 20th percentile of gap(x) over the player's last ≤ 200 prior games that are not first in their session; needs ≥ 10 such gaps.
- Fires when the next game is in-session and `gap(next) ≤ min(q20, 60 s)`.
- Lost with no in-session next game: `not_fired`.
- `missing` when g is the player's last collected game, or when fewer than 10 prior gaps exist.

**Counts.** `n_fired` = number of E1–E7 that fired; `n_missing` = number missing. Missing never counts as fired. For NOT, missing counts against the game (worst case).

## 3. Label combination

Deterministic; no Dawid–Skene.

- **TILT** if all of:
  1. eligible and `z_cpl > 0`;
  2. (`strong` and `n_fired ≥ 2`) or (`weak` and `n_fired ≥ 3`);
  3. if g was won (`result_score == 1`): `strong`, `n_fired ≥ 3`, and E1 or E2 fired. Draws follow the ordinary rule.
- **NOT** if eligible, `n_fired + n_missing ≤ 1`, and (`none` or `z_cpl ≤ 0`).
- **ABSTAIN** otherwise.

TILT and NOT are mutually exclusive: within `weak` and `strong`, TILT needs `n_fired ≥ 2` and NOT needs ≤ 1; `none` and `stale` never give TILT.

Truth table (eligible games; `e` = `n_fired`, `u` = `n_fired + n_missing`):

| Level | `u ≤ 1`, `z_cpl ≤ 0` | `u ≤ 1`, `z_cpl > 0` | `e = 2`, `z_cpl > 0` | `e ≥ 3`, `z_cpl > 0` | `e ≥ 2`, `z_cpl ≤ 0` | `e ≤ 1`, `u ≥ 2` |
|---|---|---|---|---|---|---|
| none | NOT | NOT | ABSTAIN | ABSTAIN | ABSTAIN | ABSTAIN |
| stale | NOT | ABSTAIN | ABSTAIN | ABSTAIN | ABSTAIN | ABSTAIN |
| weak | NOT | ABSTAIN | ABSTAIN | TILT | ABSTAIN | ABSTAIN |
| strong | NOT | ABSTAIN | TILT (ABSTAIN if won) | TILT (if won: needs E1 or E2) | ABSTAIN | ABSTAIN |

## 4. Gates

Evaluated on `by_player` train and on `by_time` train. **Every gate must pass on both.** T, N, A = counts of TILT, NOT, ABSTAIN; "labelled" = T + N.

| Gate | Formula | Pass |
|---|---|---|
| G1 length AUC | ROC AUC of `plies` for TILT vs NOT among labelled; take `max(AUC, 1 − AUC)` | ≤ 0.60 |
| G2 length gap | TILT share `T/(T+N)` in buckets `plies < 40`, 40–79, ≥ 80; max − min | ≤ 15.0 points |
| G3a coverage | `(T+N)` / all train rows (ineligible rows in the denominator) | ≥ 0.50 |
| G3b post-loss coverage | same, over rows with `prev_lost` | ≥ 0.50 |
| G4 prevalence | `T/(T+N)` | within [0.10, 0.35] |
| G5 won games | share of TILT with `result_score == 1` | ≤ 0.10 |
| G6 dominance | for each E, share of TILT games where it fired | each ≤ 0.70 |
| G7 monotonicity | `s_L` = share of eligible games with `n_fired ≥ 2`, for L = 0, 1, 2, 3+ | `s_3+ − s_0 ≥ 0.03` and `s_{L+1} ≥ s_L − 0.01` |

- G2: a bucket with fewer than 100 labelled games is merged into its neighbour before the gap is taken; report the merge.
- G7 tests evidence, not the label, because the label contains the loss run.

**Report only (no pass/fail):**
- vote counts per LF, and the distributions of `n_fired` and of context level;
- label by rating tercile and by time control;
- AUC of `result_score` for the label;
- agreement with v1 labels (`weak_by_player.parquet`, train rows);
- share of each ABSTAIN reason;
- `baseline_kind` shares by label.

## 5. Fallback `v3b`

Computed **only if v3 fails at least one gate**. Identical to v3 except E1–E5 and the CPL sign test:
- **Reference set**: the baseline window of §1.3, but the bucketed window needs ≥ 20 games and the pooled window also needs ≥ 20; otherwise the LF is `missing` (and for CPL, the game is ineligible with `no_baseline`).
- **E1, E2, E4**: fire when x(g) ≥ the 80th percentile of the reference set.
- **E3**: fires when x(g) ≤ the 20th percentile.
- **E5**: fires when at least 2 of the 3 rates are ≥ their 80th percentile.
- **`z_cpl > 0`** becomes `cpl_mean_w300(g) >` reference median; `z_cpl ≤ 0` becomes `≤` median.
- Percentiles use linear interpolation.
- Context, E6, E7, eligibility, combination and gates are unchanged.

**If `v3b` also fails:** select the variant with fewer failed gates on `by_player` train (ties: fewer on `by_time`, then v3). List the failed gates as known limitations in the report. The user then decides whether S2 proceeds; if it does, adoption in S5 is judged on the length strata only (§7).

## 6. S1 deliverables (Codex)

**Before any computation:** save this document as `tilt/reports/label_v3_preregistration.md` and write its sha256 to `~/tilt-labels-v3/prereg.sha256`.

**Code:**
- `tilt/src/tilt/labels/rules_v3.py`: all constants in one frozen dataclass (with a design hash over the constants), context LFs, evidence LFs, combination, gates, `v3b`, and a CLI entry point.
- `tilt/tests/unit/test_rules_v3.py`, covering at least:
  - L(g) with draws and with a session boundary;
  - C2 with fewer than 5 games; D(g) values for LL, LLL, LWLL;
  - C5 with fewer than 3 gaps;
  - every context level, including `stale` and first-of-session;
  - each E in its fired / not-fired / missing state;
  - E6 point-of-view conversion and the mate case;
  - E7 with no next game and with the last collected game;
  - every cell of the truth table; the won-game rule;
  - invariants: no TILT with `z_cpl ≤ 0`, none in the first game of a session, none in `none` or `stale`;
  - the baseline uses only prior games;
  - validation, test and purged rows are never labelled.

**Outputs in `~/tilt-labels-v3/S1/` (outside the repo, never committed):**
- `labels_by_player_train.parquet`, `labels_by_time_train.parquet`, one row per game with: game id, player, L, D, C1–C5, level, each x and z, each E state, `n_fired`, `n_missing`, `baseline_kind`, label, abstain reason;
- `gates.json`, `lf_stats.csv`, `design_hash.txt`;
- the same files with a `_v3b` suffix if the fallback runs.

**Report:** `tilt/reports/label_v3_S1.md` with the gate table for both splits, the report-only items, any deviations, and a pass/fail verdict.

**S1 must not:** train any model, touch `lila/`, modify v1/v2 code or outputs, read validation/test labels, commit, or push. The whole test suite must still pass.

## 7. Later stages (each needs user approval)

- **S2, data.**
  - Codex writes the collector; the user runs Stockfish on Colab.
  - 200 new blitz players, ≤ 150 latest games each, stratified by rating.
  - Engine settings identical to the cache: nodes 5000, multipv 2, hash 32 MB, threads 1, fresh game per position, `settings_key ca2f1c3a…`.
  - Gate: clock coverage ≥ 90% and the settings key matches.
- **Holdouts.**
  - A′ = 60 of the new players (chosen by hash of player id), all their games.
  - B′ = the latest 20% of games of the other 140.
  - Both stay unlabelled and unscored until S5.
- **S3, features (Codex).** Model-side features per §1.4, with an automated test that no label-only field reaches the model.
- **S4, training (Codex code; user trains on Colab).**
  - Class weights in train only; abstained games excluded from training.
  - Platt calibration on the unrebalanced validation set.
  - Gate: M-v3 beats `R-pre` on validation.
- **S5, one-shot evaluation on A′ and B′ with v3 labels.**
  - Candidates: B-length and B-result (reference only), B-streak, `R-pre` (context level from model-side inputs), P3-B frozen, P3-B/v3 (same features retrained on v3 labels), M-v3.
  - Report: PR-AUC with prevalence and a player-clustered bootstrap CI, ROC-AUC, ECE, Brier; each for all games, ≥ 40 plies and < 40 plies.
  - **Adopt M-v3 over P3-B only if all hold on both A′ and B′:**
    - ΔPR-AUC against each of P3-B/v3, `R-pre` and B-streak has a CI lower bound > 0;
    - Δ > 0 in both length strata;
    - ECE ≤ 0.05.
  - Otherwise P3-B stays deployed.
  - v1-label results appear on validation only, as description.

## 8. Deviations policy

- If a rule cannot be implemented as written (a column is missing, a convention differs, a definition is ambiguous), Codex **stops before computing any label statistic**, writes the problem and a proposed minimal change under "Deviations" in the report, and waits for a decision.
- Facts to verify in code before use, and to report if they differ from this document:
  - the sign convention of `eval_after_cp` / `eval_after_mate`;
  - whether `rating` is the pre-game rating;
  - that `status == timeout` means abandonment;
  - the existing unit floors;
  - the end timestamp used by the session code.
- Purely mechanical choices not covered here (column names, file layout inside the module) are Codex's to make and must be listed in the report.
- No threshold, LF, gate or row set may change after the first gate value is seen. A change after that point needs a new, separately hashed pre-registration and a new variant name.
- Bugs found after numbers are seen: fix, re-run, and report both the old and the new numbers.

## Erratum 1 (before any number)

Recorded after S1 preflight stopped under §8. No label, LF vote, or gate value had been computed.
This erratum supersedes the original text where they differ. It changes no LF, threshold, gate,
combination rule or split membership.

### E1.1 Row counts (corrects §1.1)
- The figure "22,316 each" was wrong. The train rows are exactly the rows with `split == 'train'`
  in each aligned file: 22,316 for `by_player` and 25,403 for `by_time`.
- For reference, the aligned files contain:
  - `by_player`: train 22,316 / validation 6,697 / test 6,923 / purged_shared_game 465;
  - `by_time`: train 25,403 / validation 5,431 / test 5,476 / purged_crossing_cutoff 91.
- Gates (§4) are evaluated on each split's own train rows. Purged rows of either split are never
  labelled.

### E1.2 E6 point of view (clarifies §2.3)
- `eval_after_cp` / `eval_after_mate` are stored from the mover's point of view.
- For the ply used as the final eval: if the mover is the cohort player, use the values as stored;
  if the mover is the opponent, negate both cp and mate before applying `formulas.win_percent`.
- The same rule applies when falling back to the ply before the last.

### E1.3 Unit floors and time-control columns (clarifies §1.3, §2.3)
- `risk_rate` and `attack_rate` use the existing floor .05. `sacrifice_rate` has no existing floor,
  so the pre-registered .02 applies.
- `initial_seconds` and `increment_seconds` are read from the aligned files, joined on game id.
  The same values are used for prior games in the baseline window. If either value is null for a
  game, E3 is `missing` for that game, and the E6(b) `outoftime` sub-condition is false.

### E1.4 Missing `end_ms` (clarifies §1.2, §2.1, §2.3)
- Session membership is the existing `session_id`, unchanged, including where the session code
  used a previous-start proxy.
- A gap is "exact" only if the previous game's true `end_ms` exists. Proxy-based gaps are never
  used in a threshold:
  - C5 does not fire if the recency interval or any of its three gaps is not exact;
  - E7 is `missing` if g was lost and `end_ms(g)` is absent;
  - `q20` is computed from exact gaps only, and still needs ≥ 10 of them.
- Baseline eligibility keeps using `end_upper_ms`, as in the existing code.

### E1.5 Rating (clarifies §2.1 C4)
- `rating` is the cohort player's `white_rating` / `black_rating` for that game, taken as the
  pre-game rating.
- Before computing labels, verify this on train rows with a data check that involves no label:
  for consecutive rated games of a player, the sign of `rating(next) − rating(g)` should match
  the result of g in at least 95% of decisive pairs.
- If the check fails, stop under §8. If it passes, report the percentage under "Deviations".

### E1.6 Status semantics
- Confirmed as assumed: `timeout` = abandonment, `outoftime` = time forfeit. No change to E6.

### E1.7 Lock
- The sha256 of the document before this erratum is kept in `~/tilt-labels-v3/prereg.sha256.v0`.
- The sha256 of the document including this erratum is written to `~/tilt-labels-v3/prereg.sha256`
  and is the lock from here on. Both are quoted in `tilt/reports/label_v3_S1.md`.

## Addendum S2 (after S1, before any collection)

Recorded after S1 (verdict FAIL; v3 selected by §5). The user chose to proceed to S2. Standing consequence of §5:
the known limitations are G1, G4, G6 and G7 (by_time), and S5 adoption is judged on the length strata only.
This addendum changes no LF, threshold, combination rule or gate of §2–§4.

### S2.1 Sampling
1. Source: the October 2026 monthly dump again, through `tilt sample-players`, with `limit` = 1,200,000 games and
   `seed` = 43.
2. Strata as before: 200-point blitz rating bands from 400 to 3000 (13 bands), `min_games` = 12 in the header window.
3. Exclude the 196 existing cohort accounts (case-insensitive) before picking.
4. Per band: 16 primary players plus an ordered reserve of the next 14 by hash (13 × 16 = 208).
5. Exclusion through the public API user endpoint: drop accounts flagged `tosViolation` or `disabled`, or with title
   `BOT`.
6. Replacement: a player with fewer than 60 blitz games through the API (same `collect-api` filters as the original
   cohort) is replaced by the next reserve in the same band. If the band's reserve runs out, take from the nearest
   band's reserve, lower band first.

### S2.2 Collection window
1. Latest ≤ 150 blitz games per player, no `since`, as for the original cohort.
2. `--until` fixed at 2026-11-16 00:00 UTC, for reproducibility.
3. Old games are kept. Report each player's date span; no exclusion on age.

### S2.3 Data root
1. Separate root `tilt/data/v3new/`. The existing root, its features and the deployed model's parity stay untouched.
2. The engine cache for the new root starts as a copy of the existing cache if the upload size is practical;
   otherwise it starts empty. The existing cache is never written.
3. Raw NDJSON stays in WSL and Colab only. Nothing is committed or copied to Windows.

### S2.4 Holdouts
1. Assignment key: sha256 of the fixed public string `label-v3-holdout-1:` followed by the lower-cased username.
   `TILT_SALT` is not used.
2. A′: within each rating band, sort the collected players by that hash and take the first 30% (round half up);
   all their games are A′ (about 60 players).
3. B′: for every other new player, take the game at the 80th percentile by `start_ms`. B′ is every game from the
   start of that game's session onward, so no session crosses the cutoff.
4. Shared games: if a game has rows in both a holdout and development (new or old cohort), drop the development row.
5. The assignment is made once, after collection and replacement finish. The manifest is hashed, stored in
   `~/tilt-labels-v3/S2/`, and never regenerated.
6. Development portion: non-A′ players' pre-cutoff games are usable in S3/S4 together with the old 196. Their
   train/validation split is fixed in the S3 addendum.

### S2.5 Gate (all must hold)
1. Settings key: the Colab run reports `ca2f1c3a…` exactly, using the uploaded WSL binary. Check this before analysis
   and abort on mismatch.
2. Eval agreement: re-analyse 500 engine-sourced cached positions (picked by hash) on Colab with the cache bypassed.
   Require 500/500 identical cp/mate; otherwise stop under §8 and report the differences.
3. Clock coverage: ≥ 90% of own moves in the new games have `think_seconds`.
4. Eval coverage: ≥ 98% of plies have an eval after `analyze`.
5. Size: ≥ 170 players with ≥ 60 games each, and ≥ 20,000 games in total.
6. No overlap with the 196 existing accounts.
7. Existing root unchanged: its features manifest hash is the same before and after S2.
8. Fewer than 200 but ≥ 170 players: proceed; A′ stays 30% per band.
9. Fewer than 170: raise `limit` to 2,400,000 once and resample only the short bands. If still under 170, stop for
   the user's decision.

### S2.6 S2 must not
1. Run `rules_v3` labelling or compute label statistics on any new row, development or holdout. S2 is data only.
2. Show more than quality-control numbers in the S2 report. Features may be computed for all new games on Colab, but
   the report shows only counts, rating bands, date spans, and clock and eval coverage.
3. Show any behaviour-feature distribution broken down by holdout membership.
4. Change the rules, thresholds or gates; train a model; change `lila/`, v1/v2 code, or the existing data root.
5. Commit or push.

### S2.7 Lock
The sha256 before this addendum is kept in `~/tilt-labels-v3/prereg.sha256.v1`. The sha256 including it is written
to `~/tilt-labels-v3/prereg.sha256` and is the lock from here on.

## Erratum 2 (before any holdout assignment)

Recorded after `cohort_v3 assign` stopped: 82 collected player-game sides (82 games, 26 players)
have no features row. No manifest had been written and no label had been computed on new data.

- The features step drops games with `plies ≤ 1` by construction, in the old cohort as well
  (70 such games there). These games were never part of the modelling universe.
- In Addendum S2, "games" means player-game sides present in features. Sides absent from features
  whose normalized game has `plies ≤ 1` are excluded before assignment and listed in
  `excluded_sides.csv` (hashed in the assignment metadata). Any other missing side is an error.
- The ≥ 60 games-per-player rule, the B′ 80th-percentile anchor, and the S2 gate's size and
  coverage checks are computed on kept sides. The raw collected count is reported beside them.
- Observed before assignment: 30,695 collected sides, 30,613 kept; all 208 players keep ≥ 60 games,
  so no replacement is triggered.
- A′ player selection is unchanged (it is per player). No LF, threshold, gate or hash rule changes.
- The previous lock is kept in `~/tilt-labels-v3/prereg.sha256.v2`.

## Addendum S3 (after S2, before any label or feature is computed on new data)

Recorded after S2 passed its gate 7/7 (holdout manifest sha `d21e5b02…`). The user approved S3 on 2026-11-17.
No v3 label exists on any new game, and no model has been fitted on v3 labels. This addendum changes no LF,
threshold, combination rule or gate of §2–§4, and no holdout membership.

### S3.0 Changes relative to §7 and §1.4

| # | §7 / §1.4 text | This addendum | Reason |
|---|---|---|---|
| 1 | old splits `by_player` / `by_time` | one development split with two validation parts, V_A and V_B (S3.1) | The holdouts are one player-held-out set and one time-held-out set scored by one model; validation now has the same shape. |
| 2 | "first 20 plies" as one feature block for every game | two prediction times and two heads, `pre` and `p20` (S3.2) | A prefix of a game that ends before ply 20 encodes its length, which is label-only (Phase 3 lesson). |
| 3 | adoption comparator P3-B/v3 | **unchanged, by user decision (2026-11-17):** P3-B/v3 stays the adoption comparator. It is exempt from §1.4 as a comparator only; M-v3 stays bound by §1.4. P3-B@20/v3 is added as a reference (S3.4) | Fable proposed P3-B@20/v3 as the comparator, because P3-B's rates are whole-game aggregates that §1.4 bans as model inputs. The user chose the stricter rule: M-v3 must beat the whole-game P3-B/v3. |
| 4 | "baselines" are model-side | model-side baselines use the pooled window only (S3.3) | The bucketed window of §1.3 depends on g's length bucket, which is label-only. |
| 5 | holdouts "unlabelled and unscored until S5" | also no S3 feature row is built for a holdout row (S3.6) | Tightening; removes any way to inspect holdout features. |
| 6 | model-side list in §1.4 | adds opponent rating and colour of g | Both are known before the first move. |
| 7 | `R-pre`, B-streak named only | exact definitions (S3.4) | Needed before any score exists. |

Everything else in §7 stands, including the S5 report strata (all, ≥ 40 plies, < 40 plies) and the three adoption
conditions.

### S3.1 Development rows and split

**Rows.**
- Development pool = every old-cohort side present in the old features (all former train, validation, test and
  purged rows; the old splits are retired) plus the new sides with assignment `development` (15,943).
- Rows with assignment `drop_shared_development` (12 old, 16 new) are never targets: no label is stored for them and
  they enter no train or validation set. They remain usable as history of their own player.
- A′ and B′ rows are never targets in S3 or S4.

**Assignment (made once; the manifest is hashed and never regenerated).**
1. Key: `h(p)` = sha256 of the fixed public string `label-v3-dev-split-1:` followed by the cohort player's identifier
   exactly as stored in the processed games table of its root. `TILT_SALT` is not read.
2. **V_A (held-out players).** Within each cohort (old; new non-A′ players with ≥ 1 development row), sort players by
   `h(p)` and take the first 20%, rounded half up as `(2·n + 5) // 10`. All their development rows are V_A.
3. **V_B (held-out time).** For every other player, order their development rows by `start_ms`, then game id. Take the
   nearest-rank 85th-percentile game, one-based `ceil(0.85·n)`. V_B is every row from the earliest start of that
   game's existing session onward. No session id is recomputed and no session crosses the cut.
4. **Train** = the remaining development rows.
5. **Shared games.** If one physical game has a side in train and another side in V_A or V_B, the train side becomes
   `drop_shared_split`: not a target, still history. Two sides in validation parts are both kept.
6. Expected sizes are not targets. Report rows and players per part and per cohort.

**Integrity checks (must hold):** every development row has exactly one assignment; no player is in both V_A and
train/V_B; no session spans train and V_B; no physical game spans train and validation; the holdout manifest sha is
unchanged.

P3-B frozen was trained on old rows with v1 labels, so its validation numbers are description only.

### S3.2 Prediction times, populations and heads

- **Ply index.** "First 20 plies" means the first 20 half-moves of the game counted over both sides, i.e. 10 own
  moves. Codex verifies whether the stored ply index is 0- or 1-based and reports it.
- **Two prediction times.**
  - `pre`: at the start of g. Available for every game.
  - `p20`: when ply 20 has been played. Available only for games with `plies ≥ 20`. That a game is still running at
    ply 20 is known at that moment, so membership of this population is not label-only information.
- **Populations.** `P-all` = all target rows. `P-20` = target rows with `plies ≥ 20`.
- **Two heads per candidate feature set.**
  - `pre` head: block F-pre only; trained on labelled train rows of `P-all`.
  - `p20` head: F-pre plus F-p20; trained on labelled train rows of `P-20` only.
- **Composite score** of a candidate = the `p20` head's calibrated score when `plies ≥ 20`, else the `pre` head's.
  The composite is what "M-v3" and each retrained comparator mean in §7. `plies` is used only to choose the head.
- **No masking and no indicator for short games.** A game shorter than 20 plies never receives a prefix feature, an
  imputed prefix value or a "short" flag. Every row of `P-20` has exactly 20 prefix plies, so prefix support is
  identical for all rows.
- S5 additionally reports the `pre` head alone on `P-all`, the `p20` head on `P-20`, and the stratum < 20 plies.

### S3.3 Feature blocks

Exact column names are Codex's choice. Every column must be listed in `feature_registry.csv` with: block, family,
source fields, minimum data, and missing-value rule. Missing values stay null in the tables; imputation is S4's.

**F-pre (uses g only through its start time, time control, ratings and colour; everything else from games before g).**
A prior game counts only if `end_upper_ms < start_ms(g)`; report how many in-session prior games fail this.
1. *Meta:* `initial_seconds`, `increment_seconds`, pre-game rating, opponent rating minus own rating, colour.
2. *Session context (§2.1 quantities):* L(g); losses in the last 5 and last 10 session games; D(g); session rating
   delta; `games_in_session_before`; seconds from session start; seconds since the last in-session loss (exact gaps
   only, else null); gap(g), gap(g−1), gap(g−2); C1–C5; `n_C`; context level as a rank; `prev_lost`; result of g−1.
3. *Existing history columns:* `rematch_streak_before`, `losing_streak_before`, `rest_gap_seconds`, `recent_form`.
4. *Previous game g−1 (whole game, same session; null if none):* its five x values and z values of E1–E5 as defined
   in §2.3 for g−1 itself; its E1–E7 states; its `n_fired`; its plies; its status; its v3 label.
5. *Session behaviour:* mean of each E1–E5 z over the last 3 in-session games; count of TILT labels and mean
   `n_fired` over the last 10 in-session games.
6. *Player baseline descriptors:* median and MAD of `cpl_mean_w300`, `blunders_per20`, `think_frac_median`,
   `think_cv`, `risk_rate`, `attack_rate`, `sacrifice_rate` over the **pooled** window of §1.3, and the window size.
   This includes `baseline_risk_rate_games` from P3-B.

Labels and E states of prior games are legitimate inputs: each depends only on data available before g starts
(E7 of g−1 uses the start time of g).

**F-p20 (own moves and positions within plies 1–20 of g; defined only on `P-20`).**
1. *Quality:* mean of `min(cpl, 300)` over own prefix moves; maximum own cpl; counts of own inaccuracies, mistakes
   and blunders; mean of `min(cpl, 300)` over the opponent's prefix moves.
2. *Time:* `think_frac_median` and `think_cv` over own prefix moves; largest own think time over the time budget;
   share of the initial clock used after the tenth own move; think time of the first own move.
3. *Style (P3-B's rates on the prefix):* `risk_rate`, `attack_rate`, `defensive_rate`, `style_switch_rate`,
   `sacrifice_rate` over own prefix moves; the three group-B dynamics exactly as `core/score.py` computes them on a
   game played up to ply 20.
4. *Position:* own win percent after ply 20 and its minimum over the prefix (`formulas.win_percent`, own point of
   view per E1.2); material balance after ply 20; mean `legal_moves` on own prefix moves; phase after ply 20.
5. *Prefix z-scores:* for prefix `cpl_mean_w300`, `think_frac_median`, `think_cv` and the three aggression rates,
   z against the same statistic on the first 20 plies of the player's prior games that reached ply 20 (last ≤ 200,
   `end_upper_ms < start_ms(g)`, at least 5; else null), with the unit floors of §1.3. `aggression_p20` is the mean
   of the three rate z values.

**Candidate feature sets (fixed now; no selection in S3).**
- M-v3: all of F-pre; all of F-p20.
- P3-B@20: `pre` part = `initial_seconds`, `increment_seconds`, `rematch_streak_before`, `baseline_risk_rate_games`;
  `p20` part adds the four P3-B rates and the three group-B dynamics on the prefix.

### S3.4 Baselines and comparators

- **`R-pre`** (no fitting) = rank of the context level (none 0, stale 1, weak 2, strong 3) + D(g)/4. Every game.
- **B-streak** (no fitting) = `losing_streak_before`. Every game.
- **B-length, B-result** (reference only; label-only inputs) = `plies`; `1 − result_score`.
- **P3-B frozen** (reference) = the deployed bundle on the whole game.
- **P3-B/v3** (adoption comparator; exempt from §1.4 as a comparator only) = P3-B's whole-game features retrained on v3 labels.
- **P3-B@20 frozen** (reference) = the deployed bundle scored on the game cut at ply 20, for `P-20` rows only.
- **P3-B@20/v3** (reference) = the P3-B@20 feature set under the two-head protocol of S3.2, retrained on v3 labels.
- **Adoption rule (as §7, user decision 2026-11-17):** ΔPR-AUC of M-v3 against each of P3-B/v3, `R-pre` and
  B-streak has a CI lower bound > 0 on both A′ and B′. The other two conditions are unchanged. References are
  reported beside them and do not decide adoption.

Model class, hyperparameters, calibration details and the S4 gate are fixed in the S4 addendum.

### S3.5 Leakage tests (pytest, automated)

1. **Allowlist.** The model matrix for each head contains only registry columns of the right block. No column name
   or source field is `result_score`, `status`, `plies`, a length bucket, `baseline_kind`, `end_ms` of g, any
   whole-game aggregate of g, any E value of g, `n_fired`, `n_missing`, the label of g, or any `lf_input__*`.
   This test covers the M-v3 and P3-B@20 feature sets. P3-B/v3 is the one exempt comparator (S3.0 row 3): S4
   builds it from P3-B's existing whole-game feature table, outside the S3 registry, and nothing from it may
   enter the M-v3 matrix.
2. **Future perturbation.** On synthetic fixtures and on a sample of real development players: change any move,
   eval, clock or flag of g after ply 20; change g's result, status, plies and end time; delete or alter every later
   game of the player; alter other players' games. F-pre(g) and F-p20(g) stay byte-identical.
3. **Truncation equivalence.** Features built from the full data equal features built from data cut to: all games
   that ended before `start_ms(g)`, g's header, and g's first 20 plies.
4. **Pre-game independence.** Deleting or altering every move row of g leaves F-pre(g) byte-identical.
5. **Baseline independence.** Changing g's plies leaves every model-side baseline value unchanged (pooled window).
6. **Prefix support.** Every `P-20` row uses exactly 20 prefix plies; no row with `plies < 20` has any F-p20 value.
7. **Holdout isolation.** The builder refuses A′, B′ and `drop_shared_*` rows as targets.
8. **Determinism.** Two builds give identical sha256 for every output table.
9. **Label regression.** v3 labels recomputed in S3 for old rows equal the S1 outputs on every row S1 labelled.

**Length probe (diagnostic; targets are lengths, never labels; train rows only).**
- For each F-p20 column on `P-20`: single-feature ROC AUC for `plies < 40`, and the null-rate difference between
  rows with 20–39 plies and rows with ≥ 40.
- For each F-pre column on `P-all`: single-feature ROC AUC for `plies < 20` and for `plies < 40`.
- A multi-feature probe per block (gradient boosting, 3 folds grouped by player) is reported only.
- **Stop for a decision** (no automatic removal) if any single-feature AUC, taken as `max(AUC, 1 − AUC)`, is ≥ 0.70,
  or any null-rate difference exceeds 2 percentage points.

### S3.6 What S3 may compute

- **Labels.** Run frozen `rules_v3` (variant v3, design hash unchanged) on all target development rows: train, V_A
  and V_B. Prior-game labels are features, and S4 needs the targets.
- **Label statistics: train rows only.** Coverage, prevalence, counts by cohort and by `P-20` membership, and gates
  G1–G7 re-reported as description, with no pass/fail and no consequence for the rules.
- **Validation rows:** labels and features are stored; only row counts are reported.
- **No score-versus-label metric of any kind in S3,** on any row. That includes `R-pre` and B-streak.
- **Feature description: train rows only.** Null rate and median per column, old cohort beside new cohort.
- **Holdout rows:** no label, no S3 feature row, no statistic. S5 builds their features with the code frozen in S3;
  the code hash is recorded in S3.

### S3.7 Gate (all must hold)

1. The whole test suite passes, including every test of S3.5.
2. The split integrity checks of S3.1 hold, and the split manifest is hashed.
3. Label regression: 100% agreement with S1 (S3.5 item 9); `rules_v3` design hash unchanged.
4. The F-pre table has one row per target development row; the F-p20 table has one row per target row of `P-20`.
5. The length probe triggers no stop, or the triggered columns have been decided on in writing.
6. Unchanged hashes: old features manifest `1ea2383b…`, holdout manifest `d21e5b02…`, new-root features manifest.

### S3.8 Deliverables

**Before any computation:** verify the lock of this document and record it in the report.

**Code (Codex):**
- `tilt/src/tilt/labels/split_v3.py`: development split, integrity checks, manifest.
- `tilt/src/tilt/features/prefix_v3.py`: F-pre and F-p20 builders, registry, length probe, CLI
  (`python -m tilt.features.prefix_v3`). It streams player by player; both data roots are opened read-only.
- `tilt/tests/unit/test_split_v3.py`, `tilt/tests/unit/test_prefix_v3.py`: the tests of S3.1 and S3.5.

**Outputs in `~/tilt-labels-v3/S3/` (outside the repo, never committed):**
- `dev_split_manifest.parquet` and its sha256;
- `labels_dev.parquet` (same columns as the S1 label files);
- `features_pre.parquet`, `features_p20.parquet`, `feature_registry.csv`;
- `length_probe.json`, `s3_gate.json`, `code_hash.txt` (sha256 of the two modules and of `rules_v3.py`).

**Report:** `tilt/reports/label_v3_S3.md` with the split table, the registry summary, the train-only label
description, the probe table, test results, deviations and the gate verdict.

**Computation.** No heavy job is expected. Codex runs the unit tests and a smoke build on at most 5 players. The
operator runs the full build: in WSL if the smoke run extrapolates to under 30 minutes and under 4 GB of RAM,
otherwise on the rented box. Training stays in S4.

### S3.9 S3 must not

1. Train or fit any model on v3 labels, or compute any score-versus-label metric.
2. Build labels, features or statistics for A′, B′ or `drop_shared_*` rows.
3. Change `rules_v3` constants, the holdout manifest, either data root's processed files, `lila/`, or v1/v2 code.
4. Select or drop features by looking at labels. The length probe may only trigger a stop.
5. Commit or push.

§8 applies unchanged. In particular, Codex stops before computing anything on real data if: a listed source column
does not exist; the group-B dynamics cannot be computed on a 20-ply game by the existing code; a prior game overlaps
the start of g in more than 0.5% of target rows; or the player identifier differs in form between the two roots.

### S3.10 Lock
The sha256 before this addendum is kept in `~/tilt-labels-v3/prereg.sha256.v3`. The sha256 including it is written
to `~/tilt-labels-v3/prereg.sha256` and is the lock from here on.

## Erratum 3 (S3 preflight)

Recorded after the S3 preflight stopped under S3.9 on the overlap rule. The preflight was count-only: nothing was
implemented, split, labelled or featurised. This erratum changes no LF, threshold, gate, split rule, feature family
or holdout membership.

### E3.1 What the preflight found
Over the 52,332 candidate targets (old 36,389, new 15,943):

| Definition | Rows | Share |
|---|---|---|
| any in-session prior with `end_upper_ms ≥ start_ms(g)` | 546 | 1.043% |
| the immediate prior only, same test | 110 | 0.210% |
| any in-session prior with a known true `end_ms ≥ start_ms(g)` | 30 | 0.057% |

`end_upper_ms` is the pipeline's conservative upper bound when the true end is unknown or uncertain. Most of the
546 rows are therefore uncertain ends, not real overlaps.

### E3.2 The stop measure (corrects S3.9)
- The 0.5% threshold is unchanged. **The measure changes:** it counts target rows with an in-session prior whose
  known true `end_ms ≥ start_ms(g)`. That is 0.057%, so the stop does not trigger.
- Reason: the rule was meant to catch games that really overlap. It was worded with the upper bound by mistake.
- The upper-bound count (546 rows, 1.043%) is reported beside it in `label_v3_S3.md`, by cohort.

### E3.3 Model-side session history (clarifies S3.3, S3.4)
- Define **S′(g)** = the games of S(g) with `end_upper_ms < start_ms(g)`, most recent first.
- **Every model-side quantity uses S′(g), never S(g).** This covers all of F-pre: L(g), the loss counts, D(g), the
  session rating delta, the gaps, C1–C5, `n_C`, the context rank, `prev_lost`, the previous-game features and the
  session means. It also covers `R-pre`.
- **The model's g−1 is the first element of S′(g),** i.e. the latest in-session prior that had surely ended.
- A game left out of S′(g) is simply absent: it neither counts as a loss nor stops the loss-run scan.
- gap(g) on the model side is `start_ms(g) − end_ms` of the model's g−1, and is null unless that end is exact (E1.4).
- Baselines already use `end_upper_ms < start_ms(g)` (§1.3) and do not change.
- Existing history columns (`losing_streak_before`, `rest_gap_seconds`, `recent_form`, `rematch_streak_before`) are
  used as the pipeline stores them. Codex reports whether each one applies the same end-before-start condition; a
  column that does not is listed under "Deviations" and stays out of the model matrix until decided.

### E3.4 Label side is unchanged
- Labels keep using S(g) by `start_ms`, as in §1.2 and as computed in S1. The label regression test (S3.5 item 9)
  stays at 100%.
- On about 1% of rows the model's context can therefore differ from the label's context. This is accepted: the
  label is allowed to see more than the model, and the model must use only what had surely ended.
- Add to the S3 report: the number of target rows where the model-side context rank differs from the label-side
  context level, for train rows only.

### E3.5 Known residual (accepted, to be stated in the report)
- Stored labels and E states of prior games are used as features as they are. The label of an included prior x was
  computed from S(x) by `start_ms`, which can contain a game whose `end_upper_ms` lies after `start_ms(g)`.
- That game started before x and x had ended before g, so in reality it had ended too, except in true overlaps
  (0.057% of rows). No correction is applied.

### E3.6 Tests (adjusts S3.5)
- Item 3, truncation equivalence: "games that ended before `start_ms(g)`" means `end_upper_ms < start_ms(g)`. The
  real-data sample for this test is drawn from target rows whose player has no prior game, in any session, with
  `end_upper_ms ≥ start_ms(g)`; fixtures cover the general case for direct inputs.
- New item 10: a fixture with an uncertain-end prior and one with a true-overlap prior. Both priors are absent from
  every F-pre value and from `R-pre`; changing their result, moves or end time leaves F-pre(g) byte-identical.

### E3.7 Content hashes (replaces S3.7 item 6)
- Finding: `features/manifest.json` records parameters only, and its sha is the same in both roots (`1ea2383b…`).
  It cannot detect a change of content. The S2 gate's "existing root unchanged" check had the same weakness and
  cannot be redone after the fact; this is stated in the S3 report as a limitation.
- **Before any S3 build,** record for each root the sha256 of every `features/*.parquet` file, sorted by file name,
  in `~/tilt-labels-v3/S3/features_content_old.sha256` and `features_content_new.sha256`.
- S3.7 item 6 becomes: both content-hash files are identical before and after S3, and the holdout manifest sha is
  still `d21e5b02…`.

### E3.8 Lock
The sha256 before this erratum is kept in `~/tilt-labels-v3/prereg.sha256.v4`. The sha256 including it is written
to `~/tilt-labels-v3/prereg.sha256` and is the lock from here on.

## Erratum 4 (S3 build, before any feature is written)

Recorded after the S3 full build stopped on its own guard "P-20 must have exactly physical plies 1..20". At that
point the split (sha `f0677cb8…`) and the development labels existed, and the S1 label regression was exact
(22,316/22,316 and 25,403/25,403). No feature table had been written. This erratum changes no LF, threshold, gate,
split rule, feature family or holdout membership. The split manifest and `labels_dev.parquet` are not regenerated.

### E4.1 The defect
- In both roots, some physical games have move rows for one colour only (only odd or only even plies). Their
  normalized `plies` is correct (20–137 among the affected P-20 games); the games are complete, the moves table is
  not.
- Operator's count-only diagnosis: 41 physical games with `plies ≥ 20` (16 old, 25 new). As rows: train 20, V_A 9,
  V_B 5 (34 development targets), A′ 7, B′ 0. Of the 49,881 P-20 targets, 662 have at least one such game in their
  prefix reference window.
- The diagnosis counted move rows on holdout games. It read no label, feature or score; it is recorded here as a
  deviation from S3.9 item 2.
- The cause in the pipeline is not investigated in S3, and neither data root is modified.

### E4.2 Definition
A game has a **complete prefix** when its `plies ≥ 20` and a move row exists for every ply 1–20. A game with
`plies ≥ 20` and no complete prefix has an **incomplete prefix**. The one-colour pattern (exactly the 10 odd or the
10 even plies present) is the only incomplete pattern this erratum handles. Any other pattern still raises and
stops the build under §8.

### E4.3 Targets (decision: drop, as in Erratum 2)
- A development target with an incomplete prefix gets the status `drop_incomplete_moves`. It is not a target: it
  enters no train or validation set and no feature table, for either head.
- The status is not written into the split manifest. The builder derives it and writes
  `excluded_incomplete_moves.csv` (game id, player, part, cohort, plies, colour present), hashed in `s3_gate.json`.
- Expected count: 34 (train 20, V_A 9, V_B 5). If the builder finds a different number, it stops under §8.
- Their stored labels stay in `labels_dev.parquet` and the game stays in its player's history (E4.5).
- Reason for dropping instead of scoring with the `pre` head: the composite score of S3.2 is defined by `plies`
  alone, and an exception based on a dataset artifact would make the scored population depend on a storage defect.
- Games with `plies < 20` are not affected by this erratum: they never receive prefix features.

### E4.4 Prefix reference windows (clarifies S3.3 F-p20 item 5)
- The window is the last ≤ 200 prior games with a **complete prefix** and `end_upper_ms < start_ms(g)`; at least 5,
  else null. Prior games with an incomplete prefix are skipped, not counted.
- Report the number of P-20 targets whose window skipped at least one game (expected about 662), by part.

### E4.5 Everything else that reads moves
- **Rule:** wherever S3 code reads move rows of both colours, a game with an incomplete prefix is skipped. This
  covers F-p20 of g, the prefix reference windows, the opponent's prefix CPL, the position after ply 20, and the
  P3-B@20 scoring of a game cut at ply 20.
- **F-pre is unchanged.** It reads no prefix of any game. Its previous-game and session features use the stored E
  values, states and labels, and its baseline descriptors use the stored per-game aggregates through the pooled
  window of §1.3, where null values already drop out.
- **Label side is unchanged,** as computed and as verified against S1.
- Codex reports, count only and by cohort: how many one-colour games exist in total, how many have `plies < 20`,
  and in how many the colour present is the cohort player's own. If the own moves are the missing ones in any game
  that carries a TILT or NOT label, Codex stops under §8.

### E4.6 Holdouts
- S5 applies E4.2–E4.5 to A′ and B′ with the code frozen in S3. Holdout rows with an incomplete prefix are dropped
  as targets and their count is reported (expected: A′ 7, B′ 0).

### E4.7 Tests and gate
- New tests: a one-colour game with `plies ≥ 20` is excluded as a target and listed in the exclusion file; it is
  skipped in a later game's prefix reference window; it remains in F-pre history; another incomplete pattern raises.
- S3.7 item 4 becomes: the F-pre table has one row per target development row after E4.3; the F-p20 table has one
  row per remaining target with `plies ≥ 20`, each with a complete prefix.
- S3.5 item 6 is unchanged and must now pass on every remaining P-20 row.

### E4.8 Lock
The sha256 before this erratum is kept in `~/tilt-labels-v3/prereg.sha256.v5`. The sha256 including it is written
to `~/tilt-labels-v3/prereg.sha256` and is the lock from here on.

## Erratum 5 (length probe decision)

Recorded after the S3 full build reached the length probe, which stopped for a decision under S3.5. This is the
written decision required by S3.7 item 5. No model has been fitted on v3 labels and no score-versus-label metric
exists. This erratum changes no LF, threshold, gate, split, feature table or holdout membership.

### E5.1 What the probe found (train rows only)
- Five single-feature stops, all in F-pre, all for the target `plies < 20`:

  | Column | AUC |
  |---|---|
  | `rating` | 0.759 |
  | `baseline_cpl_mean_w300_median` | 0.727 |
  | `baseline_blunders_per20_median` | 0.723 |
  | `baseline_blunders_per20_mad` | 0.713 |
  | `baseline_cpl_mean_w300_mad` | 0.706 |

- For `plies < 40` nothing reaches 0.70 (highest: `rating` 0.684).
- F-p20 triggered no stop, on AUC or on null-rate difference.
- Multi-feature probes (report only): pre `< 20` about 0.745; pre `< 40` about 0.679; p20 `< 40` 0.667–0.701.

### E5.2 Decision: accept all five stops; no column is dropped or transformed
- These columns are not leakage. Each is computed only from games that ended before g, and the baselines use the
  pooled window, so none depends on g's length by construction. They predict short games because weaker players
  have more of them (Phase 4 already found this).
- The S3 gate decision file lists the five as `accepted_stops` for block F-pre at the `plies < 20` threshold, with
  the `probe_sha` of the `length_probe.json` of this build. The feature tables stay as built; no rebuild.
- Columns just under 0.70 triggered no stop and need no entry. They are covered by E5.3 as a family.

### E5.3 The remaining risk and how it is controlled
The risk is indirect: v3 labels correlate with length (S1 G1: 0.633 / 0.640), so a model could score well by using
skill level as a stand-in for "short game". Dropping columns would hide this instead of measuring it. It is measured:

- **Skill-level family** = `rating` plus every baseline descriptor median and MAD of S3.3 F-pre item 6 (7 statistics
  × 2). The window size and the opponent rating difference are not in the family.
- **B-skill** (new comparator) = the skill-level family alone, under the two-head protocol of S3.2 with the same
  columns in both heads, trained like every other candidate.
- **M-v3-ns** (new reference) = M-v3 without the skill-level family.
- **Adoption rule, one condition added:** ΔPR-AUC of M-v3 against B-skill has a CI lower bound > 0 on both A′ and
  B′. This joins the comparators of the first adoption condition as it stands under the current lock. It is
  stricter than before and removes nothing.
- M-v3 itself is unchanged: it keeps every F-pre and F-p20 column, as fixed in S3.3. M-v3-ns is reported beside it
  and does not decide adoption.

### E5.4 Binding on S4 (to be repeated in the S4 addendum)
1. Train and report B-skill and M-v3-ns on validation, with every other candidate.
2. Report every candidate on V_A and V_B in three length strata: `plies < 20`, 20–39, ≥ 40.
3. Report, for each candidate's composite score, the ROC AUC for `plies < 20` and for `plies < 40` on validation
   (the score's own length shortcut), beside the same figure for B-skill.
4. No feature is added to or removed from M-v3 on the basis of these reports. They are description; the adoption
   rule decides.

### E5.5 Lock
The sha256 before this erratum is kept in `~/tilt-labels-v3/prereg.sha256.v6`. The sha256 including it is written
to `~/tilt-labels-v3/prereg.sha256` and is the lock from here on.

## Addendum S4 (after S3, before any model is fitted on v3 labels)

Recorded after S3 passed its gate 13/13. The user approved S4 on 2026-11-17. No model has been fitted on v3 labels
and no score-versus-label metric exists on any row. This addendum changes no LF, threshold, label, split, feature
table, holdout membership or adoption condition.

Inputs, all frozen in S3: `labels_dev.parquet` (`5070069a…`), `features_pre.parquet` (`07c542f1…`),
`features_p20.parquet` (`78691dfd…`), the split manifest (`f0677cb8…`), `excluded_incomplete_moves.csv`
(`e3f1bf17…`), and the code hashes `prefix_v3.py` `71b92e6e…`, `split_v3.py` `f426e792…`, `rules_v3.py` `9f2d8234…`.

### S4.0 Points that refine an approved section (for the user's acknowledgement)

| # | Approved text | This addendum | Reason |
|---|---|---|---|
| 1 | S3.2: the composite is "what M-v3 and each retrained comparator mean" | P3-B/v3 has one head on `P-all`, not two | Its features are whole-game values that exist for every game; there is no prefix version of it to switch to. |
| 2 | §7: "Gate: M-v3 beats `R-pre` on validation" | exact form in S4.5: Δ > 0 on V_A and on V_B, and a CI lower bound > 0 on the pooled validation | §7 gave no metric or interval. |
| 3 | §7: "Platt calibration on the unrebalanced validation set" | validation metrics use cross-fitted Platt; the frozen bundle uses Platt fitted on all validation rows (S4.4) | Otherwise the S4 gate would be scored on the rows the calibration was fitted on. |
| 4 | not stated | no refit on train + validation before S5 (S4.7) | A refitted model could not be calibrated or checked on any untouched development row. |

None of these changes the adoption rule of S3.4 and E5.3.

### S4.1 Rows
- **Targets** = development rows with a split part of train, V_A or V_B, minus `excluded_incomplete_moves.csv`.
- **Fitting and metrics use labelled targets only** (TILT = 1, NOT = 0). ABSTAIN rows are scored but enter no fit
  and no metric.
- `P-all` and `P-20` are as in S3.2 and E4.2.

### S4.2 Model class (one class, no tuning)
- Every fitted model is `core.train.tree_models('xgboost', seed=42, threads=2, trees=100)[0]`, exactly as P3-B:
  depth 3, learning rate 0.06, subsample 0.85, column sample 0.85, `hist`, `reg_lambda` 3.
- **No hyperparameter search, no early stopping, no feature selection, no second model class.** One fixed
  configuration keeps every candidate comparable with P3-B and leaves nothing to choose after seeing validation.
- Sample weights: `compute_sample_weight('balanced', y)` on that head's labelled train rows. Train only.
- Seed 42 everywhere.

### S4.3 Model matrices and missing values
- Matrix columns come from `prefix_v3.model_matrix(frame, head, candidate, excluded)` for `M-v3` and `P3-B@20`.
  M-v3-ns and B-skill are column subsets of the M-v3 matrix, selected by registry family (E5.3).
- Preprocessing, fitted on that head's labelled train rows only and then frozen: median imputation with
  `add_indicator=True` and `keep_empty_features=True`, then `StandardScaler`. This is the Phase 5 `Fitted` pipeline.
- Indicators are allowed here because the S3 length probe found no null-rate difference by length in F-p20, and
  nulls in F-pre mean pre-game facts (no previous game in the session, no baseline yet, no exact gap).
- P3-B/v3 uses exactly the Phase 5 P3-B configuration: its 11 features, indicators for all but the three group-B
  columns.

### S4.4 Candidates, heads and calibration

| Candidate | Role in S5 | Columns | Heads |
|---|---|---|---|
| M-v3 | candidate | all F-pre; all F-p20 | `pre` on `P-all`, `p20` on `P-20` |
| M-v3-ns | reference | M-v3 without the skill-level family | two heads |
| B-skill | adoption comparator | the skill-level family (15 columns), same in both heads | two heads |
| P3-B/v3 | adoption comparator | P3-B's 11 whole-game features (S4.6) | one head on `P-all` |
| P3-B@20/v3 | reference | `model_matrix(..., 'P3-B@20')` | two heads |
| P3-B frozen | reference | deployed bundle on the whole-game table (S4.6) | no fit |
| P3-B@20 frozen | reference | deployed bundle on the game cut at ply 20, `P-20` rows only | no fit |
| `R-pre`, B-streak | adoption comparators | S3.4, E3.3 | no fit |
| B-length, B-result | reference | S3.4 | no fit |

**Calibration (fitted candidates only).**
- Platt scaling through the existing `core.train.calibrate`, one fit per head, on that head's labelled validation
  rows, V_A and V_B pooled. The `pre` head is calibrated on `P-all`, the `p20` head on `P-20`.
- The `pre` head is not recalibrated for games under 20 plies. Their length is unknown when the `pre` score is
  issued, so the composite may under-predict in that stratum. This is reported, not corrected.
- **Cross-fitting for validation metrics.** Fold of a player = `int(sha256("label-v3-cal-fold-1:" + player id), 16)
  mod 2`. A validation row's calibrated score comes from the Platt fit on the other fold. Every validation metric and
  the S4 gate use these out-of-fold scores.
- **Frozen calibration for S5.** One Platt fit per head on all labelled validation rows. It is stored in the bundle
  and is the only calibration applied to A′ and B′.
- Composite score = calibrated `p20` score when `plies ≥ 20`, else calibrated `pre` score (S3.2).
- Unfitted scores are ranked as they are; they get no calibration, Brier or ECE.
- ECE and reliability bins: the existing `phase1.calibration_bins`, unchanged. The report states its binning rule.

### S4.5 Validation report and gate

**Report, for every candidate, on V_A, on V_B and pooled:**
- PR-AUC with prevalence, ROC AUC; Brier and ECE for fitted candidates;
- the same in the strata `plies < 20`, 20–39, ≥ 40, and in `< 40` / `≥ 40`;
- for two-head candidates, the `pre` head alone on `P-all` and the `p20` head on `P-20`;
- ROC AUC of each composite score for `plies < 20` and for `plies < 40`, beside B-skill's (E5.4);
- paired ΔPR-AUC of M-v3 against each of P3-B/v3, `R-pre`, B-streak and B-skill, with 95% intervals. This is a
  preview only: adoption is decided in S5 on A′ and B′.
- Train-row PR-AUC of each fitted head, to show the train–validation gap.

**Bootstrap.** Player-clustered and paired, 1,000 resamples, seed 42, percentile 95% interval, using the existing
`phase5.bootstrap` logic. A resample with no positive row is skipped and counted.

**Gate (all must hold):**
1. PR-AUC of the M-v3 composite minus PR-AUC of `R-pre` is > 0 on V_A and > 0 on V_B.
2. On V_A and V_B pooled, the 95% interval of that difference has a lower bound > 0.
3. Every Platt fit of M-v3 and of the adoption comparators reports the normal fitted status.
4. Determinism (S4.8) holds.
5. The leakage tests of S3.5 still pass, and the M-v3 matrices contain no column of the whole-game table (S4.6).

**If item 1 or 2 fails:** S4 stops and reports. There is no fallback variant and no second attempt with other
settings. P3-B stays deployed and the user decides whether S5 still runs as a description.

### S4.6 Whole-game P3-B features (for P3-B/v3 and P3-B frozen only)
- One table, `features_p3b_whole.parquet`, for every development target: `initial_seconds`, `increment_seconds`,
  `risk_rate`, `attack_rate`, `defensive_rate`, `style_switch_rate`, `rematch_streak_before`,
  `baseline_risk_rate_games`, `attack_trend_3w`, `risk_volatility_3w`, `behavior_change_point`.
- **One code path for both roots:** the feature computation of the deployed scorer (`core/score.py`,
  `core/deployment.py`) applied to the whole game. No Phase 5 table is copied, so old and new rows are built alike.
- **Parity check.** For every old row that is also in the Phase 5 `by_player` tables, the 11 values equal the
  Phase 5 values within 1e-9 (nulls equal nulls). Any mismatch stops S4 under §8.
- A game with an incomplete prefix is already excluded as a target (E4.3). A one-colour game under 20 plies keeps
  whatever the deployed code returns for it.
- **Isolation.** This table is label-only data under §1.4. A test asserts that no M-v3, M-v3-ns, B-skill or
  P3-B@20 matrix contains any of its whole-game columns, and that `v3_train` never joins it to them.
- P3-B frozen applies the deployed bundle (`cbd7a3f9…`) to this table as it is, with the bundle's own calibration.
  The deployment pointer `deployed.json` is read, never written.

### S4.7 Frozen bundles for S5
- **No refit on train + validation.** Each fitted candidate is frozen as trained on train rows, with the frozen
  calibration of S4.4.
- One bundle per fitted candidate: column lists per head, imputer, scaler, classifier and Platt parameters per
  head, the code hashes, and the lock of this document. Each bundle's sha256 is written to `bundles.sha256`.
- S5 scores A′ and B′ with these bundles and nothing else. No decision threshold is fixed in S4: adoption needs
  none, and a deployment threshold would be set in a separate addendum if M-v3 is adopted.

### S4.8 Compute and determinism
- Training does not run on the user's machine. The operator runs the full S4 on the rented box or on Colab; the
  job is small (about a dozen fits of 100 trees on at most 19,102 rows, plus 1,000 resamples).
- **Two complete runs** in separate processes, into `run1/` and `run2/`. Required: every prediction and metric file
  is identical (largest absolute difference 0.0) and every bundle sha256 is equal. Otherwise S4 stops.
- Codex runs the unit tests and a smoke fit on synthetic data only. Codex does not fit on real labels.

### S4.9 Deliverables

**Before any computation:** verify the lock of this document and the S3 input hashes listed above.

**Code (Codex):**
- `tilt/src/tilt/evaluation/v3_p3b.py`: the whole-game table and its parity check.
- `tilt/src/tilt/evaluation/v3_train.py`: matrices, fitting, cross-fitted and frozen calibration, composite,
  metrics, bootstrap, gate, bundles, determinism comparison, CLI (`python -m tilt.evaluation.v3_train`).
- `tilt/tests/unit/test_v3_p3b.py`, `tilt/tests/unit/test_v3_train.py`, covering at least:
  - only labelled train rows enter a fit; only validation rows enter a calibration;
  - the fold rule, and that no row is calibrated by a fit that saw it;
  - the composite switches on `plies ≥ 20` only;
  - the column subsets of M-v3-ns and B-skill match the registry family;
  - the isolation test of S4.6;
  - A′, B′, `drop_shared_*` and `drop_incomplete_moves` rows are refused everywhere;
  - the bootstrap is clustered by player and reproducible for seed 42;
  - two runs on the synthetic fixture give identical outputs.

**Outputs in `~/tilt-labels-v3/S4/run1/` and `run2/` (outside the repo, never committed):**
- `features_p3b_whole.parquet`, `p3b_parity.json`;
- `predictions.parquet` (raw and calibrated scores per candidate and head, all target rows);
- `metrics_validation.json`, `bootstrap_validation.json`, `length_auc.json`;
- `bundles/*.joblib`, `bundles.sha256`, `code_hash.txt`, `s4_gate.json`;
- `~/tilt-labels-v3/S4/determinism.json`.

**Report:** `tilt/reports/label_v3_S4.md` with the candidate table, the validation tables by part and stratum, the
length-shortcut table, the paired differences, the parity and determinism results, deviations and the gate verdict.

### S4.10 S4 must not
1. Read, label, featurise or score any A′ or B′ row, or build the whole-game table for one.
2. Tune, search, select features, add a model class, or refit after any validation number has been seen.
3. Use validation rows for anything except calibration, the reports of S4.5 and the gate.
4. Change labels, the split, the S3 feature tables, `rules_v3`, `prefix_v3`, `split_v3`, either data root,
   `deployed.json`, the deployed bundle, `lila/`, or v1/v2 code.
5. Commit or push.

§8 applies unchanged. A bug found after validation numbers are seen is fixed, re-run, and both sets of numbers are
reported. Codex stops before any real-data fit if: the parity check fails; a column named in S4.6 cannot be produced
by the deployed feature code for new rows; `model_matrix` returns a column that is not in the registry; or a head
has fewer than 50 positive labelled train rows.

### S4.11 Lock
The sha256 before this addendum is kept in `~/tilt-labels-v3/prereg.sha256.v7`. The sha256 including it is written
to `~/tilt-labels-v3/prereg.sha256` and is the lock from here on.

## Erratum 6 (S4 run 1, before any validation number)

Recorded after the first S4 `train` run stopped with "Missing unfitted reference score". The five fitted bundles
had been written, but no metric, report or gate existed and no validation value had been seen. This erratum changes
no LF, threshold, label, split, feature table, fitted candidate, gate or adoption condition.

### E6.1 The finding
- 364 of the 52,239 target rows have a null `result_score` in `labels_dev.parquet` (train 251, V_A 62, V_B 51).
  Their status is `outoftime` 326, `timeout` 29, `insufficientMaterialClaim` 9. Labels: ABSTAIN 191, NOT 163,
  TILT 10.
- The source records no winner for these games. On Lichess they are draws: a flag or an abandonment against
  insufficient mating material, or a claimed draw. The pipeline left the result null.
- S3.4 defines B-result as `1 − result_score`, which is null on these rows. `R-pre`, B-streak and B-length have
  no null.

### E6.2 Decision
- **For B-result only, a null `result_score` counts as a draw (0.5), so B-result = 0.5 on these rows.** The
  formula of S3.4 is otherwise unchanged, and B-result is scored on the same rows as every other candidate.
- Reason: the games are draws, so this fills in the true value. Scoring B-result on fewer rows would make its
  figures incomparable with the others; switching to the Phase 1 binary form would change a registered formula.
- B-result stays a reference: it is in no gate and in no adoption condition.
- The same rule applies to A′ and B′ in S5.

### E6.3 What does not change
- **Labels.** `rules_v3` already treats a null result as neither a loss nor a win: it is skipped in the loss-run
  scan, adds nothing to the loss counts, and makes E6, E7 and the won-game rule not apply. That is the treatment of
  a draw, so the frozen labels are consistent with E6.2. They are not recomputed.
- **Features.** F-pre and F-p20 stay as built in S3. A null previous-game result goes through the imputation of
  S4.3 like any other null.
- **Rows.** No row is dropped or added.
- The report states the 364 rows by part, status and label, and that the pipeline's missing draw result is a known
  defect of the normalisation step, not fixed here.

### E6.4 Re-run
- The stopped run is kept unchanged as `run1_failed_attempt1/`. Its bundles were never evaluated and are not used.
- Codex makes the minimal change in `v3_train.py` (B-result fill) and adds a test: a null result gives B-result
  0.5, and no other score or matrix changes.
- The operator then runs the whole S4 script from the start in fresh directories: the whole-game table, the parity
  check, both complete runs and the determinism comparison. The bundles of the new `run1/` are the frozen ones.
- The stop and this erratum are listed under "Deviations" in `label_v3_S4.md`.

### E6.5 Lock
The sha256 before this erratum is kept in `~/tilt-labels-v3/prereg.sha256.v8`. The sha256 including it is written
to `~/tilt-labels-v3/prereg.sha256` and is the lock from here on.

## Addendum S5 (after S4, before any holdout row is labelled, featurised or scored)

Recorded after S4 passed its gate. The user chose on 2026-11-17 to run S5 before any deployment decision. No label,
S3 feature row, whole-game row or score exists for any A′ or B′ row. This addendum changes no LF, threshold, label
rule, feature definition, bundle or holdout membership. A deployment addendum is written only after the S5 result.

### S5.0 Points that settle an ambiguity (for the user's acknowledgement)

| # | Locked text | This addendum | Reason |
|---|---|---|---|
| 1 | §5 and Addendum S2: "S5 adoption is judged on the length strata only"; §7: CI condition, then "Δ > 0 in both length strata" | The CI condition is evaluated inside each length stratum (≥ 40 and < 40 plies). All-games figures are reported and do not decide (S5.6). | v3 failed G1, so an all-games comparison can be won through game length. §7 did not say where the CI applies once the standing consequence holds; this is the only reading that satisfies both texts. |
| 2 | §7: "Δ > 0 in both length strata", comparators not named | Against all four adoption comparators: P3-B/v3, `R-pre`, B-streak, B-skill. | E5.3 put B-skill among "the comparators of the first adoption condition"; under row 1 that condition is the stratum condition. |
| 3 | §7: "ECE ≤ 0.05", rows not named | M-v3 composite on all labelled rows of A′ and of B′, not per stratum. | It is a calibration check, not a comparison; stratum ECE would be too noisy to decide anything. |
| 4 | S3.6: "S5 builds their features with the code frozen in S3" | Through a new module that calls the frozen functions unchanged, proven equal on development rows (S5.2). | The frozen code refuses holdout rows by design and must not be edited. |

The other reading of row 1 (CI on all games, point Δ > 0 in the strata) is not used.

### S5.1 Inputs (verified by hash before anything runs)
- This document's lock; the holdout manifest `d21e5b02…`; `excluded_sides.csv` `0ce5efcd…`.
- Frozen code: `rules_v3.py` `9f2d8234…` (design hash `6393da7f…`), `prefix_v3.py` `71b92e6e…`, `split_v3.py`
  `f426e792…`, and `v3_train.py` and `v3_p3b.py` at the hashes recorded in the accepted S4 `run1/code_hash.txt`.
- S3 tables `labels_dev` `5070069a…`, `features_pre` `07c542f1…`, `features_p20` `78691dfd…`; the S4 run 1
  `features_p3b_whole.parquet` and `predictions.parquet`.
- The fitted bundles in `~/tilt-labels-v3/S4/run1/bundles/`, each against `bundles.sha256`; the deployed P3-B bundle
  `cbd7a3f9…`.
- Both data roots, read-only, against the content hashes of E3.7.

### S5.2 Holdout targets and how the frozen code is used
- **Targets** = manifest rows with assignment A′ or B′ (9,665 and 4,989), minus rows with an incomplete prefix
  (E4.2–E4.3). Erratum 2 sides are already absent from the manifest. Expected incomplete drops: A′ 7, B′ 0.
- A holdout row is never dropped for sharing a game with another row: S2.4 keeps the holdout side.
- **New module only.** `tilt/src/tilt/evaluation/v3_holdout.py` imports `rules_v3`, `prefix_v3`, `split_v3`,
  `v3_train` and `v3_p3b` and calls their existing functions. It does not edit, copy, patch at run time or
  re-implement them. Where a frozen function refuses holdout assignments, the S5 module hands it the holdout rows
  as plain target rows in its own frame; every computation on those rows stays inside the frozen functions.
- Each player's full history is processed as in S3: all their games in the root, with only the holdout rows as
  targets. For B′ rows the earlier development games are history, as S2.4 and S3.1 intend.
- All rules already locked apply unchanged: S′(g) on the model side (E3.3), exact gaps (E1.4), prefix reference
  windows of complete prefixes (E4.4), the both-colours rule (E4.5), the B-result fill (E6.2).
- **Equivalence check (must pass before any holdout row is touched).** The S5 path rebuilds, for every development
  target, the labels, F-pre, F-p20, the whole-game P3-B table and every candidate's raw and calibrated score. Each
  must equal the S3 and S4 run 1 tables exactly: same rows, same columns, nulls equal nulls, largest absolute
  difference 0.0. Any difference stops S5 under §8.

### S5.3 Whole-game P3-B table for holdout rows
- Built through the S4.6 code path, for holdout targets only.
- No Phase 5 parity is possible: every holdout row belongs to a new-cohort player. The proof that the code path is
  the right one is the development equivalence of S5.2, which reproduces the table that passed S4 parity.
- The isolation rule of S4.6 holds: this table is never joined to an M-v3, M-v3-ns, B-skill or P3-B@20 matrix.

### S5.4 Scoring
- Fitted candidates are scored only with the frozen S4 run 1 bundles and their frozen all-validation Platt
  parameters. **No fit, no recalibration, no threshold, no feature change.**
- Composite score as in S3.2: the calibrated `p20` score when `plies ≥ 20`, else the calibrated `pre` score.
  P3-B/v3 has its single head.
- Unfitted scores as defined: `R-pre` (S3.4 with E3.3), B-streak, B-length, B-result (with E6.2).
- P3-B frozen and P3-B@20 frozen as in S4.4.
- ABSTAIN rows are scored and enter no metric.

### S5.5 Metrics (labelled rows; A′, B′, and pooled)
- For every candidate: PR-AUC with prevalence, ROC AUC; Brier and ECE for fitted candidates (existing
  `phase1.calibration_bins`).
- Strata: all, `plies < 20`, 20–39, ≥ 40, < 40.
- For two-head candidates: the `pre` head alone on `P-all`, the `p20` head on `P-20`.
- ROC AUC of each composite score for `plies < 20` and for `plies < 40`, beside B-skill's (E5.4).
- Paired ΔPR-AUC of M-v3 against every other candidate, in every stratum.
- **Bootstrap.** Player-clustered and paired, 1,000 resamples, seed 42, percentile 95% interval, the existing
  `phase5.bootstrap` logic. Within a stratum, a resample with no positive or no negative row is skipped and counted.
- Rows and TILT counts per part and stratum; rows by label; counts of the incomplete-prefix drops.

### S5.6 Adoption rule (final form)
M-v3 is **adopted** only if every item holds **on A′ and on B′ separately**:

1. **Stratum comparison.** For each stratum (`plies ≥ 40`, `plies < 40`) and each adoption comparator (P3-B/v3,
   `R-pre`, B-streak, B-skill): the 95% interval of PR-AUC(M-v3 composite) − PR-AUC(comparator) on the labelled
   rows of that stratum has a lower bound > 0. That is 8 cells per part, 16 in all.
2. **Estimability.** A cell with fewer than 30 TILT rows, or with more than 10% of its resamples skipped, counts
   as not met.
3. **Calibration.** ECE of the M-v3 composite on all labelled rows of the part is ≤ 0.05.

- The point difference being > 0 in both strata (§7) follows from item 1 and is reported for the record.
- All-games and pooled figures, the `plies < 20` and 20–39 strata, and all references (M-v3-ns, P3-B@20/v3, P3-B
  frozen, P3-B@20 frozen, B-length, B-result) are reported and do not decide.
- **If any item fails:** M-v3 is not adopted, P3-B stays deployed, and the report lists every failed cell. What
  happens next is the user's decision; any use of M-v3 after a failed S5 is an explicit override, recorded as such.
- **If all hold:** M-v3 is adopted in principle. Nothing is switched on by S5: the pointer, thresholds and display
  rules need the deployment addendum and the user's approval.

### S5.7 One shot
- **Phases, in order, in one script:** `verify` (S5.1) → `equivalence` (S5.2, development rows only) → `build`
  (holdout labels, features, whole-game table; counts only) → `score` → `evaluate` (metrics, bootstrap, decision).
- **Two complete runs** in separate processes into `run1/` and `run2/`, started by the same script without anyone
  reading run 1 first. Required: every output file is identical and the decision is the same. The decision file is
  written only after this comparison passes.
- **Before `evaluate` has produced any number,** S5 stops under §8 on any of:
  - a hash of S5.1 does not match;
  - the equivalence check shows any difference;
  - the incomplete-prefix drops are not exactly A′ 7 and B′ 0, or an incomplete pattern other than one-colour
    appears, or the own-colour stop of E4.5 fires;
  - target counts differ from 9,658 for A′ or 4,989 for B′;
  - a holdout target lacks a label row or an F-pre row, or a `P-20` target lacks an F-p20 row;
  - a prior game with a known true end after `start_ms(g)` occurs in more than 0.5% of holdout targets (E3.2).
  A stop at this point is resolved by an erratum, and the run starts again from `verify`.
- **Once `evaluate` has produced any number,** there is no re-run with a changed setting, rule, feature, bundle or
  row set. The only permitted re-run is a crash fix that provably changes no computed value: every file already
  written must be reproduced identically, and both sets of files are kept.
- After S5, A′ and B′ are open. No later model may be evaluated on them as untouched data.

### S5.8 Who does what
- **Codex** writes `v3_holdout.py` and `tilt/tests/unit/test_v3_holdout.py`, and tests on synthetic fixtures only.
  It may run the equivalence phase on at most 5 development players as a smoke test. It never opens, labels,
  featurises or scores a holdout row, and never runs `build`, `score` or `evaluate` on real data.
- **The operator** runs the script on the rented box. The S4 package there already holds both roots, the v3 inputs
  and the deployed bundle; the S4 run 1 bundles, `predictions.parquet` and `features_p3b_whole.parquet` are added.
- Tests cover at least:
  - the frozen modules are imported unchanged and their hashes are checked at start;
  - holdout rows reach the frozen functions as targets, and development rows are never targets in `build`;
  - the equivalence comparison fails on a one-value change and on a null/non-null change;
  - no fit or calibration function is called in S5;
  - the composite switch, the E6.2 fill and the isolation rule of S4.6;
  - the stratum bootstrap, its skip count, and the estimability rule;
  - the adoption function on synthetic tables: one failing cell gives "not adopted";
  - two runs on the synthetic fixture give identical outputs.

### S5.9 Outputs and report
**Outputs in `~/tilt-labels-v3/S5/run1/` and `run2/` (outside the repo, never committed):**
- `verify.json`, `equivalence.json`;
- `labels_holdout.parquet`, `features_pre_holdout.parquet`, `features_p20_holdout.parquet`,
  `features_p3b_whole_holdout.parquet`, `excluded_incomplete_moves_holdout.csv`;
- `predictions_holdout.parquet`;
- `metrics_holdout.json`, `bootstrap_holdout.json`, `length_auc_holdout.json`;
- `~/tilt-labels-v3/S5/determinism.json` and `adoption.json`.

**Report:** `tilt/reports/label_v3_S5.md` with the input hashes, the equivalence result, the target and exclusion
counts, the full metric tables by part and stratum, the 16 deciding cells with their intervals, the ECE values, the
length-shortcut table, deviations, and the adoption verdict. It repeats the limitation of §0: the result says how
well M-v3 predicts the v3 rule early, not how well it measures emotion.

### S5.10 S5 must not
1. Fit, refit, recalibrate, tune or choose a threshold on any row.
2. Edit a frozen module, a bundle, the manifest, either data root, `deployed.json`, `lila/`, or v1/v2 code.
3. Print or report any holdout label or score statistic before `evaluate`.
4. Change the adoption rule, the strata, the comparators or the row set after a holdout number exists.
5. Commit or push.

§8 applies unchanged.

### S5.11 Lock
The sha256 before this addendum is kept in `~/tilt-labels-v3/prereg.sha256.v9`. The sha256 including it is written
to `~/tilt-labels-v3/prereg.sha256` and is the lock from here on.

## Erratum 7 (S5 preflight, before any S5 code and before any holdout row is opened)

Recorded after Codex stopped under §8 before writing S5 code. No holdout row had been opened, labelled, featurised
or scored. The user has acknowledged S5.0 as written. This erratum changes no LF, threshold, label rule, feature
definition, bundle, holdout membership, metric or adoption condition.

### E7.1 Equivalence scope (corrects S5.2)
- **Finding.** In the S4 run 1 `predictions.parquet`, the `::calibrated` columns of fitted candidates are the
  cross-fitted Platt scores of S4.4, produced by two fold models per head. Those fold models were never stored. Each
  bundle holds only the all-validation Platt fit, which produced the `::frozen` columns and is the only calibration
  S5 applies (S5.4). Reproducing `::calibrated` would need a new Platt fit, which S5.10 item 1 forbids.
- **Decision.** The score part of the equivalence check compares, for every development target and exactly
  (largest absolute difference 0.0, nulls equal nulls):
  - every fitted candidate's `::raw` and `::frozen` columns, for each head and for the composite;
  - every column of the unfitted scores and of the deployed references.
- The cross-fitted `::calibrated` columns of fitted candidates are **excluded** from the comparison. They are not
  recomputed, not copied and not used anywhere in S5.
- The rest of S5.2 stands: labels, F-pre, F-p20 and the whole-game P3-B table must still match exactly.
- **Why this is sufficient.** The chain bundle → features → raw score → frozen Platt is exactly the S5 scoring path,
  so equality on `::raw` and `::frozen` proves the path that scores the holdouts. The excluded columns belong to a
  validation-only procedure that S5 never runs.
- `equivalence.json` lists every compared column and every excluded column by name. A column that is neither
  compared nor on the excluded list stops S5 under §8.
- In S5, "calibrated score" (S3.2, S5.4) means the score under the frozen all-validation Platt fit. The S4
  predictions file is not modified.

### E7.2 A frozen S4 test that pins the previous lock
- **Finding.** `tests/unit/test_v3_p3b.py::test_frozen_s3_files_and_real_document_are_unchanged` asserts that this
  document's sha256 equals the S4-era lock `851858bc…`. Appending Addendum S5 makes it fail by construction. The
  test file is part of the frozen S4 code hash and may not be edited. The suite is otherwise green: 531 passed,
  2 skipped.
- **Decision.**
  - The S5 suite runs with this one test deselected by its node id. The node id, the reason and the suite counts
    are written to `test_evidence.json`. No other test may be deselected, skipped anew or marked as expected to fail;
    any other failure stops S5.
  - A new S5 test asserts the same property in append-only form:
    - the snapshot `~/tilt-labels-v3/S4/prereg_at_S4/` hashes to `851858bc…`;
    - the current document begins with that snapshot byte for byte;
    - the current document hashes to the current lock;
    - the frozen S3 files and the frozen S4 modules hash to their recorded values.
  - Wherever frozen S4 code needs "the pre-registration at its lock", it is given the S4 snapshot, as S4 did with
    the S3 snapshot.
- The same rule applies to any later append to this document: a frozen test that pins an earlier lock is replaced
  by an append-only test, never edited, and listed by node id.

### E7.3 Lock
The sha256 before this erratum is kept in `~/tilt-labels-v3/prereg.sha256.v10`. The sha256 including it is written
to `~/tilt-labels-v3/prereg.sha256` and is the lock from here on.

## Erratum 8 (S5 operator run 1, crash in `equivalence`, before any holdout row is built and before any metric)

Recorded after operator run 1 stopped on 2026-11-17 04:34 UTC at lock `e01d5130…`, with `v3_holdout.py` at
`2225bed0…`. This erratum changes no LF, threshold, label rule, feature definition, bundle, holdout membership,
comparison scope, metric or adoption condition. It corrects a loader of the S5 module and records one deviation.

### E8.1 What happened
- `verify` passed and wrote `run1/verify.json`. The suite passed (575 passed, 2 baseline skips, the one deselection
  of E7.2; 44 new tests).
- `equivalence` crashed in `development_headers` with a pandas `MergeError`: the header frame had duplicate
  (cohort, player, game, colour) keys.
- No `equivalence.json` exists. `build`, `score` and `evaluate` did not start. No holdout move, label, feature or
  score was read or computed, and no number about a holdout row was written or printed.

### E8.2 Cause
- For the new cohort the loader read `features/games.parquet` with two independent filters: player in the
  development players, and game in the set of games readable by any of them. That is a cross product, not a filter
  on (player, game) pairs.
- Take a physical game with one side of development player p1 (assignment `drop_shared_development`, history
  only) and the other side of player p2 with assignment B′, p2 also having development rows. The game is readable
  for p1, and p2 is in the player list, so the first read also returned p2's B′ side.
- The boundary read used the same cross product on the B′ games. It returned p2's B′ side a second time and p1's
  side of that game, which the code then tagged B′. Hence the duplicate keys.
- The smoke run of S5.8 could not see this: it uses old-cohort players, who have no holdout rows.

### E8.3 Deviation recorded
- Before the crash, header columns of the B′ sides described in E8.2 were held in process memory: the bridge
  columns, `session_id`, `end_ms`, `speed` and the stored history columns. S5.2 intended no holdout value to be
  read before the equivalence check passed, apart from the boundary metadata of E8.4.
- Bound: at most 16 sides, the number of new-cohort `drop_shared_development` rows; fewer if some of those games
  have their holdout side in A′. The exact count is reported by the key check of E8.6.
- Nothing was computed from these values, written or shown. The process ended with the crash. A′ and B′ are
  therefore still unopened for S5.7, and the one-shot rule is not consumed.
- The deviation is listed in the S5 report.

### E8.4 Loader rule (corrects the S5 module, not a frozen module)
For every read of a per-side table in the `verify` and `equivalence` phases:
1. **Pair-level selection.** The rows returned are exactly a stated set of (player, game, colour) sides. A side of
   another player is never returned because it shares a game id with a wanted side.
2. **Value read.** Header values are read only for sides whose assignment is not A′ or B′: `development`,
   `drop_shared_development`, old-cohort rows, and new-cohort history rows outside the manifest.
3. **Boundary read.** For a development player, the only holdout sides read are that same player's own B′ sides, and
   only the columns `start_ms` and `session_id` (the next-game boundary that S3 used for the label side). The
   assignment of each boundary row is taken from the manifest; it is not assigned by the code. A boundary row
   whose manifest assignment is not B′, or whose player is not the development player being processed, stops S5.
4. **Assertions inside the loader**, each stopping S5 under §8:
   - the header frame has unique (cohort, player, game, colour) keys before any merge;
   - no A′ side appears anywhere in the equivalence phase;
   - every B′ side in the frame is a boundary row and has nulls in every column except its keys, `start_ms`,
     `session_id` and assignment;
   - the non-holdout sides in the frame equal, as a set, the sides expected for the same players from key columns
     and the manifests alone (every stored side of the player that is not A′ or B′, minus Erratum 2 sides). The frozen
     S3 header loader is not called in `equivalence`, because it reads the header values of every row.
5. **Moves** stay per physical game, as in S3. The moves of a game are read when the player being processed has a
   non-holdout side in it. That includes the `drop_shared_development` games, which are history of their own
   player (S3.1). This is unchanged from S3 and is not a holdout read.
6. **`build`** keeps using the frozen S3 header loader. The S5 module adds no reader of its own there. Before any
   computation `build` asserts unique keys and that the target set equals the manifest A′ and B′ sides, minus the
   incomplete-prefix drops.
7. `equivalence.json` gains a `headers` block with counts only: sides per assignment, boundary rows, shared games,
   and the result of each assertion.

### E8.5 Tests added (synthetic fixtures only)
- A game shared by a development side (`drop_shared_development`) and a B′ side, where the B′ player also has
  development rows. This is the case that crashed.
- Games shared B′ with B′, A′ with B′, and A′ with development.
- An old-cohort and a new-cohort `drop_shared_development` row.
- For each: unique keys; the B′ side carries only boundary metadata in `equivalence`; no A′ side in `equivalence`;
  both holdout sides are targets in `build` (S5.2); the development side is never a target in `build`.
- A fixture where the boundary read would return another player's side must stop.
- The old cross-product reader, kept only inside the test as a reference, must fail the new assertions.

### E8.6 Key check on real data (extends S5.8)
- Codex may run one check on the real roots that reads **key columns only**: `player`, `game_id` and `color` of
  `features/games.parquet`, plus the keys and assignments of the two manifests. It reads no value column of any
  row.
- From the keys it derives the read plan of E8.4 for all development players and asserts: unique keys, no holdout
  side in the value read, and boundary sides equal to the own B′ sides of each development player.
- It writes counts only to `~/tilt-labels-v3/S5/header_plan.json`, including the E8.3 count.
- Everything else in S5.8 stands. Codex still runs the value path on at most 5 development players, never runs the
  full equivalence, and never runs `build`, `score` or `evaluate` on real data.

### E8.7 Restart
- This is a stop "before `evaluate` has produced any number" (S5.7). The run starts again from `verify`.
- The crashed outputs are kept, not deleted: on the box they move to `v3/S5/operator_attempt1_crash/`; the local
  copy is `~/tilt-labels-v3/S5/operator_attempt1_crash/`.
- The new package holds the corrected `v3_holdout.py`, its tests, this document and the new lock. The hash of the
  module before (`2225bed0…`) and after is written to `verify.json` and to the report.
- `run1/` and `run2/` are both produced by the new package. No file of the crashed attempt is reused.

### E8.8 Later crashes before `build`
- A crash in `verify` or `equivalence` caused by the S5 module's own code is fixed and recorded as a deviation in
  the S5 report: log kept, module hash before and after, restart from `verify`. It needs no new erratum, provided
  that no locked rule, row set, comparison scope or assertion of E8.4 changes and that no holdout value was read
  beyond E8.4 item 3.
- If either condition fails, or the stop happens in `build` or later, an erratum is required as S5.7 says.
- A difference found by the equivalence comparison is not a crash. It stops S5 under §8 and needs an erratum.

### E8.9 Lock
The sha256 before this erratum is kept in `~/tilt-labels-v3/prereg.sha256.v11`. The sha256 including it is written
to `~/tilt-labels-v3/prereg.sha256` and is the lock from here on.
