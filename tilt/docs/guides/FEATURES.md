# Behavioural feature dictionary (section 2.3)

All feature outputs are deterministic, contain no label columns, and retain missingness.
The separate [weak-label model](../research/WEAK_LABELS.md) consumes a conservative predictor
allowlist and writes only separate weak-label artifacts. It never changes these
feature tables or the human label store. LF inputs and their raw-quantity relatives
are excluded; the original mixed BDS is displayed but not used as a predictor.
Groups: **1** move quality; **2** time management; **3** style/risk; **4** response to adverse events;
**5** cross-game/session; **6** personal baseline; **7** context/audit metadata.
Table `games` has one row per player–game; `moves` one per ply for known players;
`windows` one trailing N-board-ply window per target move; `events` one player/event anchor;
`sessions` one player/session. Identifiers and timestamps are metadata, not predictors.

`N=12`, minimum prior games `=5`, session inactivity gap `=30 min` by default; all configurable.
Only same-player games with **end_upper_ms < current game start_ms** enter history.
Game baselines match speed. Move baselines also match clock_pressure and advantage_state.
`--max-history-games K` defaults to **200**, must be positive, and selects the K most recent
eligible same-player/speed games ordered by `(end_upper_ms, game_id)` **before** filtering
move contexts or missing values. The same cap applies to normal-CPL recovery thresholds
and dataset session baselines (strictly before session start). No older values fill missing contexts.
K is stored as `max_history_games` in feature/export manifests and in the data card.
Move-value pools are built once per game; medians/MADs/counts are prepared once per
capped history/context and row similarity fractions use sorted-value binary searches.
Cross-game history counts, losing/rematch streaks and session membership keep their original
uncapped definitions; a time sweep maintains them without rescanning full move history.
There is no fallback to population values. History medians/MADs use nonmissing observations;
move history pools moves, but minimum history counts distinct games rather than move count.
SD is population SD (one valid value gives 0); means/SD of no observed values are missing.
Rates are fractions unless explicitly percentages. No future opponent reply is used to assign an offer/risk feature.

Window/event tables are retrospective and expose `available_after_ply`. A window contains only own moves
whose board ply is in its interval. An adverse own move is excluded from both surrounding windows.
An adverse opponent move is anchored at the previous ply, so the first response is in the post-window.
Game and session aggregates are available only after their entire scope; moment dataset joins never use whole-game aggregates.
Recovery can need the rest of the game and is marked censored/missing explicitly.

Raw schemas are in `src/tilt/data/storage.py`, API semantics in `docs/architecture/API_SEMANTICS.md`, and human label schema in
`src/tilt/labels/labels.py`. Human targets, survey answers, annotator/source/delay fields are never generated here.
The build-dataset manifest supplies a numerical/categorical predictor allowlist; use it instead of all numeric columns.
Internal feature tables retain raw game/session/player identifiers for local display and joins.
Every dataset table in `out/` exports game ids as HMAC-SHA256(salt, `"game:" + id`) and
session ids as HMAC-SHA256(salt, `"session:" + id`), preserving game-id case. User and
annotator identifiers are HMAC pseudonyms. Opponent usernames/ids, `previous_game_id`
and raw session game lists are omitted. Shared-game purging uses internal membership
before writing; pseudonymisation does not prevent reidentification from timing/behaviour.
The label app permits consent/self-reports only for the OAuth-verified account; experts
also authenticate and can select only consented players. Current consent version is
`draft-research-v2-oauth`; legacy v1 consents require owner re-consent and do not
authorise new expert ratings. Existing labels retain their original provenance. PKCE verifier/state stay server-side;
account access tokens are revoked immediately after identity lookup and never persisted.
Salt fingerprints use HMAC(salt, `"tilt-salt-fingerprint-v1"`), with transparent legacy migration.
Dump collectors enforce a staging/disk budget (default 5 GiB); collect-dump requires users or a limit.

Style, complexity and event thresholds are transparent research heuristics requiring validation, not psychological measurements.

| Name | Group | Granularity/table | Unit | Definition | Source |
|---|---:|---|---|---|---|

