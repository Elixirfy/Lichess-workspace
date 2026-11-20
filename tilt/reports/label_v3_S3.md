# Label v3 S3 — fourth-run Erratum 4 implementation and operator handoff

Status: **fourth run complete: Erratum 4 implemented; 76 S3 tests and all 490 suite tests pass; count stops clear; the same-five-player one-process smoke rerun passes.** The immutable split is reused. Full rebuild, length probe and final gate remain operator work. No v3 training or holdout label/feature output was produced. Third-run sections below retain their historical results; the Erratum 4 section and fourth-run end checks give the current handoff.

The complete pre-registration, S1/S2 reports and saved first-run preflight report were read. Erratum 3 resolves the earlier overlap stop. P3-B/v3 remains the whole-game adoption comparator by the user's decision. S3 implements no whole-game comparator and admits none of its columns to M-v3.

## Lock and protected inputs

At the start of run 3, `sha256sum tilt/reports/label_v3_preregistration.md` again matched `~/tilt-labels-v3/prereg.sha256`:

`73617016beb4369f03f3d4f2d6f7757dd3b58eab47967aa1ee1e6ced8c45e80c`.

A subsequent `sha256sum -c /home/trantrien/tilt-labels-v3/prereg.sha256` from `tilt/reports/` returned **OK**. The final check is recorded below. Neither the document nor its lock was edited.

| Input | SHA-256 / audit |
|---|---|
| Old features parameter manifest | `1ea2383b730329b9f3301263a42aaa788b9ff0ae961df03d921cd1bbc16ec000` |
| New features parameter manifest | Same hash; matches `S3/new_features_manifest.sha256` |
| Holdout manifest | `d21e5b02dbaf07c6fee3a7c608973c9f5608f8f62a9aa9cd97120c517a89ff3d` |
| Old feature content | All 5 `features/*.parquet` files, sorted by filename, recorded in `S3/features_content_old.sha256` before any build |
| New feature content | All 5 `features/*.parquet` files, sorted by filename, recorded in `S3/features_content_new.sha256` before any build |
| Frozen rules design | `6393da7f066e1a8c3892fd894e381cb70ceb1f24d00366e97ef5ef40794fb0fb` |

Content hashes are streamed from the files; the audit files contain basenames and hashes only. Existing baseline files refuse a different snapshot. Both roots remain read-only. SQLite reads use `mode=ro`, and normalized shards are restricted to committed batches. No salt file or token was read.

## Preflight (run 1)

The original stopped report remains at `~/tilt-labels-v3/S3/preflight1/label_v3_S3.preflight1.md`; count-only audit inputs remain in `S3/preflight_counts.{py,json}`. Its active document hash was `09bf6847f27368975d6292684a93c22ac55264b3e290f7fee37babb53d5a517a`, preceding Erratum 3.

| Count-only check | Old | New |
|---|---:|---:|
| Missing required source columns | 0 | 0 |
| Committed normalized game shards checked | 438 | 208 |
| Computable group-B columns on a 20-ply development sample | 3/3 | 3/3 |
| Identifier rows matching stored username string form | 72,575/72,575 | 61,103/61,103 |
| Null player identifiers | 0 | 0 |
| Candidate development targets, before S3 split | 36,389 | 15,943 |
| Targets with any earlier in-session `end_upper_ms >= start_ms(g)` | 338 (0.928852%) | 208 (1.304648%) |
| Targets with immediate prior failing that cutoff | 75 | 35 |
| Targets with any known true `end_ms >= start_ms(g)` | 24 | 6 |

Combined: 52,332 candidate targets; 546 upper-bound failures (1.043339%), 110 immediate-prior failures (0.210197%), and 30 known true overlaps (0.057326%). There are 554 upper-bound-failing prior/target pairs. No sessions were recomputed. Old target counts exclude 12 S2 development drops; the 15,943 new targets are exactly manifest development sides.

Required schemas checked in run 1:

- Feature games: player/game/colour/session/start/end/upper-end identifiers and timestamps, both ratings, result, speed, and the four history columns.
- Feature moves: player/game/colour/ply, CPL and judgement, think time, five style flags, cp/mate evaluations, clock, material, legal moves and phase.
- Normalized games: game ID, both time-control components, status, plies, rated and both side ratings.

Ply indexing is **1-based**. Each checked prefix had 20 distinct physical plies, indices 1–20, and 10 own moves. Existing `core.score.dynamics` produced all three group-B columns: thirds need at least 9 own moves and change point needs 10. Both roots store identifiers in the same `[A-Za-z0-9_-]{2,30}` string form, rather than hexadecimal player IDs in that source field. Only counts were retained.

## Erratum 3 outcome and history check

**The overlap stop clears:** E3.2 uses the 30 known true overlaps, below the unchanged 0.5% threshold. The 546 uncertain/overlapping upper-bound cases remain excluded from direct model history. Label history remains S(g), unchanged; model history is S′(g).

Before implementation continued, the four history columns were inspected in `PriorHistory.before` and their construction in `features.compute`. All four use the heap activated by the strict condition `end_upper_ms < start_ms(g)`. An exact replay using the existing history implementation and its null handling verified their stored values:

| Column | Applies strict cutoff | Old mismatches / rows | New mismatches / rows |
|---|---|---:|---:|
| `losing_streak_before` | yes | 0/72,575 | 0/61,103 |
| `rest_gap_seconds` | yes | 0/72,575 | 0/61,103 |
| `recent_form` | yes | 0/72,575 | 0/61,103 |
| `rematch_streak_before` | yes | 0/72,575 | 0/61,103 |

`S3/history_column_check.json` preserves these counts. No history column requires exclusion. These are the stored pipeline histories, including their existing cross-session semantics; they are not silently replaced by session-only variants.

The accepted E3.5 residual remains: an included prior game's frozen label/E states may indirectly refer to another earlier-started game with an uncertain end. Its label is not corrected. Real truncation tests select targets with no unavailable earlier-started game in any session; synthetic fixtures separately cover uncertain ends and true overlaps for direct model inputs.

