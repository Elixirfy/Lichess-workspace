# Label v3 — I0 deployment specification (M-v3 on the local lila site)

Status: **draft for the user's approval** (2026-11-17).
Author: Claude (operator). Fable 5.2 was unavailable without usage credits, and the user chose to have the
operator write I0. The decisions D1–D8 were made by Fable and approved by the user on 2026-11-17. This
document turns them into an implementable specification and adds no new modelling.

Authority:
- S5 adopted M-v3 in principle (`~/tilt-labels-v3/S5/adoption.json`, all 16 cells met).
- On 2026-11-17 the user stopped all model-improvement work and asked for the best model on the web.
- After approval, the operator (Claude) implements I1–I3 directly, without further planning rounds.

## 1. What is deployed
- **Model:** `M-v3` from `~/tilt-labels-v3/S4/run1/bundles/M-v3.joblib`, sha256 `9ebc9730c6e00ee26c51f012259c02f10eb276501744fe1d8137c3b6855baae5`.
  - It has two heads: `pre` (73 inputs) and `p20` (104 inputs).
  - The score is the frozen all-validation Platt probability from `predict_bundle`. There is no refit and no
    recalibration.
- **Composite:** the `p20` head when the game has at least 20 plies; otherwise the `pre` head (S4 `composite`).
- **Frozen code reused unchanged:** `features/prefix_v3.py` (`71b92e6e…`), `labels/rules_v3.py` (`9f2d8234…`),
  `labels/split_v3.py` (`f426e792…`), the S3 `feature_registry.csv`, and `evaluation/v3_train.py` (`ee8c3ca0…`)
  for `predict_bundle`, `matrix` and `composite`.
- **Pointer:** `processed/models/deployed_v3.json` in the worker's models root. It names:
  - the bundle path and its sha256;
  - the registry path and its sha256;
  - the bands of §4 and the source run (S4 run1 / S5).

  The worker refuses to start on any hash mismatch. **Rollback:** delete `deployed_v3.json` and restart the
  worker. Scoring then returns to P3-B (`deployed.json`, unchanged), and lila shows the previous UI for
  responses without `v: 3`.
- The bundle and registry are copied into the models root inside WSL. Nothing under `tilt/data` leaves WSL.

## 2. Eligibility (D1)
- lila still queues the same games as today: standard, with a clock, no AI, `playedPlies > 1`, human players
  only.
- The worker scores **blitz only**: the `speed` of the feature row must be `blitz`, the speed M-v3 was trained
  on. For any other speed it writes `skip: "speed"` with no score, no level, no signs and no banner contribution.
  The UI says that only blitz games are scored.
- A game of 20 or more plies whose first 20 plies hold moves of only one colour (the E4 pattern) gets
  `skip: "incomplete"`, the same exclusion as S3–S5.
- Games under 20 plies are scored with the `pre` head. The UI says that this score uses only the context before
  the game.
- A draw recorded without a result counts as a draw (0.5), as in `rules_v3` and Erratum 6.

## 3. Live pipeline (I1)
1. `collect → analyze → compute` stay as they are. The engine settings must match the trained data
   (settings key `ca2f1c3a…`, the same `features/manifest.json`).
2. **Live headers:** the player's rows from `features/games.parquet`, plus `status`, `plies`, `rated`, the
   time control and ratings from the normalized games. The columns are exactly those `split_v3.load_headers`
   produces. Every row is a plain history/target row (`assignment = development`, `part = train`, as in the S5
   adapter). Raw ids serve as the export ids.
3. **Features:** `prefix_v3.build_player(..., 'features')` for the target game. Excluded history columns are as in S3.
4. **Score:** composite frozen probability (§1).
5. **Rule check:** `prefix_v3.build_player(..., 'labels')` for the same game. Labels and fired C/E rules are
   shown as computed.
   - E7 depends on the next game, so it is `missing` (shown as "pending") until the player's next game is
     processed.
   - When the worker processes a player's game, it recomputes the rule check of that player's previous scored
     blitz game and updates that document.