| `accuracy` | 1 | moves | percent [0,100] | Lichess exponential move accuracy on WinPercent percentage-point loss, with uncertainty bonus +1 and clamps. Missing when either eval is absent. | `lila/modules/analyse/src/main/AccuracyPercent.scala; tilt/formulas.py move_accuracy` |
| `accuracy_std` | 1 | games, windows | percentage points | Arithmetic mean/population standard deviation of move accuracy; differs from weighted/harmonic game_accuracy. | `tilt/features.py` |
| `advantage_state` | 7 | moves | category | Mover winning if winning chances >= .3524 (~200 cp), losing if <= -.3524, equal otherwise, unknown if missing. State before/after respectively. | `tilt/features.py move_features; winningChances.ts uses .3524 for 200 cp-equivalent` |
| `adverse_event` | 4 | moves | boolean | Any blunder, loss of advantage/material, missed win/mate, or opponent advantage transition. | `tilt/features.py` |
| `adverse_events` | 4 | games, windows | count | Count of target-player response rows marked adverse_event in aggregation; separate event-table anchors may be more numerous. | `tilt/features.py` |
| `after_own_blunder` | 4 | moves | boolean | Previous own move was a blunder; marks first subsequent own response. | `tilt/features.py` |
| `attack` | 3 | moves | 0/1 | Capture, check, or moved piece attacks a square within Chebyshev distance 1 of enemy king. Broad attacking proxy. | `tilt/features.py` |
| `attack_rate` | 3 | games, windows | fraction [0,1] | Mean of the corresponding move flag (realized_sacrifice_rate uses unsound_sacrifice_realized). Missing flags excluded. | `tilt/features.py` |
| `available_after_ply` | 7 | events, windows | ply | One-based played ply; inclusive window bounds; event anchor; or earliest conservative ply after which the entire output is available. Opponent-event anchors are previous ply. | `tilt/features.py` |
| `baseline_accuracy_games` | 6 | moves | games count | accuracy: Distinct eligible prior games with observed values for this feature; per-feature minimum is checked. | `tilt/features.py robust` |
| `baseline_accuracy_mad` | 6 | moves | percent [0,100] | accuracy: Median absolute deviation about historical median, unscaled; same eligibility/minimum as median. | `tilt/features.py robust` |
| `baseline_accuracy_median` | 6 | moves | percent [0,100] | accuracy: Median historical observations, only when per-feature minimum prior-game count is met. | `tilt/features.py robust` |
| `baseline_attack_rate_games` | 6 | games | games count | attack_rate: Distinct eligible prior games with observed values for this feature; per-feature minimum is checked. | `tilt/features.py robust` |
| `baseline_attack_rate_mad` | 6 | games | fraction [0,1] | attack_rate: Median absolute deviation about historical median, unscaled; same eligibility/minimum as median. | `tilt/features.py robust` |
| `baseline_attack_rate_median` | 6 | games | fraction [0,1] | attack_rate: Median historical observations, only when per-feature minimum prior-game count is met. | `tilt/features.py robust` |
| `baseline_blunder_rate_games` | 6 | games | games count | blunder_rate: Distinct eligible prior games with observed values for this feature; per-feature minimum is checked. | `tilt/features.py robust` |
| `baseline_blunder_rate_mad` | 6 | games | fraction [0,1] | blunder_rate: Median absolute deviation about historical median, unscaled; same eligibility/minimum as median. | `tilt/features.py robust` |
| `baseline_blunder_rate_median` | 6 | games | fraction [0,1] | blunder_rate: Median historical observations, only when per-feature minimum prior-game count is met. | `tilt/features.py robust` |
| `baseline_cpl_games` | 6 | moves | games count | cpl: Distinct eligible prior games with observed values for this feature; per-feature minimum is checked. | `tilt/features.py robust` |
| `baseline_cpl_mad` | 6 | moves | centipawns [0,1000] | cpl: Median absolute deviation about historical median, unscaled; same eligibility/minimum as median. | `tilt/features.py robust` |
| `baseline_cpl_median` | 6 | moves | centipawns [0,1000] | cpl: Median historical observations, only when per-feature minimum prior-game count is met. | `tilt/features.py robust` |
| `baseline_cpl_std_games` | 6 | games | games count | cpl_std: Distinct eligible prior games with observed values for this feature; per-feature minimum is checked. | `tilt/features.py robust` |
| `baseline_cpl_std_mad` | 6 | games | centipawns | cpl_std: Median absolute deviation about historical median, unscaled; same eligibility/minimum as median. | `tilt/features.py robust` |
| `baseline_cpl_std_median` | 6 | games | centipawns | cpl_std: Median historical observations, only when per-feature minimum prior-game count is met. | `tilt/features.py robust` |
| `baseline_error_rate_games` | 6 | games | games count | error_rate: Distinct eligible prior games with observed values for this feature; per-feature minimum is checked. | `tilt/features.py robust` |
| `baseline_error_rate_mad` | 6 | games | fraction [0,1] | error_rate: Median absolute deviation about historical median, unscaled; same eligibility/minimum as median. | `tilt/features.py robust` |
| `baseline_error_rate_median` | 6 | games | fraction [0,1] | error_rate: Median historical observations, only when per-feature minimum prior-game count is met. | `tilt/features.py robust` |
| `baseline_immediate_after_loss_games` | 6 | games | games count | immediate_after_loss: Distinct eligible prior games with observed values for this feature; per-feature minimum is checked. | `tilt/features.py robust` |
| `baseline_immediate_after_loss_mad` | 6 | games | 0/1, nullable | immediate_after_loss: Median absolute deviation about historical median, unscaled; same eligibility/minimum as median. | `tilt/features.py robust` |
| `baseline_immediate_after_loss_median` | 6 | games | 0/1, nullable | immediate_after_loss: Median historical observations, only when per-feature minimum prior-game count is met. | `tilt/features.py robust` |
| `baseline_latest_end_ms` | 7 | games, moves | UTC epoch ms | Scope creation/start, estimated end, conservative end upper bound, or latest end admitted to baseline, respectively. Timestamp metadata; baseline_latest_end_ms must be strictly less than start_ms. | `tilt/normalize.py; tilt/features.py compute` |
| `baseline_mean_accuracy_games` | 6 | games | games count | mean_accuracy: Distinct eligible prior games with observed values for this feature; per-feature minimum is checked. | `tilt/features.py robust` |
| `baseline_mean_accuracy_mad` | 6 | games | percentage points | mean_accuracy: Median absolute deviation about historical median, unscaled; same eligibility/minimum as median. | `tilt/features.py robust` |
| `baseline_mean_accuracy_median` | 6 | games | percentage points | mean_accuracy: Median historical observations, only when per-feature minimum prior-game count is met. | `tilt/features.py robust` |
| `baseline_mean_cpl_games` | 6 | games | games count | mean_cpl: Distinct eligible prior games with observed values for this feature; per-feature minimum is checked. | `tilt/features.py robust` |
| `baseline_mean_cpl_mad` | 6 | games | centipawns | mean_cpl: Median absolute deviation about historical median, unscaled; same eligibility/minimum as median. | `tilt/features.py robust` |
| `baseline_mean_cpl_median` | 6 | games | centipawns | mean_cpl: Median historical observations, only when per-feature minimum prior-game count is met. | `tilt/features.py robust` |
| `baseline_mean_think_games` | 6 | games | games count | mean_think: Distinct eligible prior games with observed values for this feature; per-feature minimum is checked. | `tilt/features.py robust` |
| `baseline_mean_think_mad` | 6 | games | seconds | mean_think: Median absolute deviation about historical median, unscaled; same eligibility/minimum as median. | `tilt/features.py robust` |
| `baseline_mean_think_median` | 6 | games | seconds | mean_think: Median historical observations, only when per-feature minimum prior-game count is met. | `tilt/features.py robust` |
| `baseline_post_event_cpl_delta_games` | 6 | games | games count | post_event_cpl_delta: Distinct eligible prior games with observed values for this feature; per-feature minimum is checked. | `tilt/features.py robust` |
| `baseline_post_event_cpl_delta_mad` | 6 | games | centipawns | post_event_cpl_delta: Median absolute deviation about historical median, unscaled; same eligibility/minimum as median. | `tilt/features.py robust` |
| `baseline_post_event_cpl_delta_median` | 6 | games | centipawns | post_event_cpl_delta: Median historical observations, only when per-feature minimum prior-game count is met. | `tilt/features.py robust` |
| `baseline_post_event_think_delta_games` | 6 | games | games count | post_event_think_delta: Distinct eligible prior games with observed values for this feature; per-feature minimum is checked. | `tilt/features.py robust` |
| `baseline_post_event_think_delta_mad` | 6 | games | seconds | post_event_think_delta: Median absolute deviation about historical median, unscaled; same eligibility/minimum as median. | `tilt/features.py robust` |
| `baseline_post_event_think_delta_median` | 6 | games | seconds | post_event_think_delta: Median historical observations, only when per-feature minimum prior-game count is met. | `tilt/features.py robust` |
| `baseline_recovery_plies_games` | 6 | games | games count | recovery_plies: Distinct eligible prior games with observed values for this feature; per-feature minimum is checked. | `tilt/features.py robust` |
| `baseline_recovery_plies_mad` | 6 | games | board plies | recovery_plies: Median absolute deviation about historical median, unscaled; same eligibility/minimum as median. | `tilt/features.py robust` |
| `baseline_recovery_plies_median` | 6 | games | board plies | recovery_plies: Median historical observations, only when per-feature minimum prior-game count is met. | `tilt/features.py robust` |
| `baseline_rest_gap_seconds_games` | 6 | games | games count | rest_gap_seconds: Distinct eligible prior games with observed values for this feature; per-feature minimum is checked. | `tilt/features.py robust` |
| `baseline_rest_gap_seconds_mad` | 6 | games | seconds | rest_gap_seconds: Median absolute deviation about historical median, unscaled; same eligibility/minimum as median. | `tilt/features.py robust` |
| `baseline_rest_gap_seconds_median` | 6 | games | seconds | rest_gap_seconds: Median historical observations, only when per-feature minimum prior-game count is met. | `tilt/features.py robust` |
| `baseline_risk_games` | 6 | moves | games count | risk: Distinct eligible prior games with observed values for this feature; per-feature minimum is checked. | `tilt/features.py robust` |
| `baseline_risk_mad` | 6 | moves | 0/1 | risk: Median absolute deviation about historical median, unscaled; same eligibility/minimum as median. | `tilt/features.py robust` |
| `baseline_risk_median` | 6 | moves | 0/1 | risk: Median historical observations, only when per-feature minimum prior-game count is met. | `tilt/features.py robust` |
| `baseline_risk_rate_games` | 6 | games | games count | risk_rate: Distinct eligible prior games with observed values for this feature; per-feature minimum is checked. | `tilt/features.py robust` |
| `baseline_risk_rate_mad` | 6 | games | fraction [0,1] | risk_rate: Median absolute deviation about historical median, unscaled; same eligibility/minimum as median. | `tilt/features.py robust` |
| `baseline_risk_rate_median` | 6 | games | fraction [0,1] | risk_rate: Median historical observations, only when per-feature minimum prior-game count is met. | `tilt/features.py robust` |
| `baseline_speed_games` | 6 | games | games count | Number of definitely completed prior games, and same-speed subset. Not necessarily enough valid observations for every feature baseline. | `tilt/features.py` |
| `baseline_style_switch_rate_games` | 6 | games | games count | style_switch_rate: Distinct eligible prior games with observed values for this feature; per-feature minimum is checked. | `tilt/features.py robust` |
| `baseline_style_switch_rate_mad` | 6 | games | fraction [0,1] | style_switch_rate: Median absolute deviation about historical median, unscaled; same eligibility/minimum as median. | `tilt/features.py robust` |
| `baseline_style_switch_rate_median` | 6 | games | fraction [0,1] | style_switch_rate: Median historical observations, only when per-feature minimum prior-game count is met. | `tilt/features.py robust` |
| `baseline_think_seconds_games` | 6 | moves | games count | think_seconds: Distinct eligible prior games with observed values for this feature; per-feature minimum is checked. | `tilt/features.py robust` |
| `baseline_think_seconds_mad` | 6 | moves | seconds | think_seconds: Median absolute deviation about historical median, unscaled; same eligibility/minimum as median. | `tilt/features.py robust` |
| `baseline_think_seconds_median` | 6 | moves | seconds | think_seconds: Median historical observations, only when per-feature minimum prior-game count is met. | `tilt/features.py robust` |
| `baseline_think_std_games` | 6 | games | games count | think_std: Distinct eligible prior games with observed values for this feature; per-feature minimum is checked. | `tilt/features.py robust` |
| `baseline_think_std_mad` | 6 | games | seconds | think_std: Median absolute deviation about historical median, unscaled; same eligibility/minimum as median. | `tilt/features.py robust` |
| `baseline_think_std_median` | 6 | games | seconds | think_std: Median historical observations, only when per-feature minimum prior-game count is met. | `tilt/features.py robust` |
| `baseline_wc_loss_games` | 6 | moves | games count | wc_loss: Distinct eligible prior games with observed values for this feature; per-feature minimum is checked. | `tilt/features.py robust` |
| `baseline_wc_loss_mad` | 6 | moves | winning-chance difference [0,2] | wc_loss: Median absolute deviation about historical median, unscaled; same eligibility/minimum as median. | `tilt/features.py robust` |
| `baseline_wc_loss_median` | 6 | moves | winning-chance difference [0,2] | wc_loss: Median historical observations, only when per-feature minimum prior-game count is met. | `tilt/features.py robust` |
| `behavioral_deviation_score` | 6 | games, moves, sessions | score [0,100] | 10 * mean(min(10,abs(z))) over available deviation features. Missing if none; no population fallback, not a tilt label. Session feature table averages per-game BDS; labelled session export freezes games at report time and recomputes against only pre-session history. | `tilt/features.py robust/compute; tilt/dataset.py build_dataset` |
| `best_move` | 1 | moves | UCI string | Played move or best alternative at its BEFORE-position. Best from selected engine cache, falling back to API advice best; missing stays missing. | `tilt/features.py move_features; lila/modules/tree/src/main/Advice.scala` |
| `best_second_gap_cp` | 7 | moves | centipawns [0,2000] | Absolute gap between MultiPV first/second White scores after mate-to-cp conversion; missing without two PVs. Small gap means alternatives have similar eval, not a validated difficulty metric. | `tilt/engine.py; tilt/features.py move_features` |
| `blunder_rate` | 1 | games, windows | fraction [0,1] | Fraction of evaluated moves with any inaccuracy-or-worse, exactly mistake, or exactly blunder, respectively. | `tilt/features.py` |
| `capture` | 3 | moves | boolean or 0/1 | capture: move captures (including en passant); check: move gives check; defensive: mover was in check before move. Deterministic style proxies, not intention labels. | `python-chess Board; tilt/features.py move_features` |
| `check` | 3 | moves | boolean or 0/1 | capture: move captures (including en passant); check: move gives check; defensive: mover was in check before move. Deterministic style proxies, not intention labels. | `python-chess Board; tilt/features.py move_features` |
| `clock_anomaly` | 2 | moves | boolean | Clock delta plus increment < -0.1 seconds; likely added time or inconsistent history, spent time becomes missing. | `tilt/features.py` |
| `clock_config_mismatch` | 2 | moves | boolean | First observed own time differs from nominal initial by more than max(0.2 seconds,5%); without explicit berserk metadata a nonzero nominal increment is unknown (zero remains zero). | `tilt/features.py` |
| `clock_fraction` | 2 | moves | fraction, may exceed 1 | Remaining BEFORE-decision clock divided by observed initial own clock. Increment can make the ratio exceed 1. | `tilt/features.py` |
| `clock_missing_fraction` | 7 | games, windows | fraction [0,1] | Fraction of eligible own moves with missing think time. Excludes structurally unclocked first turns and observed zero-time/premove intervals from numerator and denominator; null when none are eligible. Invalid/gifted clock observations remain missing. | `tilt/features.py` |
| `clock_pressure` | 7 | moves | category | low if clock_fraction < .2, normal otherwise; unknown if missing. | `tilt/features.py` |
| `clock_seconds` | 2 | moves | seconds | Post-move remaining clock, previous own post-move clock (before current decision), and first observed own clock. Imported clocks are centiseconds divided by 100. | `tilt/features.py move_features; lila/modules/core/src/main/game/data.scala` |
| `color` | 7 | games, moves | identifier | Mover colour; internal join/audit metadata, never a predictor. | `tilt/features.py` |
| `consecutive_errors` | 1 | moves | own moves count | Consecutive own inaccuracy/mistake/blunder judgements; missing breaks a run. A known good move resets to zero. | `tilt/features.py` |
| `continued_error_rate` | 4 | events | fraction [0,1] | Fraction of evaluated target-player moves in post-event window judged inaccuracy/mistake/blunder. | `tilt/features.py` |
| `cpl` | 1 | moves | centipawns [0,1000] | max(0, mover-sign*(clamped_before_cp - clamped_after_cp)), capped 1000; mate maps to ±1000; either missing eval yields missing. | `tilt/features.py move_features; tilt/formulas.py as_cp; lila/modules/tree/src/main/eval.scala` |
| `cpl_change_after_loss` | 5 | games | centipawns | Current mean CPL minus latest definitely completed game mean CPL, only if that game was a loss. | `tilt/features.py` |
| `cpl_std` | 1 | games, windows | centipawns | Arithmetic mean and population standard deviation of observed move CPL within aggregation. Missing values excluded; entirely missing stays missing. | `tilt/features.py` |
| `cpl_volatility` | 5 | sessions | centipawns | Session population SD of player-game mean CPL; retrospective over the entire session. | `tilt/features.py` |
| `cpl_volatility_after_losses` | 5 | games | centipawns | Population SD of mean CPL over last five definitely completed games, only when preceding losing streak >=2. | `tilt/features.py` |
| `defensive` | 3 | moves | boolean or 0/1 | capture: move captures (including en passant); check: move gives check; defensive: mover was in check before move. Deterministic style proxies, not intention labels. | `python-chess Board; tilt/features.py move_features` |
| `defensive_rate` | 3 | games, windows | fraction [0,1] | Mean of the corresponding move flag (realized_sacrifice_rate uses unsound_sacrifice_realized). Missing flags excluded. | `tilt/features.py` |
| `deviation_accuracy_z` | 6 | moves | robust z | accuracy: (current - baseline_median)/max(1.4826*baseline_MAD,1.0). Positive means higher, not necessarily worse. Missing without minimum eligible history. | `tilt/features.py robust` |
| `deviation_attack_rate_z` | 6 | games | robust z | attack_rate: (current - baseline_median)/max(1.4826*baseline_MAD,0.05). Positive means higher, not necessarily worse. Missing without minimum eligible history. | `tilt/features.py robust` |
| `deviation_blunder_rate_z` | 6 | games | robust z | blunder_rate: (current - baseline_median)/max(1.4826*baseline_MAD,0.01). Positive means higher, not necessarily worse. Missing without minimum eligible history. | `tilt/features.py robust` |
| `deviation_cpl_std_z` | 6 | games | robust z | cpl_std: (current - baseline_median)/max(1.4826*baseline_MAD,1.0). Positive means higher, not necessarily worse. Missing without minimum eligible history. | `tilt/features.py robust` |
| `deviation_cpl_z` | 6 | moves | robust z | cpl: (current - baseline_median)/max(1.4826*baseline_MAD,1.0). Positive means higher, not necessarily worse. Missing without minimum eligible history. | `tilt/features.py robust` |
| `deviation_error_rate_z` | 6 | games | robust z | error_rate: (current - baseline_median)/max(1.4826*baseline_MAD,0.01). Positive means higher, not necessarily worse. Missing without minimum eligible history. | `tilt/features.py robust` |
| `deviation_feature_count` | 6 | games, moves | feature count | Number of valid z-scores contributing to Behavioral Deviation Score. | `tilt/features.py` |
| `deviation_immediate_after_loss_z` | 6 | games | robust z | immediate_after_loss: (current - baseline_median)/max(1.4826*baseline_MAD,0.05). Positive means higher, not necessarily worse. Missing without minimum eligible history. | `tilt/features.py robust` |
| `deviation_mean_accuracy_z` | 6 | games | robust z | mean_accuracy: (current - baseline_median)/max(1.4826*baseline_MAD,1.0). Positive means higher, not necessarily worse. Missing without minimum eligible history. | `tilt/features.py robust` |
| `deviation_mean_cpl_z` | 6 | games | robust z | mean_cpl: (current - baseline_median)/max(1.4826*baseline_MAD,1.0). Positive means higher, not necessarily worse. Missing without minimum eligible history. | `tilt/features.py robust` |
| `deviation_mean_think_z` | 6 | games | robust z | mean_think: (current - baseline_median)/max(1.4826*baseline_MAD,0.1). Positive means higher, not necessarily worse. Missing without minimum eligible history. | `tilt/features.py robust` |
| `deviation_post_event_cpl_delta_z` | 6 | games | robust z | post_event_cpl_delta: (current - baseline_median)/max(1.4826*baseline_MAD,1.0). Positive means higher, not necessarily worse. Missing without minimum eligible history. | `tilt/features.py robust` |
| `deviation_post_event_think_delta_z` | 6 | games | robust z | post_event_think_delta: (current - baseline_median)/max(1.4826*baseline_MAD,0.1). Positive means higher, not necessarily worse. Missing without minimum eligible history. | `tilt/features.py robust` |
| `deviation_recovery_plies_z` | 6 | games | robust z | recovery_plies: (current - baseline_median)/max(1.4826*baseline_MAD,1.0). Positive means higher, not necessarily worse. Missing without minimum eligible history. | `tilt/features.py robust` |
| `deviation_rest_gap_seconds_z` | 6 | games | robust z | rest_gap_seconds: (current - baseline_median)/max(1.4826*baseline_MAD,1.0). Positive means higher, not necessarily worse. Missing without minimum eligible history. | `tilt/features.py robust` |
| `deviation_risk_rate_z` | 6 | games | robust z | risk_rate: (current - baseline_median)/max(1.4826*baseline_MAD,0.05). Positive means higher, not necessarily worse. Missing without minimum eligible history. | `tilt/features.py robust` |
| `deviation_risk_z` | 6 | moves | robust z | risk: (current - baseline_median)/max(1.4826*baseline_MAD,0.05). Positive means higher, not necessarily worse. Missing without minimum eligible history. | `tilt/features.py robust` |
| `deviation_style_switch_rate_z` | 6 | games | robust z | style_switch_rate: (current - baseline_median)/max(1.4826*baseline_MAD,0.05). Positive means higher, not necessarily worse. Missing without minimum eligible history. | `tilt/features.py robust` |
| `deviation_think_seconds_z` | 6 | moves | robust z | think_seconds: (current - baseline_median)/max(1.4826*baseline_MAD,0.1). Positive means higher, not necessarily worse. Missing without minimum eligible history. | `tilt/features.py robust` |
| `deviation_think_std_z` | 6 | games | robust z | think_std: (current - baseline_median)/max(1.4826*baseline_MAD,0.1). Positive means higher, not necessarily worse. Missing without minimum eligible history. | `tilt/features.py robust` |
| `deviation_wc_loss_z` | 6 | moves | robust z | wc_loss: (current - baseline_median)/max(1.4826*baseline_MAD,0.01). Positive means higher, not necessarily worse. Missing without minimum eligible history. | `tilt/features.py robust` |
| `differs_from_best` | 1 | moves | boolean, nullable | Played UCI differs from engine best/API alternative. Missing if no best is known; not assumed false. | `tilt/features.py` |
| `end_kind` | 7 | games | category | terminal_move, stopped_clock_estimate, observed_upper_bound, pgn_end_header or unknown; preserves end-time uncertainty. | `tilt/normalize.py` |
| `end_ms` | 7 | games | UTC epoch ms | Scope creation/start, estimated end, conservative end upper bound, or latest end admitted to baseline, respectively. Timestamp metadata; baseline_latest_end_ms must be strictly less than start_ms. | `tilt/normalize.py; tilt/features.py compute` |
| `end_ply` | 7 | windows | ply | One-based played ply; inclusive window bounds; event anchor; or earliest conservative ply after which the entire output is available. Opponent-event anchors are previous ply. | `tilt/features.py` |
| `end_upper_ms` | 7 | games, moves, sessions | UTC epoch ms | Scope creation/start, estimated end, conservative end upper bound, or latest end admitted to baseline, respectively. Timestamp metadata; baseline_latest_end_ms must be strictly less than start_ms. | `tilt/normalize.py; tilt/features.py compute` |
| `endgame_accuracy` | 1 | games | percent | Arithmetic mean move accuracy of each BEFORE-position phase; not the weighted/harmonic API phases field. | `tilt/features.py` |
| `endgame_think` | 2 | games | seconds | Arithmetic mean measured think time in the corresponding BEFORE-position phase. | `tilt/features.py` |
| `error_rate` | 1 | games, windows | fraction [0,1] | Fraction of evaluated moves with any inaccuracy-or-worse, exactly mistake, or exactly blunder, respectively. | `tilt/features.py` |
| `eval_after_cp` | 1 | moves | centipawns, mover POV | Position eval before/after move; cp is absent for nonterminal mate scores. Terminal mate=0 is resolved by board turn to ±1000. | `tilt/features.py _score/move_features; API_SEMANTICS.md` |
| `eval_after_mate` | 1 | moves | signed moves to mate, mover POV | Positive: mover has mate; negative: mover faces mate. Not interchangeable with cp. Terminal mate zero resolved separately. | `tilt/features.py _score/move_features` |
| `eval_after_source` | 7 | moves | category | lichess, lichess_dump, stockfish_cache, terminal_board or lichess_legacy_initial. Conventional initial +15 cp used only at untouched standard start. | `tilt/features.py` |
| `eval_before_cp` | 1 | moves | centipawns, mover POV | Position eval before/after move; cp is absent for nonterminal mate scores. Terminal mate=0 is resolved by board turn to ±1000. | `tilt/features.py _score/move_features; API_SEMANTICS.md` |
| `eval_before_mate` | 1 | moves | signed moves to mate, mover POV | Positive: mover has mate; negative: mover faces mate. Not interchangeable with cp. Terminal mate zero resolved separately. | `tilt/features.py _score/move_features` |
| `eval_before_source` | 7 | moves | category | lichess, lichess_dump, stockfish_cache, terminal_board or lichess_legacy_initial. Conventional initial +15 cp used only at untouched standard start. | `tilt/features.py` |
| `eval_missing_fraction` | 7 | games, windows | fraction [0,1] | Fraction of eligible own moves with missing think time. Excludes structurally unclocked first turns and observed zero-time/premove intervals from numerator and denominator; null when none are eligible. Invalid/gifted clock observations remain missing. | `tilt/features.py` |
| `event_ply` | 7 | events | ply | One-based played ply; inclusive window bounds; event anchor; or earliest conservative ply after which the entire output is available. Opponent-event anchors are previous ply. | `tilt/features.py` |
| `event_types` | 4 | events | comma-separated names | Flags sharing the event anchor. Own-move errors and opponent events get separate rows if both occur on one response turn. | `tilt/features.py` |
| `game_accuracy` | 1 | games | percent [0,100] | Lichess mean of volatility-weighted and harmonic move accuracy. Volatility window clamp 2..8; weights clamp .5..12. Missing scores excluded per source rules. | `lila/modules/analyse/src/main/AccuracyPercent.scala gameAccuracy; tilt/formulas.py game_accuracy` |
| `game_count` | 7 | sessions | count | Number of target-player moves in aggregation or games in a session, respectively. | `tilt/features.py` |
| `game_id` | 7 | events, games, moves, windows | identifier | Raw local game id. Dataset exports use HMAC-SHA256(salt, "game:" + id); never a predictor. | `tilt/features.py` |
| `game_ids` | 7 | sessions | identifier | JSON list of raw member game ids in local session features; omitted from exports. | `tilt/features.py` |
| `games_in_session_before` | 5 | games | games count | Number of already-started earlier games in same session; excludes current game. Can include an overlapping game, without using its uncompleted performance. | `tilt/features.py` |
| `historical_accuracy_similar_fraction` | 6 | moves | fraction [0,1] | accuracy: fraction of eligible historical values within max(1.4826*MAD,1.0) of current value; missing without minimum eligible history. | `tilt/features.py robust` |
| `historical_attack_rate_similar_fraction` | 6 | games | fraction [0,1] | attack_rate: fraction of eligible historical values within max(1.4826*MAD,0.05) of current value; missing without minimum eligible history. | `tilt/features.py robust` |
| `historical_blunder_rate_similar_fraction` | 6 | games | fraction [0,1] | blunder_rate: fraction of eligible historical values within max(1.4826*MAD,0.01) of current value; missing without minimum eligible history. | `tilt/features.py robust` |
| `historical_cpl_similar_fraction` | 6 | moves | fraction [0,1] | cpl: fraction of eligible historical values within max(1.4826*MAD,1.0) of current value; missing without minimum eligible history. | `tilt/features.py robust` |
| `historical_cpl_std_similar_fraction` | 6 | games | fraction [0,1] | cpl_std: fraction of eligible historical values within max(1.4826*MAD,1.0) of current value; missing without minimum eligible history. | `tilt/features.py robust` |
| `historical_error_rate_similar_fraction` | 6 | games | fraction [0,1] | error_rate: fraction of eligible historical values within max(1.4826*MAD,0.01) of current value; missing without minimum eligible history. | `tilt/features.py robust` |
| `historical_immediate_after_loss_similar_fraction` | 6 | games | fraction [0,1] | immediate_after_loss: fraction of eligible historical values within max(1.4826*MAD,0.05) of current value; missing without minimum eligible history. | `tilt/features.py robust` |
| `historical_mean_accuracy_similar_fraction` | 6 | games | fraction [0,1] | mean_accuracy: fraction of eligible historical values within max(1.4826*MAD,1.0) of current value; missing without minimum eligible history. | `tilt/features.py robust` |
| `historical_mean_cpl_similar_fraction` | 6 | games | fraction [0,1] | mean_cpl: fraction of eligible historical values within max(1.4826*MAD,1.0) of current value; missing without minimum eligible history. | `tilt/features.py robust` |
| `historical_mean_think_similar_fraction` | 6 | games | fraction [0,1] | mean_think: fraction of eligible historical values within max(1.4826*MAD,0.1) of current value; missing without minimum eligible history. | `tilt/features.py robust` |
| `historical_post_event_cpl_delta_similar_fraction` | 6 | games | fraction [0,1] | post_event_cpl_delta: fraction of eligible historical values within max(1.4826*MAD,1.0) of current value; missing without minimum eligible history. | `tilt/features.py robust` |
| `historical_post_event_think_delta_similar_fraction` | 6 | games | fraction [0,1] | post_event_think_delta: fraction of eligible historical values within max(1.4826*MAD,0.1) of current value; missing without minimum eligible history. | `tilt/features.py robust` |
| `historical_recovery_plies_similar_fraction` | 6 | games | fraction [0,1] | recovery_plies: fraction of eligible historical values within max(1.4826*MAD,1.0) of current value; missing without minimum eligible history. | `tilt/features.py robust` |
| `historical_rest_gap_seconds_similar_fraction` | 6 | games | fraction [0,1] | rest_gap_seconds: fraction of eligible historical values within max(1.4826*MAD,1.0) of current value; missing without minimum eligible history. | `tilt/features.py robust` |
| `historical_risk_rate_similar_fraction` | 6 | games | fraction [0,1] | risk_rate: fraction of eligible historical values within max(1.4826*MAD,0.05) of current value; missing without minimum eligible history. | `tilt/features.py robust` |
| `historical_risk_similar_fraction` | 6 | moves | fraction [0,1] | risk: fraction of eligible historical values within max(1.4826*MAD,0.05) of current value; missing without minimum eligible history. | `tilt/features.py robust` |
| `historical_style_switch_rate_similar_fraction` | 6 | games | fraction [0,1] | style_switch_rate: fraction of eligible historical values within max(1.4826*MAD,0.05) of current value; missing without minimum eligible history. | `tilt/features.py robust` |
| `historical_think_seconds_similar_fraction` | 6 | moves | fraction [0,1] | think_seconds: fraction of eligible historical values within max(1.4826*MAD,0.1) of current value; missing without minimum eligible history. | `tilt/features.py robust` |
| `historical_think_std_similar_fraction` | 6 | games | fraction [0,1] | think_std: fraction of eligible historical values within max(1.4826*MAD,0.1) of current value; missing without minimum eligible history. | `tilt/features.py robust` |
| `historical_wc_loss_similar_fraction` | 6 | moves | fraction [0,1] | wc_loss: fraction of eligible historical values within max(1.4826*MAD,0.01) of current value; missing without minimum eligible history. | `tilt/features.py robust` |
| `history_games` | 6 | games | games count | Number of definitely completed prior games, and same-speed subset. Not necessarily enough valid observations for every feature baseline. | `tilt/features.py` |
| `immediate_after_loss` | 5 | games | 0/1, nullable | Latest definitely completed game was a loss and rest gap <=60 seconds. Missing with no eligible previous game. | `tilt/features.py` |
| `judgement` | 1 | moves | category | good/inaccuracy/mistake/blunder, or missing. Inclusive server cp winning-chance-loss thresholds .1/.2/.3; mate created/lost uses server mate rules. Delivering mate is good. | `lila/modules/tree/src/main/Advice.scala; lila/ui/analyse/src/liveAnnotate.ts (strict-boundary difference); tilt/formulas.py judgement` |
| `just_blundered` | 4 | moves | boolean | Current move judgement is blunder. A feature/event flag only. | `tilt/features.py` |
| `just_lost_advantage` | 4 | moves | boolean, nullable | Own winning chances crossed from >=.3524 before to <.3524 after current move. | `tilt/features.py` |
| `just_lost_material` | 4 | moves | boolean | Material balance before current own move fell relative to previous own post-move balance; event anchor is intervening opponent ply. | `tilt/features.py` |
| `just_missed_mate` | 4 | moves | boolean | Had positive mover mate before, no positive mate after; false if the move delivers checkmate. | `tilt/features.py` |
| `just_missed_win` | 4 | moves | boolean, nullable | Own winning chances >=.6 before but <.3524 after current move. Heuristic win-loss event threshold; not a tilt label. | `tilt/features.py` |
| `legal_moves` | 7 | moves | count | Legal move count BEFORE move, one simple complexity proxy. | `python-chess Board.legal_moves` |
| `losing_streak_before` | 5 | games | games count | Consecutive losses in end-ordered, definitely completed own games before current start. Non-loss/unknown breaks streak. | `tilt/features.py` |
| `material_after` | 7 | moves | pawn units, mover POV | Own minus enemy material before/after move: P=1,N=B=3,R=5,Q=9,K=0. Positional compensation is not material. | `tilt/features.py` |
| `material_balance` | 7 | moves | pawn units, mover POV | Own minus enemy material before/after move: P=1,N=B=3,R=5,Q=9,K=0. Positional compensation is not material. | `tilt/features.py` |
| `material_lost_since_turn` | 4 | moves | pawn units | max(0, own previous post-turn material balance - own current pre-turn material balance), reflecting intervening opponent move. | `tilt/features.py` |
| `max_consecutive_errors` | 1 | games, windows | own moves count | Maximum observed consecutive_errors within aggregation; a run may begin before the window boundary. | `tilt/features.py` |
| `mean_accuracy` | 1 | games, sessions, windows | percentage points | Arithmetic mean/population standard deviation of move accuracy; differs from weighted/harmonic game_accuracy. | `tilt/features.py` |
| `mean_cpl` | 1 | games, sessions, windows | centipawns | Arithmetic mean and population standard deviation of observed move CPL within aggregation. Missing values excluded; entirely missing stays missing. | `tilt/features.py` |
| `mean_think` | 2 | games, sessions, windows | seconds | Arithmetic mean/population standard deviation of observed think time, excluding unclocked or missing moves. | `tilt/features.py` |
| `mean_think_per_legal_move` | 2 | games, windows | seconds/legal move | Arithmetic mean observed think_per_legal_move over aggregation. | `tilt/features.py` |
| `mean_wc_loss` | 1 | games, windows | winning-chance difference | Arithmetic mean of observed move wc_loss. | `tilt/features.py` |
| `middlegame_accuracy` | 1 | games | percent | Arithmetic mean move accuracy of each BEFORE-position phase; not the weighted/harmonic API phases field. | `tilt/features.py` |
| `middlegame_think` | 2 | games | seconds | Arithmetic mean measured think time in the corresponding BEFORE-position phase. | `tilt/features.py` |
| `mistake_rate` | 1 | games, windows | fraction [0,1] | Fraction of evaluated moves with any inaccuracy-or-worse, exactly mistake, or exactly blunder, respectively. | `tilt/features.py` |
| `move_count` | 7 | games, windows | count | Number of target-player moves in aggregation or games in a session, respectively. | `tilt/features.py` |
| `observed_initial_seconds` | 2 | moves | seconds | Post-move remaining clock, previous own post-move clock (before current decision), and first observed own clock. Imported clocks are centiseconds divided by 100. | `tilt/features.py move_features; lila/modules/core/src/main/game/data.scala` |
| `offered_material` | 3 | moves | pawn units | Value of the moved piece if risk=1, else 0. Material offered, not automatically a sacrifice. | `tilt/features.py` |
| `opening_accuracy` | 1 | games | percent | Arithmetic mean move accuracy of each BEFORE-position phase; not the weighted/harmonic API phases field. | `tilt/features.py` |
| `opening_think` | 2 | games | seconds | Arithmetic mean measured think time in the corresponding BEFORE-position phase. | `tilt/features.py` |
| `opponent` | 7 | games, moves | identifier | Raw opponent username in local features; omitted from dataset exports. | `tilt/features.py` |
| `opponent_just_took_advantage` | 4 | moves | boolean | Current BEFORE-state losing, previous own AFTER-state was not losing; event anchor is opponent previous ply. | `tilt/features.py` |
| `opponent_rating` | 7 | games, moves | rating points | Player rating, opponent rating, and player minus opponent rating; missing ratings remain missing. | `tilt/features.py` |
| `phase` | 7 | moves | category | opening/middlegame/endgame from Divider boundary applied to BEFORE-position index ply-1. Endgame boundary wins if middle absent. | `scalachess/core/src/main/scala/Divider.scala; tilt/formulas.py division` |
| `phase_accuracy_change` | 1 | games | percentage points | Endgame mean move accuracy minus opening mean move accuracy; missing if either phase lacks data. | `tilt/features.py` |
| `phase_speed_change` | 2 | games | seconds | Endgame mean think time minus opening mean think time; negative means faster. | `tilt/features.py` |
| `player` | 7 | events, games, moves, sessions, windows | identifier | Raw local player id; exported as player_id = HMAC-SHA256(salt, lower-case id); never a predictor. | `tilt/features.py` |
| `ply` | 7 | moves | ply | One-based played ply; inclusive window bounds; event anchor; or earliest conservative ply after which the entire output is available. Opponent-event anchors are previous ply. | `tilt/features.py` |
| `post_advantage_state` | 7 | moves | category | Mover winning if winning chances >= .3524 (~200 cp), losing if <= -.3524, equal otherwise, unknown if missing. State before/after respectively. | `tilt/features.py move_features; winningChances.ts uses .3524 for 200 cp-equivalent` |
| `post_count` | 4 | events | own moves count | Number of own moves in N-ply pre/post-event windows, excluding event ply. Opponent event anchors include the first own response in post. | `tilt/features.py` |
| `post_event_cpl_delta` | 4 | events, games | centipawns | Mean CPL in pre/post-event windows and post minus pre delta. Game rows average event deltas, not individual pooled moves. | `tilt/features.py` |
| `post_event_think_delta` | 4 | events, games | seconds | Mean measured think time before/after event and post minus pre delta. Game rows average event deltas. | `tilt/features.py` |
| `post_mean_cpl` | 4 | events | centipawns | Mean CPL in pre/post-event windows and post minus pre delta. Game rows average event deltas, not individual pooled moves. | `tilt/features.py` |
| `post_mean_think` | 4 | events | seconds | Mean measured think time before/after event and post minus pre delta. Game rows average event deltas. | `tilt/features.py` |
| `pre_count` | 4 | events | own moves count | Number of own moves in N-ply pre/post-event windows, excluding event ply. Opponent event anchors include the first own response in post. | `tilt/features.py` |
| `pre_mean_cpl` | 4 | events | centipawns | Mean CPL in pre/post-event windows and post minus pre delta. Game rows average event deltas, not individual pooled moves. | `tilt/features.py` |
| `pre_mean_think` | 4 | events | seconds | Mean measured think time before/after event and post minus pre delta. Game rows average event deltas. | `tilt/features.py` |
| `previous_game_id` | 7 | games | identifier | Raw local id of the latest strictly prior game by end time; omitted from exports. | `tilt/features.py` |
| `rating` | 7 | games, moves | rating points | Player rating, opponent rating, and player minus opponent rating; missing ratings remain missing. | `tilt/features.py` |
| `rating_difference` | 7 | games, moves | rating points | Player rating, opponent rating, and player minus opponent rating; missing ratings remain missing. | `tilt/features.py` |
| `realized_sacrifice_rate` | 3 | games, windows | fraction [0,1] | Mean of the corresponding move flag (realized_sacrifice_rate uses unsound_sacrifice_realized). Missing flags excluded. | `tilt/features.py` |
| `recent_form` | 7 | games | mean outcome score [0,1] | Mean result_score over last five definitely completed own games, end-ordered; unknown outcomes excluded. | `tilt/features.py` |
| `recovery_baseline_missing` | 6 | events | boolean | Fewer than required prior same-speed games or no historical CPL; recovery cannot be evaluated. | `tilt/features.py` |
| `recovery_censored` | 4 | events | boolean | No observed pair satisfying recovery criterion before game end, or missing normal baseline. | `tilt/features.py` |
| `recovery_plies` | 4 | events, games | board plies | Distance from event to second of two consecutive future own moves with CPL <= prior personal median + max(1,1.4826*MAD). Uses only pre-game same-speed history for normal threshold; may scan to game end; missing when unavailable/unrecovered. | `tilt/features.py` |
| `remaining_before_seconds` | 2 | moves | seconds | Post-move remaining clock, previous own post-move clock (before current decision), and first observed own clock. Imported clocks are centiseconds divided by 100. | `tilt/features.py move_features; lila/modules/core/src/main/game/data.scala` |
| `rematch_streak_before` | 5 | games | games count | Consecutive definitely completed prior games against the current opponent, in end order; zero if no matching predecessor. | `tilt/features.py compute` |
| `rematch` | 5 | games | 0/1 | Same opponent as latest definitely completed own game; zero with no previous game. | `tilt/features.py` |
| `rest_gap_seconds` | 5 | games | seconds | Current start minus end estimate of latest definitely completed own game. Missing if no eligible history or no end estimate. | `tilt/features.py` |
| `result_score` | 7 | games | 0 / .5 / 1 or missing | Current player-game outcome, used internally to build later cross-game history; excluded from labelled predictor export. | `tilt/features.py` |
| `risk` | 3 | moves | 0/1 | Moved non-king piece is attacked and either undefended or attacked by a cheaper piece. A simple exposure proxy; ignores deep tactics. | `tilt/features.py` |
| `risk_rate` | 3 | games, sessions, windows | fraction [0,1] | Mean of the corresponding move flag (realized_sacrifice_rate uses unsound_sacrifice_realized). Missing flags excluded. | `tilt/features.py` |
| `sacrifice_heuristic` | 3 | moves | boolean, nullable | Offered material >0 and current CPL >=100; provisional unsound offer heuristic, no future reply consulted. | `tilt/features.py` |
| `sacrifice_rate` | 3 | games, windows | fraction [0,1] | Mean of the corresponding move flag (realized_sacrifice_rate uses unsound_sacrifice_realized). Missing flags excluded. | `tilt/features.py` |
| `session_gap_basis` | 7 | games | category | end_time when previous-started game has known estimated end, otherwise start_gap_proxy. Indicates session-boundary approximation. | `tilt/features.py` |
| `session_id` | 7 | events, games, moves, sessions, windows | identifier | Local session hash for joins; dataset exports use HMAC-SHA256(salt, "session:" + id); never a predictor. | `tilt/features.py` |
| `speed` | 7 | games, moves | category | Lichess speed; dump uses initial + 40*increment with repository thresholds. | `tilt/formulas.py speed; scalachess/core/src/main/scala/Speed.scala` |
| `start_ms` | 7 | games, moves, sessions | UTC epoch ms | Scope creation/start, estimated end, conservative end upper bound, or latest end admitted to baseline, respectively. Timestamp metadata; baseline_latest_end_ms must be strictly less than start_ms. | `tilt/normalize.py; tilt/features.py compute` |
| `start_ply` | 7 | windows | ply | One-based played ply; inclusive window bounds; event anchor; or earliest conservative ply after which the entire output is available. Opponent-event anchors are previous ply. | `tilt/features.py` |
| `style_drift_in_session` | 5 | games | fraction difference | Current risk_rate minus mean risk_rate of definitely completed earlier games in same session. | `tilt/features.py` |
| `style_switch` | 3 | moves | 0/1 | risk changes compared with previous own move; first own move is 0. | `tilt/features.py` |
| `style_switch_rate` | 3 | games, windows | fraction [0,1] | Mean of the corresponding move flag (realized_sacrifice_rate uses unsound_sacrifice_realized). Missing flags excluded. | `tilt/features.py` |
| `tense_think_std` | 2 | games, windows | seconds | Population think-time standard deviation restricted to equal advantage_state; equal is a stated tense-position proxy. | `tilt/features.py` |
| `think_per_legal_move` | 2 | moves | seconds/legal move | think_seconds divided by legal_moves. Transparent complexity-adjusted timing proxy, not expected-time prediction. | `tilt/features.py` |
| `think_seconds` | 2 | moves | seconds | Previous own clock minus current clock plus applicable increment; no increment on terminal move. First own moves unmeasured/missing. Gifts, inconsistent controls, or ambiguous final dump claim-draw increments can make time missing. | `tilt/features.py move_features; lila/modules/game/src/main/Game.scala computeMoveTimes; scalachess/core/src/main/scala/Clock.scala` |
| `think_std` | 2 | games, windows | seconds | Arithmetic mean/population standard deviation of observed think time, excluding unclocked or missing moves. | `tilt/features.py` |
| `uci` | 1 | moves | UCI string | Played move or best alternative at its BEFORE-position. Best from selected engine cache, falling back to API advice best; missing stays missing. | `tilt/features.py move_features; lila/modules/tree/src/main/Advice.scala` |
| `unclocked_first_move` | 2 | moves | boolean | First exported move of this colour; no observed think duration, excluded from time means. | `tilt/features.py` |
| `unsound_attack` | 3 | moves | boolean, nullable | attack=1 and current CPL >=100; not a human judgement of emotion. | `tilt/features.py` |
| `unsound_attack_rate` | 3 | games, windows | fraction [0,1] | Mean of the corresponding move flag (realized_sacrifice_rate uses unsound_sacrifice_realized). Missing flags excluded. | `tilt/features.py` |
| `unsound_sacrifice_realized` | 3 | moves | boolean, nullable | Material lost since previous own turn, previous moved piece was offered, and previous own CPL >=100. Delayed confirmation heuristic available only on this response turn. | `tilt/features.py` |
| `wc_loss` | 1 | moves | winning-chance difference [0,2] | max(0,before-after) in mover POV. cp clamp ±1000; mate distance handling follows UI winning chances. | `lila/ui/lib/src/ceval/winningChances.ts; tilt/formulas.py chances` |

## Robust scale floors

Scale is `max(1.4826 * MAD, floor)`. Floors prevent division by zero in stable histories without population imputation. Signed z-scores are uncapped; only their contribution to BDS is clipped at absolute 10.

| Input feature | Move floor | Game floor |
|---|---:|---:|
| `accuracy` | 1.0 | — |
| `attack_rate` | — | 0.05 |
| `blunder_rate` | — | 0.01 |
| `cpl` | 1.0 | — |
| `cpl_std` | — | 1.0 |
| `error_rate` | — | 0.01 |
| `immediate_after_loss` | — | 0.05 |
| `mean_accuracy` | — | 1.0 |
| `mean_cpl` | — | 1.0 |
| `mean_think` | — | 0.1 |
| `post_event_cpl_delta` | — | 1.0 |
| `post_event_think_delta` | — | 0.1 |
| `recovery_plies` | — | 1.0 |
| `rest_gap_seconds` | — | 1.0 |
| `risk` | 0.05 | — |
| `risk_rate` | — | 0.05 |
| `style_switch_rate` | — | 0.05 |
| `think_seconds` | 0.1 | — |
| `think_std` | — | 0.1 |
| `wc_loss` | 0.01 | — |