## Implementation and mechanical choices

Runs 1–2 created or rewrote the original five authorized repository files:

- `src/tilt/labels/split_v3.py`;
- `src/tilt/features/prefix_v3.py`;
- `tests/unit/test_split_v3.py`;
- `tests/unit/test_prefix_v3.py`;
- this report.

The standalone CLI provides `split`, `labels`, `features`, `probe`, `gate` and `describe`, with explicit input/output paths and `--processes N`. No workstation path is embedded in either module. Player-sized move reads stream through bounded process batches; the parent writes fixed-order Parquet row groups. Serial and two-process outputs have identical hashes in tests. Input-root destinations are rejected.

`split` implements cohort-wise hash ordering, half-up V_A rounding, the nearest-rank 85th-percentile V_B anchor, existing-session expansion, and shared-game train drops. An exclusive `split.once` marker and existing-output checks refuse regeneration, including interrupted publication. Integrity checks cover the complete development universe, uniqueness, player/session/physical-game isolation and holdout hash. The manifest retains only pseudonymous keys, hashed sessions, counts-related metadata and the public split hash; raw identifiers stay in memory.

Portable old-cohort discovery projects only S1 bridge metadata and existing pseudonyms from `old-root/out/weak_by_player.parquet`. It reads no v1 label or prediction column. The bridge covers 36,401 sides and 196 players and does not require `~/tilt-phase1/aligned`. New membership comes from S2's cohort and locked manifest. The recorded S2 pseudonym scheme is honored explicitly, so an unrelated environment salt cannot change a public-keyed assignment. `excluded_sides.csv` is hash-checked and excluded from targets. Physical-game equality uses a separate common hash across roots.

The label wrapper calls frozen v3 functions and restores actual development membership after adapting S1's train-only guard. It never changes the rule design. The `labels` step also recomputes S1 regression rows in memory, including rows now excluded as S3 targets, and saves agreement counts only in `label_regression.json`. No dropped-side label is stored. Necessary own-player prior-rule evaluations are transient history inputs, not target rows. Holdout moves are excluded from worker reads; later holdout headers are used only for E7's next-game/session boundary.

Every direct session quantity and R-pre uses S′(g), with its own previous game and exact gaps. Model baseline descriptors use the pooled same-speed window. Prefix z references use the last available prior prefixes that reached ply 20, without a current-length bucket. A current game's end timestamp cannot admit that game into its own baseline. No feature of the current game's suffix, result or whole-game behavior is copied into the model tables.

After Erratum 4, retained prefix rows require exactly physical plies 1–20 and 10 own moves. The exact one-colour pattern is dropped from both heads; every other gap still raises. Shorter games have no prefix row. Stored evaluations and material are converted from mover POV to own POV. `clock_used` is net initial-clock depletion `(initial_seconds - tenth_own_clock) / initial_seconds`; increments are included in the think-time budget `initial_seconds + 40*increment_seconds`. Nulls remain null. Missing flags use the existing false convention; prior evidence missing maps to null. Previous labels encode NOT/TILT/ABSTAIN as 0/1/2; phase encodes opening/middlegame/endgame as 0/1/2, and previous status uses the fixed enum in the module, unknown values null. These are fixed encodings, not learned mappings.

The registry has **73 F-pre** and **31 F-p20** columns:

| Block | Family | Columns |
|---|---|---:|
| pre | meta | 5 |
| pre | session context | 20 |
| pre | stored history | 4 |
| pre | previous game | 21 |
| pre | session behavior | 7 |
| pre | pooled baseline | 16 |
| p20 | quality | 6 |
| p20 | time | 5 |
| p20 | style/dynamics | 8 |
| p20 | position | 5 |
| p20 | prefix z/aggression | 7 |

`model_matrix` selects registered blocks for M-v3 and P3-B@20 and rejects unregistered fields. Whole-game P3-B/v3 is deliberately outside this API. The `probe` uses train lengths only; single-feature stops return exit code 2. Its multi-feature diagnostic uses fixed gradient boosting with three player-grouped folds. `describe` filters train before any label or feature statistic and removes G1–G7 pass/fail decisions. `gate` checks row sets, membership, split/content hashes, frozen design, full S1 regression, exact registry, build provenance, current-code test evidence and written decisions for any probe stops. A failed gate returns exit code 1. It cannot treat smoke output as a full build.

## Tests and current gate status

Third-run commands, from `tilt/`:

```bash
S3_REAL_CONFIG=/home/trantrien/tilt-labels-v3/S3/real_test_paths.json \
  .venv/bin/python -m pytest -q tests/unit/test_split_v3.py tests/unit/test_prefix_v3.py

PYTHONPATH=/home/trantrien/tilt-labels-v2/test_runtime \
S3_REAL_CONFIG=/home/trantrien/tilt-labels-v3/S3/real_test_paths.json \
  .venv/bin/python -m pytest -q
```

- New tests: **54 passed in 21.30 s**.
- Full suite: **468 passed in 79.99 s**, one existing Starlette/AnyIO deprecation warning.
- No test was changed, weakened, skipped or deselected to resolve the lock failure. The S2 lock test calls `check_lock()` and contains no hardcoded old hash.
- The same external test-only asyncio wake-up shim as run 2 was used for the full suite. Existing model/integration tests use their existing synthetic fixtures; no v3 training or score-versus-label computation was introduced. The existing Stockfish fixture integration test passed.

Tests cover every S3.1 integrity check and every S3.5 item, including real development samples from one player per root, filtered histories, future/suffix perturbations, pre-game independence, truncation, pooled-baseline independence, prefix support, holdout/drop rejection, frozen-rule agreement, exact registry selection, and deterministic serial/parallel output. Synthetic gate tests cover failure paths and hashed written probe decisions. `real_tests_old.json` and `real_tests_new.json` contain counts and current code bindings. `test_evidence.json` now records success; the run-2 failure is preserved as `test_evidence_run2.json`. Logs are `tests_new_run3.txt` and `tests_full_run3.txt`.