6. **Shadow:** the current P3-B path (`score.run`) still runs. Its `score` and `flag` go into `response.shadow`,
   which is never shown. The shadow runs for 14 days after the pointer switch; then it is turned off and a
   descriptive comparison is written.

### Response (written by the worker, read by lila)
New fields are optional, so old documents and rollback keep working:
```
response.pred = {
  score, flag, factors,        # kept: score = round(100·prob), flag = prob ≥ 0.30
  v: 3, prob, level,           # level: "low" | "attention" | "high"   (§4)
  head: "pre" | "p20",
  signs: [{family, share}],    # §5, at most 3
  fast:  {z, zTrim, games},    # only when §6 holds
  rules: {context, label, fired, pending}   # context: none|stale|weak|strong; fired/pending: rule ids
}
response.skip   = "speed" | "incomplete"   # instead of pred
response.shadow = {model: "P3-B", score, flag}
```

## 4. Levels (D6)
| Level | Probability | Holdout A′ / B′ share of games | TILT rate among labelled rows (A′ / B′) |
|---|---|---|---|
| low | < 0.10 | 73.8% / 71.7% | 1.3% / 1.3% |
| attention | 0.10–0.30 | 17.0% / 17.8% | 18.6% / 17.5% |
| high | ≥ 0.30 | 9.2% / 10.5% | 45.3% / 42.7% |

Validation S4 at 0.30 gave precision 0.45 and recall 0.49. Holdout gave precision 0.453 / 0.427 and recall
0.460 / 0.486. These numbers are descriptive: the bands were fixed before S5 and are not changed.

## 5. "Early signs the model saw" (D4, part 1)
- **Unit:** per-feature contributions of the scoring head, the XGBoost `pred_contribs` margin terms (SHAP).
  They are summed by registry `family`.
- **Shown:** at most 3 families, each with a share of at least 10% of the absolute positive contribution, strongest
  first.
- **Never shown as a reason:**
  - the `meta` family (time control, ratings, colour);
  - the 15 skill columns of B-skill.

  These still count in the score.
- **Text:** every family has a fixed Vietnamese and English description in `TiltText.scala`. For example,
  `previous` = "how your previous game in this session went", `session` = "the length of this session and recent
  losses", `prefix_z` = "how the first 20 plies compare with your usual play". The UI says these are patterns
  the model used, not proof of an emotion.

## 6. "Faster than your usual pace" (D5)
The reason is shown only when all of these hold:
- the game used the `p20` head;
- the model input `p20_z_think_frac_median` is ≤ −1.5;
- the prefix reference window has at least 20 blitz games;
- `z_trim` is ≤ −1. It is the same z computed after dropping each game's first 4 own moves, in the target and
  in every reference game. This keeps instant book moves from counting as haste.

Notes:
- The number shown is the model input (z, one decimal).
- `think_frac` divides think time by `initial + 40·increment`, and the reference holds blitz games only. So
  "fast" means fast compared with the player's own blitz pace, never compared with bullet.
- `z_trim` only hides the reason. It never changes the score.

## 7. "Post-game rule check" (D4, part 2)
- **Shown:** the v3 rule outcome (TILT / NOT / not decided), the context level, and each fired rule in words:
  - C1 losing streak;
  - C2 three of five or five of ten lost;
  - C3 decaying loss load;
  - C4 session rating drop of 30 or more;
  - C5 shrinking breaks;
  - E1 accuracy drop;
  - E2 blunders;
  - E3 hurried moves;
  - E4 erratic timing;
  - E5 aggression;
  - E6 early resignation or abandonment;
  - E7 instant re-queue after a loss (pending until the next game).
- **Between games (D3):** only this transparent context is used. The `pre` head is never shown on its own.

## 8. Banner (D7)
- **Shown** on the lobby/home page to the logged-in player when either holds:
  - the last two scored blitz games of the player were both `high`;
  - or the last one was `high` and its context level was `strong`.
- **Limits:**
  - at most once per session;
  - at least 30 minutes between banners;
  - the player can dismiss it;
  - an opt-out switch on `/account/tilt` turns it off for good.