**S3.7 remains NOT READY for S4.** Tests and split integrity now pass. Full output populations, full S1 regression, length-probe decisions and the final gate await the operator's full build. No real `s3_gate.json` was produced, and smoke regression is not full regression.

## One-time real split — completed

The real `split` CLI was invoked **exactly once in this run**, after both test commands passed. It wrote `dev_split_manifest.parquet`, `dev_split_manifest.sha256`, `split.once` and `split_counts.json` directly into `~/tilt-labels-v3/S3/`. No assignment was regenerated or marker removed.

Manifest SHA-256:

`f0677cb8f63c73d91cf98f6d40bb26a85c58631b8642ae90f3e98b0b6789cccb`.

| Part | Old rows | Old players | New rows | New players | Total rows | Total players |
|---|---:|---:|---:|---:|---:|---:|
| train | 24,220 | 157 | 10,300 | 113 | 34,520 | 270 |
| V_A | 6,743 | 39 | 3,049 | 28 | 9,792 | 67 |
| V_B | 5,382 | 157 | 2,579 | 114 | 7,961 | 271 |
| drop_shared_split | 44 | 26 | 15 | 13 | 59 | 39 |
| Development universe | 36,389 | 196 | 15,943 | 142 | 52,332 | 338 |
| Kept targets | 36,345 | 196 | 15,928 | 142 | 52,273 | 338 |

Player counts across parts overlap and must not be summed. One new non-V_A player has only validation targets after shared-game drops, explaining 113 train versus 114 V_B players. S2's 12 old and 16 new `drop_shared_development` sides were already outside the development universe; they are separate from these 59 S3 drops.

All eight checks in `split_integrity.json` passed: exact development universe, unique assignment, manifest metadata matching canonical sources, V_A player isolation, train/V_B session isolation, train/validation physical-game isolation, unchanged holdout SHA, and matching feature-content baselines. The saved manifest's SHA was independently checked with `sha256sum -c`. The audit uses the existing manifest only; it does not call `assign` again.

## Smoke build and resource extrapolation — completed

The deterministic sample contains **five distinct development players total: two old and three new**. `labels` and `features` ran with `--max-players 5 --processes 1` into `S3/smoke/`, then on the **same five players** with `--processes 2` into `S3/smoke/parallel2/`. No additional real players received stored smoke rows. All three table hashes match between serial and parallel builds, as does the sampled player set.

Both runs produced **618 labels, 618 F-pre rows and 596 F-p20 rows**. Label and pre-game keys/membership match exactly; prefix rows are exactly the selected targets reaching ply 20. Registry: **73 F-pre + 31 F-p20 columns**. No label distribution, behavior distribution or validation statistic beyond row counts was computed or reported.

| Processes | Step | CLI wall seconds | Build-loop seconds | `/usr/bin/time` peak RSS KiB | Parent peak KiB | Child peak KiB |
|---|---|---:|---:|---:|---:|---:|
| 1 | labels | 11.79 | 5.330 | 1,194,916 | 1,194,916 | 0 |
| 1 | features | 33.34 | 27.550 | 1,343,560 | 1,343,560 | 0 |
| 2 | labels | 12.24 | 5.964 | 938,416 | 553,996 | 938,416 |
| 2 | features | 24.40 | 18.378 | 904,124 | 536,676 | 904,124 |

GNU time's RSS is not simultaneous process-tree memory. The parallel metadata's child value is the maximum recorded child RSS, not a sum. For planning, use `parent_peak + N * child_peak`: **2,430,828 KiB = 2.318 GiB (2.49 decimal GB)** at N=2, versus **1.281 GiB** measured serial peak. Peaks need not coincide. This estimates the measured player mix; a larger individual player can require more memory. For arbitrary N, a conservative smoke-derived expression is `553996 + N*938416` KiB; only N=1 and N=2 were measured, and extrapolating concurrency does not establish its full-build peak.

Full target count is **338 players / 52,273 sides**; smoke count is **5 / 618**. Let `H = CLI wall − recorded build seconds` per step. To avoid multiplying fixed import/header/content-hash overhead, estimate each step as `H + build_seconds * scale`, then sum labels and features. The measured parallel loop already includes process startup, I/O and batching; do not divide it by N again.

| Processes | Player scaling: 338/5 = 67.6 | Row scaling: 52,273/618 = 84.584 | Planning peak |
|---|---:|---:|---:|
| 1 | 37.25 min | 46.56 min | 1.281 GiB |
| 2 | 27.63 min | 34.52 min | 2.318 GiB bound |

These are labels-plus-features estimates, excluding installation, pytest, probe and gate. Repeated player Parquet scans, game lengths, session mix, baseline work, cache state and larger individual histories limit five-player extrapolation. The sample has fewer sides per player than the full target set, so **use the row-scaled estimate for host planning**. Recommend the **rented Ubuntu 24.04 box, initially N=2**, because 34.52 minutes exceeds the WSL 30-minute criterion. The nominal player-scaled N=2 estimate is below 30 minutes, but has little margin. The exact same commands support WSL `--processes N` if the operator elects that host. No full build was run here.

Sampled old-row S1 regression checked **148/148 by_player** and **139/139 by_time** labels with exact agreement. Both `label_regression.json` files correctly say `complete: false`. Counts are regression audits, not label statistics; full regression remains pending. Raw timings/build metadata, source/output hashes and the count-only summary are preserved under `smoke/` and `smoke_summary.json`.

## Deviations

**Mechanical, operator-approved lock correction.** The operator explicitly authorized replacing only `LOCK` in `src/tilt/data/cohort_v3.py`:

- Old: `0d59ce9d79e6e9e9e9992e5116b83e39440eacfc1f3a53b83772030d8b2a0b06`.
- New: `73617016beb4369f03f3d4f2d6f7757dd3b58eab47967aa1ee1e6ced8c45e80c`.

Nothing else in that file changed; a byte comparison against its pre-edit snapshot verifies this, with before/after file hashes in `lock_correction.json`. No S2 test edit was necessary. S2 assignment was not rerun; its existing immutable manifest remains unchanged. The constant checks the approved current document, while the S2 steps remain finished. This resolves the run-2 stop (467 passed / one stale-lock failure) and expands the original five-file scope by exactly the approved constant edit. The preregistration and its lock were never edited. The prior report is preserved outside the repo as `S3/label_v3_S3.run2.md`.

**Mechanical smoke choices.** Serial and two-process runs reuse the same five players to measure concurrency without widening the real-data smoke sample. The conservative row-scaled estimate drives the host recommendation because the sample's sides-per-player is below the full development set's. No real label/probe/gate statistic selected or removed any feature.

**Accepted E3.7 limitation:** both parameter manifests have the same hash and cannot establish unchanged historical data content. S2's old-root unchanged check had the same weakness and cannot be reconstructed retrospectively. All actual S3 per-Parquet content baselines still match. The accepted E3.5 indirect prior-label residual remains as documented above. No threshold, LF, rule, feature family or membership rule changed.

## Full-build attempt 1

The operator ran `operator_full_build.sh` on the rented Ubuntu box with **12 processes**. The labels step completed with **52,273 stored development rows**. S1 regression was complete and exact: **22,316/22,316 by_player** and **25,403/25,403 by_time**. Features then stopped at `P-20 must have exactly physical plies 1..20`; no feature table had been published. These are operator-reported results, not a WSL full build.

The operator's count-only diagnosis found **41 physical games with plies ≥20: 16 old and 25 new**. Their target memberships were:

| Part | Old | New | Total |
|---|---:|---:|---:|
| train | 9 | 11 | 20 |
| V_A | 5 | 4 | 9 |
| V_B | 2 | 3 | 5 |
| Development targets | 16 | 18 | 34 |
| A′ | 0 | 7 | 7 |
| B′ | 0 | 0 | 0 |

Of **49,881 P-20 development targets**, the operator found **662** with at least one affected game in their original prefix reference window. E4.1 records the operator's holdout move-presence diagnosis as a deviation from the former S3.9 restriction. This run uses only the specific count permission in E4; it does not investigate the pipeline cause or modify either data root.

## Erratum 4 — fourth run

The start lock check returned **OK**, SHA-256 `8bee90248167e4085e7b48c2ff280d444138b9cb14399775348cbabe3530be4c`. The preregistration and its lock are untouched. As explicitly authorized, `cohort_v3.LOCK` was mechanically changed from `73617016…` to this SHA. The S3 CLI's `split_v3.PREREG_SHA` required the same mechanical update to accept the binding document; no split logic or assignment changed. Exact before/after checks are in `S3/lock_correction_run4.json`.

`prefix_status` handles exactly ten odd white plies or ten even black plies in 1–20 as `drop_incomplete_moves`. Other missing or duplicated prefix plies still raise. `incomplete_targets` is independent of development/holdout membership and freezes the same exclusion rule for S5; S3's actual feature-target guard continues to reject holdouts. `prefix_stats` returns no prefix for the handled defect, also preventing a P3-B@20 matrix from receiving those rows.

Both feature heads exclude affected targets. The original labels remain stored and all these games remain in F-pre history. Prefix references first skip incomplete games and then select the last ≤200 complete available prefixes, retaining the minimum of five nonnull component statistics. The length probe and train description consume the resulting retained feature population. No feature is selected by label.

The builder runs a projected move-presence audit (`game_id`, `ply`, `color` only), including the E4-permitted holdout presence counts. It checks exactly **34 development exclusions: train 20, V_A 9, V_B 5**, before feature publication, repeats the count on worker results, and compares the two inventories. Own-colour checks reject any existing or freshly computed TILT/NOT label whose own moves are missing, including short one-colour games. S1 and development label columns used solely for that stop are never summarized by label. No holdout labels are read or computed.

`excluded_incomplete_moves.csv` uses existing pseudonymous game/player keys, colour, cohort, original part, plies, colour present and derived status. It does not change the manifest. Its hash is bound into feature-build provenance and `s3_gate.json`; the gate independently rechecks the exclusion inventory and expects all original labels but only retained feature rows. `features_build.json` reports affected reference-window target counts by part, both for the original P-20 population (to compare with 662) and for retained targets. This count marks an incomplete game in the original last-200 eligible window; the replacement window fills from earlier complete prefixes.

The independent WSL count-only audit confirmed the operator's 41/34 counts and each old/new part count above. It also found:

| Cohort | All one-colour physical games | Plies <20 | Plies ≥20 | Own colour present | Own colour missing |
|---|---:|---:|---:|---:|---:|
| old | 42 | 26 | 16 | 42 | 0 |
| new | 64 | 39 | 25 | 64 | 0 |
| Total | 106 | 65 | 41 | 106 | 0 |

Every physical game in this inventory corresponds to one cohort side. **Neither E4 stop fired.** The only holdout move-presence result is the authorized **A′ 7 / B′ 0** incomplete-prefix count. There are no holdout label, feature or score outputs. `S3/incomplete_moves_audit.json` and `erratum4_counts.json` contain counts only; `erratum4_counts.py` reproduces the latter using projected move columns and existing headers, with identifiers confined to memory.

The independent header/presence calculation also confirms the **49,881 original P-20 targets** and reference-window counts:

| Part | Original P-20 targets whose window skips a defect | Of those, retained after E4 |
|---|---:|---:|
| train | 348 | 334 |
| V_A | 192 | 186 |
| V_B | 122 | 118 |
| Total | 662 | 638 |

These are row counts, including validation only as counts. No target feature or label was built for this calculation.