- **Text:** a suggestion to take a short break, with the reason ("2 games in a row" / "after a run of losses")
  and a link to the Tilt page.
- **Never** shown during a game (D2). Nothing in the round UI changes while a game is running.

## 9. Pages (D4, D8)
- **Game tab "Tilt"** (only for the player of that game, after the game): level and meter, early signs (§5), the
  fast reason (§6) when it holds, the rule check (§7), and the notice "predicts the v3 behaviour rule, does not
  measure emotion".
- **`/account/tilt` statistics:**
  - the number of scored blitz games and the share at each level, for the last 30 days and the last 50 games;
  - the most frequent early-sign families;
  - how often the rule check said TILT;
  - the list of recent games with their level;
  - the banner opt-out switch.
- **Language:** all text is in Vietnamese and English via `TiltText.scala`, following the page language, without
  crowdin. The existing English-only text is replaced.

## 10. Privacy
- Only the player sees their scores.
- Deleting the user deletes the documents (existing `UserDelete` subscription), including banner state.
- No raw data, salt or `tilt/data` leaves WSL.

## 11. Stage gates (operator implements; each gate is checked before the next stage)
- **I1 worker:** `core/live_v3.py`, the worker changes and unit tests.
  - **Parity:** for ≥ 20 development players (both cohorts, games under and over 20 plies), the live header,
    feature and score path on the stored roots must reproduce the S3 `features_pre`/`features_p20` rows and the S4
    M-v3 composite `::frozen` scores **exactly** (max |diff| 0, nulls equal). The rule-check path must reproduce
    `labels_dev` for the same players.
  - Unit tests: speed skip, one-colour skip, null-result draw, the §5 filter, the §6 conditions, E7 pending and
    update, the response schema, and pointer hash checks.
  - Full suite passes.
  - The one-colour defect is also checked: how many live-root games ≥ 20 plies have only one colour in the first
    20 plies. This affects P3-B today, because the old pipeline did not exclude them. It is reported only.
- **I2 lila:** `Pred` gains the optional fields; banner state lives in collection `tilt_banner`
  (`_id` = user, `shownAt`, `optOut`); there is a new `TiltText.scala`, the game tab, the account page and the
  lobby banner. scalafmt, compile and module tests must pass; `./ui/build -n` and the lints pass if any UI asset
  changes.
- **I3 end-to-end (Playwright):** run on the local site with test accounts `coach[a-d]xxxx`:
  - a blitz game gets scored;
  - a non-blitz game is skipped;
  - the tab, stats page, banner, dismissal and opt-out work, in VI and EN.

  Everything is then deleted: the accounts, their games, `tilt_queue` and `tilt_banner` documents, and the
  worker data rows of those accounts.
- **Switch:** write `deployed_v3.json`, restart the worker, keep the P3-B shadow for 14 days, and record the date
  in CLAUDE.md. Nothing is committed unless the user asks.

## Code layout update (2026-11-22)

The package was reorganised by role. Only import lines and path strings changed; scoring all 122 local games
(60 M-v3, 62 P3-B) before and after gave byte-identical results.

| Before | After |
|---|---|
| `core/formulas.py`, `core/engine.py` | `common/` |
| `core/train.py`, `core/sequence.py`, `evaluation/v3_train.py` | `training/` |
| `core/score.py`, `core/deployment.py`, `core/live_v3.py`, `workers/lila_worker.py` | `service/` |

New frozen hashes (`FROZEN` in `service/live_v3.py`; the first three also in `evaluation/v3_p3b.py`):
`features/prefix_v3.py` `92c6d277…`, `labels/rules_v3.py` `86fcd9c1…`, `labels/split_v3.py` `f426e792…`
(unchanged), `data/cohort_v3.py` `08f33a44…` (unchanged), `training/v3_train.py` `d5af618d…`,
`evaluation/v3_p3b.py` `00f137e0…`. The hashes above in this document and in the pre-registration describe the
code as evaluated, before the move.