The new S3 test command passed **76 tests in 25.13 s**, including **22 added E4 cases**. Fixtures cover both one-colour target patterns, actual build output of the exclusion CSV with hash provenance, unchanged stored labels, prior-game/F-pre retention, reference-window skipping, minimum-five and replacement-to-200 rules, unexpected target/history gaps, frozen holdout exclusion semantics, count stops, own-colour stops and rejection before publishing either feature table. Existing leakage, split, determinism, real-sample and gate tests still pass. Synthetic full-build fixtures declare their own defect count; the production 34-count constant is unchanged.

The final full-suite rerun passed **490 tests in 80.23 s**, with one existing Starlette/AnyIO deprecation warning; evidence is recorded in the fourth-run end checks below. Commands are the same as run 3, using `S3_REAL_CONFIG` for both runs and the existing external test-only asyncio shim for the full suite. No v3 training or score-versus-label computation was introduced; existing suite tests retain their synthetic fixtures.

A fresh **`S3/smoke_e4/`** build used `--max-players 5 --processes 1`, the same **two old and three new players** as run 3. It produced **618 labels, 618 F-pre rows and 596 F-p20 rows**; all three table hashes are identical to the original serial smoke tables. Keys, parts, registry and complete-prefix populations pass; there are zero affected smoke targets or reference windows and the exclusion CSV contains only its header. Sample S1 regression remains exact **148/148** and **139/139**, correctly marked `complete: false`. The full count audit still enforces 34 globally even during smoke; the per-worker sample count is compared with its selected-player subset rather than with 34.

Labels took **11.10 s wall / 5.155 s build loop**, peak RSS **1,240,768 KiB**. Features took **45.16 s wall / 34.465 s build loop**, peak RSS **1,538,688 KiB**. The additional projected count audit increases fixed overhead and peak memory; these serial timings supersede run-3 smoke timings for the revised code. N=12 was the operator's full-build choice; it has not been benchmarked by Codex. Full feature computation remains operator work. Raw metadata, timing files and `smoke_e4_summary.json` preserve these checks.

The split, frozen design, S1 files and both processed roots are unchanged. `split_v3.py` differs only in its active lock SHA; `cohort_v3.py` differs only in `LOCK`. No split command, full feature build, real length probe, train description, real final gate, commit or push ran in this WSL turn. A full `s3_gate.json` remains pending the operator; its exclusion SHA binding is covered by synthetic gate tests.

## Operator runbook (executed; see Full-build Results)

The operator will restart the complete script after deleting only the attempt-1 partial outputs listed below on the rented box. This explicit user instruction overrides E4's default instruction to reuse the completed labels; the frozen labels are recomputed identically with current code provenance. Labels take about 30 seconds on that host.

```bash
# On the rented box only; S3_WORK is the existing S3 output directory.
rm -- "$S3_WORK/labels_dev.parquet" "$S3_WORK/label_regression.json" "$S3_WORK/labels_build.json"
find "$S3_WORK" -maxdepth 1 -type f -name '*.tmp' -delete
bash "$S3_WORK/operator_full_build.sh" "$S3_CODE" "$S3_OLD_ROOT" "$S3_NEW_ROOT" "$S3_V3_DIR" 12
```

Transfer the updated code, preregistration document, current `prereg.sha256` and operator script first, using the transfer lists below. The script runs the whole suite and labels/features/probe/description/gate as before; it never silently reuses stale provenance. Existing feature tables still cause refusal. Expect **52,273 labels, 52,239 F-pre rows and 49,847 F-p20 rows** after E4. The exclusions are **20/9/5**; the gate expects labels for these excluded rows to remain. No cleanup or full build was performed by Codex on the rented host.

The full build is operator work. **Do not run `split` again**: transfer the manifest, SHA file and `split.once` unchanged. The CLI refuses existing full-build tables; it must not overwrite smoke or previous build files. The prepared `S3/operator_full_build.sh` accepts **all paths as arguments**, uses `--processes N`, verifies the existing split/lock, recreates destination-specific real-test configuration, reruns the full suite, writes current successful evidence, then runs labels, features, length probe, train-only description and gate. Its syntax was checked with `bash -n`; the full-build script itself was not executed.

### Exact minimum transfer contents

`transfer_old_files.txt`, `transfer_new_files.txt`, `transfer_code_files.txt` and `transfer_v3_files.txt` list exact relative files for the commands below. Preserve relative paths and bytes. The data-root lists were derived read-only from the committed `batches` table, not from game identifiers.

| Destination root | Required files/directories |
|---|---|
| Code directory | `pyproject.toml`; all package files under `src/tilt/`; `tests/` including its two fixtures; `benchmarks/features_bench.py`; `docs/guides/FEATURES.md`; `reports/label_v3_preregistration.md`; this report. Exact list: 65 files, without bytecode/caches. Benchmark and feature dictionary are required by the full suite. |
| Old processed root | `index.sqlite`; `normalized/games/` **438 committed Parquets** named in the old transfer list; `features/manifest.json`; **all five** `features/{events,games,moves,sessions,windows}.parquet`; `out/weak_by_player.parquet`. **446 files, 417,040,680 bytes.** |
| New processed root | `index.sqlite`; `normalized/games/` **208 committed Parquets** named in the new transfer list; `features/manifest.json`; **all five** `features/{events,games,moves,sessions,windows}.parquet`. **215 files, 326,637,333 bytes.** See `transfer_sizes.json` for the exact checked byte count. |
| v3 directory | `prereg.sha256` at its root. |
| `v3/S1/` | `design_hash.txt`, `labels_by_player_train.parquet`, `labels_by_time_train.parquet` (v3, not v3b). |
| `v3/S2/` | `cohort.csv`, `assignment_metadata.json`, `excluded_sides.csv`, `holdout_manifest.parquet`. |
| `v3/S3/` runtime | `features_content_old.sha256`, `features_content_new.sha256`, `dev_split_manifest.parquet`, `dev_split_manifest.sha256`, `split.once`. Preserve `code_hash.txt`, `test_evidence.json`, `real_tests_old.json`, `real_tests_new.json` as provenance; destination tests refresh their own evidence. |
| `v3/S3/` handoff | `operator_full_build.sh`, `split_counts.json`, `split_integrity.json`, `lock_correction.json`, `smoke_summary.json`, `codex-last.md`, `transfer_sizes.json`, all four `transfer_*_files.txt` lists. Included in the v3 transfer list for a reviewable handoff. |

All five feature Parquets are needed even though builders project only games/moves: `verify_sources` rehashes every feature Parquet against the original content baselines. The old metadata export is read through bridge/pseudonym columns only. Both SQLite files must be quiescent consistent copies. Existing databases use DELETE journaling with no required WAL. Data roots remain read-only during S3.

The minimum package is about **744 MB uncompressed for the two processed roots**, plus code and the selected v3 files. The code list includes ordinary package imports used by `core.score.dynamics`; those imports do not load a deployed bundle. Raw PGN/NDJSON, normalized move shards, engine caches/binaries, models, the separate phase-1 aligned directory, v3b outputs, collection logs, archives, salt files, tokens and all other S1/S2/S3 history are unnecessary for the full build. The Stockfish test uses the host binary only on its synthetic fixture; install it on Ubuntu to run that existing test instead of its ordinary absent-binary skip.

### Source packaging commands

These commands create transfer tarballs from exact lists. The code tarball and its checksum are also prepared at this handoff; the other three packaging commands are provided for the operator. They copy files and never rebuild data or assignments.

```bash
set -euo pipefail
S3_CODE=/home/trantrien/lichess-workspace/tilt
S3_OLD_ROOT="$S3_CODE/data/processed"
S3_NEW_ROOT="$S3_CODE/data/v3new/processed"
S3_V3_DIR=/home/trantrien/tilt-labels-v3
S3_WORK="$S3_V3_DIR/S3"
S3_PACK=/tmp/label-v3-s3-transfer
mkdir -p "$S3_PACK"
tar -C "$S3_CODE" -czf "$S3_PACK/code.tar.gz" -T "$S3_WORK/transfer_code_files.txt"
tar -C "$S3_OLD_ROOT" -czf "$S3_PACK/old-processed.tar.gz" -T "$S3_WORK/transfer_old_files.txt"
tar -C "$S3_NEW_ROOT" -czf "$S3_PACK/new-processed.tar.gz" -T "$S3_WORK/transfer_new_files.txt"
tar -C "$S3_V3_DIR" -czf "$S3_PACK/v3.tar.gz" -T "$S3_WORK/transfer_v3_files.txt"
(cd "$S3_PACK" && sha256sum code.tar.gz old-processed.tar.gz new-processed.tar.gz v3.tar.gz > SHA256SUMS)
```

Ship the four tarballs and `SHA256SUMS`. Raw identifiers remain confined to the private data copies; do not publish these data archives. No salt or token is packaged.

### WSL command

The existing Python 3.12 venv already passed this run's suite. N=2 was measured; replace the final `2` with the chosen N. For this existing restricted environment only, pass the same external test shim to the script; omit `PYTHONPATH` on an ordinary WSL installation where socketpair wake-ups work.

```bash
PYTHONPATH=/home/trantrien/tilt-labels-v2/test_runtime \
bash /home/trantrien/tilt-labels-v3/S3/operator_full_build.sh \
  /home/trantrien/lichess-workspace/tilt \
  /home/trantrien/lichess-workspace/tilt/data/processed \
  /home/trantrien/lichess-workspace/tilt/data/v3new/processed \
  /home/trantrien/tilt-labels-v3 2
```

### Fresh Ubuntu 24.04 / Python 3.12 / uv commands

Copy the transfer directory onto the box, then set its path below. These paths are examples; the script accepts any absolute paths and never uses the source workstation's home directory. Package downloads require network access. `uv` is the installer; the package's Python dependencies are pinned in `pyproject.toml`. No `uv.lock` exists in this checkout. The fresh-host install was not executed in this sandbox.

```bash
set -euo pipefail
sudo apt-get update
sudo apt-get install -y python3.12 python3.12-venv libgomp1 stockfish time
# If uv is already installed, skip these two bootstrap commands and use uv below.
python3.12 -m venv /tmp/label-v3-uv
/tmp/label-v3-uv/bin/python -m pip install uv
S3_UV=/tmp/label-v3-uv/bin/uv
S3_PACK="$HOME/label-v3-transfer"
S3_CODE="$HOME/label-v3/code"
S3_OLD_ROOT="$HOME/label-v3/old-processed"
S3_NEW_ROOT="$HOME/label-v3/new-processed"
S3_V3_DIR="$HOME/label-v3/tilt-labels-v3"
(cd "$S3_PACK" && sha256sum -c SHA256SUMS)
mkdir -p "$S3_CODE" "$S3_OLD_ROOT" "$S3_NEW_ROOT" "$S3_V3_DIR"
tar -xzf "$S3_PACK/code.tar.gz" -C "$S3_CODE"
tar -xzf "$S3_PACK/old-processed.tar.gz" -C "$S3_OLD_ROOT"
tar -xzf "$S3_PACK/new-processed.tar.gz" -C "$S3_NEW_ROOT"
tar -xzf "$S3_PACK/v3.tar.gz" -C "$S3_V3_DIR"
cd "$S3_CODE"
"$S3_UV" venv --python python3.12 .venv
"$S3_UV" pip install --python .venv/bin/python -e '.[test]'
bash "$S3_V3_DIR/S3/operator_full_build.sh" \
  "$S3_CODE" "$S3_OLD_ROOT" "$S3_NEW_ROOT" "$S3_V3_DIR" 2
```

With a preinstalled uv, set `S3_UV=$(command -v uv)` instead of bootstrapping it. Use a writable destination for extraction/venv/output and preserve the source baselines. The destination script automatically recreates `real_test_paths.json`, so source absolute paths are not reused. Normal Ubuntu does not need the WSL test shim. The two real-data sample tests must not be skipped; `S3_REAL_CONFIG` is always set by the script.

### Exact build steps, probe stop and resume

These are the substantive commands inside the script, with its CLI argument array expanded here for review. They are **future operator commands**, not executed full-build results:

```bash
S3_WORK="$S3_V3_DIR/S3"
S3_ARGS=(--old-root "$S3_OLD_ROOT" --new-root "$S3_NEW_ROOT"
  --s1 "$S3_V3_DIR/S1" --s2 "$S3_V3_DIR/S2" --s3 "$S3_WORK"
  --prereg "$S3_CODE/reports/label_v3_preregistration.md"
  --lock "$S3_V3_DIR/prereg.sha256" --out "$S3_WORK" --processes 2)
"$S3_CODE/.venv/bin/python" -m tilt.features.prefix_v3 labels "${S3_ARGS[@]}"
"$S3_CODE/.venv/bin/python" -m tilt.features.prefix_v3 features "${S3_ARGS[@]}"
"$S3_CODE/.venv/bin/python" -m tilt.features.prefix_v3 probe "${S3_ARGS[@]}"
"$S3_CODE/.venv/bin/python" -m tilt.features.prefix_v3 describe "${S3_ARGS[@]}"
"$S3_CODE/.venv/bin/python" -m tilt.features.prefix_v3 gate "${S3_ARGS[@]}" \
  --test-evidence "$S3_WORK/test_evidence.json"
```

The script exits on probe status 2, before description/gate, for the required written decision. It never removes a feature automatically. Do not rerun the whole script after this stop: labels/features already exist. After an accepted written decision, resume only with `describe`, then `gate ... --decisions /absolute/path/decision.json`, using the same `S3_ARGS` above. Decision JSON must contain `probe_sha` (exact SHA-256 of `length_probe.json`) and `accepted_stops`, a list of `[block, column, threshold]` triples covering every accepted stop. A decision requiring a feature or rule change needs separate approved implementation and tests; the flag itself changes no matrix.

The diagnostic gradient boosting fits lengths only, never v3 labels. `describe` computes train-only descriptions and removes G1–G7 pass/fail decisions; it computes no prediction-score-versus-label metric. Inspect `label_regression.json`, `s3_gate.json`, `description_train.json` and `length_probe.json`; report only row counts for validation. The CLI checks both feature-content baselines, parameter manifests, holdout manifest and preregistration before and after each step. Run the final lock check from the copied code's `reports/`:

```bash
(cd "$S3_CODE/reports" && sha256sum -c "$S3_V3_DIR/prereg.sha256")
```

## Full-build Results (operator, 2026-11-17)

Filled in by the operator. Every number below is computed on **train rows only** or is a row count; no
score-versus-label metric was computed.

### Runs on the rented box (Ubuntu 24.04, 24 CPU, `--processes 12`)

| Attempt | Lock | Outcome |
|---|---|---|
| 0 | `73617016…` | The full suite failed 8 integration tests: `templates/` was missing from the code transfer list. The operator shipped `templates/` and nothing else. |
| 1 | `73617016…` | `labels` were exact against S1. `features` raised "P-20 must have exactly physical plies 1..20" (41 one-colour games), which led to **Erratum 4**. |
| 2 | `8bee9024…` | `labels`, `features` and `probe` ran; the probe stopped on 5 F-pre columns, which led to **Erratum 5** (user chose option A: B-skill joins the adoption rule). |
| 3 (final) | `82789032…` | Same as attempt 2, after the mechanical change of the lock constants (`PREREG_SHA` in `split_v3.py`, `LOCK` in `cohort_v3.py`; see `lock_correction_run5.json`). The probe stopped; then `describe` and `gate` ran with `probe_decision.json`. |

- Attempt 3 outputs are byte-identical to attempt 2 (`labels_dev`, `features_pre`, `features_p20` and `length_probe` hashes are equal).
- Wall time 3 min 44 s in total: `labels` 31 s, `features` 152 s. Peak RSS 1.41 GB.
- The full suite passed on the box before the build (490 tests).

### Outputs (`~/tilt-labels-v3/S3/`)

| File | sha256 |
|---|---|
| `labels_dev.parquet` (52,273 rows) | `5070069a7a4dedae5cea4c1a92cd0d1cc4548e66ea58f277cb233adadc427af4` |
| `features_pre.parquet` (52,239 rows) | `07c542f14d8ec708aab53afed1e2baf019153991f1ef634e664744f5b8edb730` |
| `features_p20.parquet` (49,847 rows) | `78691dfd9fe1df9c5a844c4ed33b995f0d0b685afaa6af04fae20012bc2d987f` |
| `excluded_incomplete_moves.csv` (34 targets) | `e3f1bf17e551f7d01c4ba587c67d2464ab01d6aa3c531096b6cddea5387bad1e` |
| `s3_gate.json` | `5169cb67cc8074a6ca80c6da24c22229be0d712b845eaa5e983d47fb06e9f375` |

Frozen code hashes (`code_hash.txt`):
- `split_v3.py` `f426e792…`
- `prefix_v3.py` `71b92e6e…`
- `rules_v3.py` `9f2d8234…`, design hash `6393da7f…`

### Labels and regression
- S1 regression is complete and exact: `by_player` 22,316/22,316, `by_time` 25,403/25,403.
- Erratum 4 excluded 34 targets: train 20, V_A 9, V_B 5. Targets with a one-colour game in their reference window after exclusion: train 334, V_A 186, V_B 118. The own-colour stop did not fire.

### Train-only label description (descriptive; no pass/fail)

| Cohort | Rows | TILT | NOT | ABSTAIN | Coverage | Prevalence |
|---|---:|---:|---:|---:|---:|---:|
| old | 24,211 | 1,033 | 12,422 | 10,756 | 55.6% | 7.7% |
| new | 10,289 | 410 | 5,237 | 4,642 | 54.9% | 7.3% |
| all | 34,500 | 1,443 | 17,659 | 15,398 | 55.4% | 7.6% |

- Prevalence by population: P-20 is 7.4% (old) and 7.0% (new); the rows under 20 plies are 18.3% (old) and 14.8% (new).
- G1–G7 re-reported (all / old / new):
  - G1 length AUC 0.640 / 0.632 / 0.662;
  - G2 bucket spread 9.5 / 9.0 / 10.6 points;
  - G3a coverage 55.4% / 55.6% / 54.9%;
  - G4 prevalence 7.6% / 7.7% / 7.3%;
  - G5 won share of TILT 4.9% / 4.7% / 5.4%;
  - G6 max evidence share 76.7% / 76.2% / 78.1%;
  - G7 evidence-by-streak rise 4.0 / 3.0 / 6.5 points.

  These match S1's picture: G1, G4 and G6 would fail as gates, and G7 is weak.
- Model-versus-label context-rank differences (Erratum 3, S′ versus S): **45 train rows**.

### Length probe and decision
- Five single-feature stops, all F-pre at `plies < 20`:
  - `rating` 0.759;
  - `baseline_cpl_mean_w300_median` 0.727;
  - `baseline_blunders_per20_median` 0.723;
  - `baseline_blunders_per20_mad` 0.713;
  - `baseline_cpl_mean_w300_mad` 0.706.
- No F-p20 stop (neither AUC nor null rate). Nothing reaches 0.70 at `< 40`.
- Multi-feature probe (report only): pre `< 20` ≈ 0.745; pre `< 40` ≈ 0.68; p20 `< 40` 0.667–0.701.
- Decision (Erratum 5): accept all five; drop nothing. The S4 obligations are B-skill (adoption comparator, user option A), M-v3-ns (reference) and length-stratified reports.
- `probe_decision.json` records probe sha `bca34e82…` and decision sha `d1190208…`.

### S3.7 gate: **PASSED**
All 13 checks are true:
- tests, real-sample tests, split, labels, regression;
- pre, p20, registry, probe, incomplete exclusions, exclusion hash;
- content hashes, build provenance.

The prereg lock `82789032…` was verified before and after.

## Artifacts and end checks

`S3/code_hash.txt` records unchanged `split_v3.py`, `prefix_v3.py` and `rules_v3.py`; the design hash remains `6393da7f066e1a8c3892fd894e381cb70ceb1f24d00366e97ef5ef40794fb0fb`. Only the approved S2 constant and this report changed in the repository during run 3. Other workspace changes were left alone. Outside the repo are the immutable split, counts/integrity audits, successful test evidence, smoke outputs/timings, transfer lists, portable operator script, code tarball and short `codex-last.md` handoff.

No full labels/features, real length probe, train description, final gate, comparator evaluation, v3 training, commit or push ran. No holdout label or S3 feature row was built. Later holdout headers are boundary metadata only, as documented above; no holdout behavior/statistic was reported. No salt file or token was read or shipped. Report and summaries contain no usernames or game identifiers.

Final checks are saved in `end_checks_run3.json`: all 10 feature Parquets match their original S3 content baselines; both parameter manifests remain `1ea2383b730329b9f3301263a42aaa788b9ff0ae961df03d921cd1bbc16ec000`; holdout manifest remains `d21e5b02dbaf07c6fee3a7c608973c9f5608f8f62a9aa9cd97120c517a89ff3d`; split SHA remains the published value; smoke memberships/populations and serial/parallel hashes match; the frozen design and S3 code hashes are unchanged; and only the authorized constant differs in `cohort_v3.py`. Final `sha256sum -c` from `tilt/reports/`: **OK**, active prereg hash `73617016beb4369f03f3d4f2d6f7757dd3b58eab47967aa1ee1e6ced8c45e80c`.


## Fourth-run artifacts and end checks

`S3/test_evidence.json` binds the **76/490 passing tests** to the final module hashes; run-3 evidence is preserved as `test_evidence_run3.json`. Logs are `tests_new_run4.txt` and `tests_full_run4.txt`; real-sample evidence was regenerated by both test commands. `S3/code_hash.txt`, `transfer_code_files.txt` and `transfer_v3_files.txt` were regenerated. `S3/code.tar.gz` and its SHA file contain the current report, locked preregistration, code and tests listed in the code transfer list. The operator must also transfer the current lock and updated script with the v3 list. No salt or token is included.

`S3/end_checks_run4.json` records that all 10 feature Parquets still match the original content baselines; both parameter manifests remain `1ea2383b730329b9f3301263a42aaa788b9ff0ae961df03d921cd1bbc16ec000`; the holdout manifest remains `d21e5b02dbaf07c6fee3a7c608973c9f5608f8f62a9aa9cd97120c517a89ff3d`; and the split remains `f0677cb8f63c73d91cf98f6d40bb26a85c58631b8642ae90f3e98b0b6789cccb`. Neither the split nor its marker was recreated. The frozen design is unchanged, and `rules_v3.py` remains `9f2d8234377999965699be45aa466595447fad3dcf93709cf7ff89ed5a2a0a8a`. Mechanical-only lock substitutions in both constants were byte-checked against start snapshots.

Final `sha256sum -c ~/tilt-labels-v3/prereg.sha256` from `tilt/reports/`: **OK**, SHA `8bee90248167e4085e7b48c2ff280d444138b9cb14399775348cbabe3530be4c`. Neither the preregistration nor the lock was edited. No Erratum 4 stop fired. No full WSL build, training, score-versus-label metric, holdout label/feature output, split rerun, commit or push occurred. **S3.7 remains pending the operator's full rerun and written decisions for any length-probe stops.** `S3/codex-last.md` is the short handoff.
