# Label v3 S4: training code handoff

Status: Erratum 6 code fix and synthetic validation prepared. The operator's first real S4 train attempt stopped after writing five fitted bundles; **no metric, report or gate was produced and no validation value has been seen**. Full training, reporting, determinism and the S4 gate are operator work. The deployed P3-B pointer and bundle are unchanged. These models predict the frozen behavioural rule, not emotion.

## Locks and read-only inputs

The entire preregistration, S1 report and S3 Full-build Results were read before implementation. `sha256sum -c` passed from the appropriate document directories at the start. Current lock: `851858bca40d46ff6ee76a1b62bcab19e89581b03f59e9193e43eca1f072204f`. S3 snapshot: `827890324bdd0e17cef555b770920c972ba10d6bbc9552e830b4f1b7b06c665e`. The current document starts with the exact snapshot bytes. Neither document nor either lock was edited.

Every CLI step verifies both locks, the byte prefix, the five frozen S3 input hashes and `s3_gate.json` against the S3 report, the three frozen S3 module hashes, both roots' feature-content baselines, the holdout-manifest hash and the S1 design hash, before and after work. `prefix_v3.verify_sources` receives the snapshot and snapshot lock. `model_matrix` itself takes no lock/path argument; it is called unchanged after verification. S3 outputs and both processed roots remain read-only.

| Frozen input | SHA-256 |
|---|---|
| labels_dev.parquet | `5070069a7a4dedae5cea4c1a92cd0d1cc4548e66ea58f277cb233adadc427af4` |
| features_pre.parquet | `07c542f14d8ec708aab53afed1e2baf019153991f1ef634e664744f5b8edb730` |
| features_p20.parquet | `78691dfd9fe1df9c5a844c4ed33b995f0d0b685afaa6af04fae20012bc2d987f` |
| dev_split_manifest.parquet | `f0677cb8f63c73d91cf98f6d40bb26a85c58631b8642ae90f3e98b0b6789cccb` |
| excluded_incomplete_moves.csv | `e3f1bf17e551f7d01c4ba587c67d2464ab01d6aa3c531096b6cddea5387bad1e` |
| s3_gate.json | `5169cb67cc8074a6ca80c6da24c22229be0d712b845eaa5e983d47fb06e9f375` |

The frozen code remains `split_v3.py` `f426e792…`, `prefix_v3.py` `71b92e6e…`, `rules_v3.py` `9f2d8234…`. The design remains `6393da7f…`. Bundles bind the current lock and exact hashes of the training, scorer, feature, calibration and test code. `S4/code_hash.txt` records the source handoff hashes.

## Stop checks and parity sample

These were checked before implementation, with no fit and no score-versus-label statistic:

| Check | Evidence | Outcome |
|---|---|---|
| New-root whole-game columns | All eight stored/header columns and all move-flag inputs for the three deployed dynamics exist; both roots use the same deployed scorer projection | 11/11 producible |
| Registry | M-v3: 73 pre columns, 104 p20 columns; P3-B@20: 4 pre, 11 p20 | Every returned column is registered |
| Labelled train, pre / P-all | 34,500 targets; 19,102 labelled; 1,443 TILT | Above 50 positives |
| Labelled train, p20 / P-20 | 33,009 targets; 18,584 labelled; 1,354 TILT | Above 50 positives |
| Calibration status contract | Normal: `validation-only Platt scaling`; degenerate: explicit `identity: ...` statuses, including nonpositive slope | Distinguishes normal and degenerate |
| Old-player parity sample | 5 players, 750 development targets, every overlapping Phase 5 row, all 11 columns; absolute tolerance 1e-9, nulls equal | 0 mismatches; maximum absolute difference 0.0 |

The sample was first checked privately before implementation and then through the delivered `p3b` CLI on the same five players. Evidence: `S4/preflight_parity.json`, `S4/parity_sample/p3b_parity.json`, `S4/parity_sample_runtime.json`. No new-root whole-game table or full real-data table was built here.

The final sample CLI took **5.444 s**, peak RSS **598.3 MiB**, including lock/content verification. Straight row extrapolation is 5.444 × 52,239 / 750 = **379 s (6.3 min)** for one serial full table. The initial projection-only measurement was 1.304 s, suggesting a roughly 91 s compute component; fixed verification and host I/O make extrapolation uncertain. Budget **6–10 min serial**, approximately **4–8 min with two processes**, and **up to 2.5 GB RAM with two processes**. These are estimates, not a full-build benchmark. RSS should not be multiplied by row count: processing streams one player per worker and the final table is only 11 columns. Each complete operator run rebuilds the table and parity independently.

## Implementation and candidates

| Candidate | Heads and inputs | Calibration / role |
|---|---|---|
| M-v3 | pre: all F-pre; p20: F-pre + F-p20 | Fitted candidate |
| M-v3-ns | Both heads remove rating and 14 baseline medians/MADs | Fitted reference |
| B-skill | Same 15 skill-family columns in each head | Fitted adoption comparator |
| P3-B/v3 | One whole-game head, exactly 11 deployed columns | Fitted adoption comparator; §1.4 exception |
| P3-B@20/v3 | 4 pre columns; 11 p20 columns | Fitted reference |
| P3-B frozen | Deployed bundle on recomputed whole-game table | Frozen reference, own calibration |
| P3-B@20 frozen | Deployed bundle on S3 prefix columns, renamed to deployed column names, P-20 only | Frozen reference, own calibration |
| R-pre | S′ context rank + D/4 | Unfitted adoption comparator |
| B-streak | Stored strictly causal losing_streak_before | Unfitted adoption comparator |
| B-length / B-result | plies / 1 − result_score.fillna(0.5) (Erratum 6) | Unfitted references |

Nine classifiers use exactly `tree_models('xgboost', seed=42, threads=2, trees=100)[0]`. The `train` CLI rejects a different thread count; `--threads` controls native report threads on other steps. There is no tuning, early stopping, feature selection, threshold selection or train-plus-validation refit. Each imputer, scaler and classifier is passed only that head's labelled train rows. Balanced sample weights are confined to these rows. Median imputation retains empty columns and indicators; P3-B/v3 suppresses indicators for its three group-B columns exactly as Phase 5 does.

Each fitted head has two validation Platt fits, each using only labelled validation players in the opposite hash fold, plus one frozen Platt fit on all labelled validation rows. Fold key is exactly `label-v3-cal-fold-1:` plus the stored player identifier, SHA-256 interpreted as an integer modulo 2. ABSTAIN is scored but enters no classifier, calibration, metric or length-AUC denominator. Validation metrics use the cross-fitted score; train-head metrics use the frozen validation calibration. Predictions retain raw, cross-fitted/frozen calibrated scores for every head and the composite. The composite switches solely at plies ≥ 20. P3-B@20 frozen has no score below 20; it is not silently given a pre-head fallback.

Whole-game construction follows `score.run`: existing per-game rate/history aggregates, normalized time controls, and `score.dynamics` on the player's own moves. There is one builder for both roots. It never copies Phase 5 features into its output. SQLite is opened `mode=ro`; normalized Parquets are selected from committed batches and filtered to targets. The S3 target manifest and Erratum 4 exclusions determine the universe. New-root key discovery projects only membership keys, then filters before reading feature/header/move values. It does not call `split.load_headers`, which would open holdout headers. The two frozen references are scored only during the operator's training step.

Model matrices and the comparator table have separate paths. The whole-game table is never joined to M-v3, M-v3-ns, B-skill or P3-B@20. The four legitimate common pre-game column names are discussed under Deviations below; none of the seven current-game whole-only columns can enter these matrices. No A′/B′ feature, label or score was read. No holdout-bearing normalized/header scan was used by S4.

Reports contain PR-AUC, prevalence, ROC AUC, fitted-only Brier/ECE and reliability bins for V_A, V_B and pooled, all five distinct strata, and every fitted head. `ge40` also represents the repeated ≥40 stratum of the `<40`/`≥40` pair. ECE uses unchanged `phase1.calibration_bins`: ten quantile bins, collapsed duplicate edges, weighted absolute calibration error. Length diagnostics report signed and symmetric score-versus-length ROC AUC beside B-skill. Bootstrap uses 1,000 paired player-cluster draws, seed 42, percentile 95% intervals, and counts skipped one-class/no-positive draws. Cached score ranks with integer draw multiplicities reproduce the existing Phase 5 AP calculation and its exact draw/interval results, including ties; bootstrap features and settings are not tuned.

The initial `gate` records determinism as pending. `compare` requires all prediction/metric files and every bundle to match byte-for-byte, records maximum numeric prediction difference 0.0, then finalizes each run's gate with hash-bound determinism. A missing/degenerate calibration, failed Δ/CI, missing test evidence or unequal artifact fails closed. Exit code 2 records a failed gate; there is no fallback candidate. P3-B stays deployed.

## Tests and synthetic smoke

Real validation results are reserved for the Results section. Checks below use synthetic fixtures except the explicitly permitted counts and parity sample.

- S4 test files after Erratum 6: **44 passed in 51.80 s**, including six new cases for B-result and the other reference guards. All 44 also passed inside the full suite; its JUnit file records individual cases. The null-result test verifies every other score, all nine input matrices and all five fitted bundles are unchanged.
- Full suite: **532 passed, 2 skipped, 1 existing Starlette/AnyIO deprecation warning in 118.89 s**, using the supplied external asyncio wake-up shim. Evidence: `S4/tests_full_e6.txt`, `tests_full_e6.xml`, `tests_new_e6.txt`, `tests_new_e6.xml` and refreshed `test_evidence.json`; canonical test logs/XML are refreshed too. The two S3 real-sample skips are explained below.
- External synthetic run1/run2: **passed**, in separate processes, 432 synthetic targets per run, nine fitted heads and five bundles. Every compared file and bundle is byte-identical; maximum prediction difference **0.0**. Erratum 6 evidence: `S4/synthetic_e6/determinism.json`, `synthetic_smoke.json`. An additional tied-score bootstrap check exactly matched Phase 5 intervals and paired differences for seed 42.
- Portability: the original S4 package passed extraction, source guards and two-process parity on the same five players, matching the serial table and parity JSON byte-for-byte (`S4/portable_code_check.json`, retained as pre-Erratum 6 evidence). The Erratum 6 `S4/code.tar.gz` is refreshed with the unchanged 75-file transfer list; every archived file matches the current source and relocated source guards pass (`S4/end_checks.json`). No real-data parity rerun was performed for this fix.
- Operator/package shells: `bash -n` passed; the full operator script has not been executed here.

All S4.9 items have direct tests: fit/calibration row isolation; player fold and opposite-fold calibration; exact head switch; registry family; whole-game provenance; every holdout/drop status at construction/matrix/fit/calibration/report boundaries; paired clustered bootstrap against Phase 5; separate-process reproducibility; all gate conditions; parity tolerance/null/coverage; committed read-only source projection; and locks.

## Deviations and mechanical choices

1. **S3-era lock accommodation (user-authorized).** Frozen `split_v3`, `prefix_v3` and `rules_v3` are unchanged. Every S4 CLI checks current and snapshot locks and append-only bytes. Frozen source verification receives the snapshot. No frozen constant is updated.
2. **S2-era append-only check (user-authorized).** `cohort_v3.LOCK` now names the exactly identified S2-era prefix, hash `0d59ce9d79e6e9e9e9992e5116b83e39440eacfc1f3a53b83772030d8b2a0b06`, also recorded by `prereg.sha256.v3`. `check_lock` hashes the bytes through Erratum 2, retaining their final newline, before the blank line preceding Addendum S3. Later append-only stages leave these bytes unchanged. No cohort assignment logic changes.
3. **Existing tests.** This checkout's `test_split_v3.py` and `test_prefix_v3.py` have no exact comparison of the current document to `split.PREREG_SHA`. `test_cohort_v3.py` calls `cohort_v3.check_lock`, now append-only. Therefore no existing test file needed a lock-path edit. The new S4 tests verify the exact S3 snapshot prefix and the S2 check.
4. **S4.6 isolation wording.** Four names occur legitimately in both the whole table and the S3 pre matrix: initial/increment seconds, rematch streak and baseline risk count. Literal disjoint names would contradict S3.3/S4.3. Isolation is enforced by provenance and by rejecting the seven whole-only current-game columns; existing pre values are retained without a comparator-table join. No feature definition is changed.
5. **Read-only scorer projection.** `model_features.enrich` calls `storage.read`, which opens the source SQLite database for writes and reads all normalized headers. S4 projects the same required columns through read-only, target-filtered readers, while calling deployed `score.dynamics` directly. The five-player parity result validates the required output, not an alternative feature definition.
6. **Frozen prefix reference.** P3-B@20 frozen consumes the already frozen S3 prefix statistics and shared causal pre-game fields. These use the same deployed prefix flag rates/dynamics. Renaming `p20_*` for inference does not merge whole-game features or rebuild any S3 table.
7. **Full-suite real-sample tests.** The two opt-in S3 real-sample tests are not enabled: their frozen loader opens A′/B′ headers beyond membership, which S4.10 forbids. All synthetic leakage tests run. The unchanged S3 code and the hash-verified passed S3 gate preserve prior real-sample evidence; S4 opens no such headers. The operator script follows the same restriction and records this basis in test evidence.
8. **Development test rerun.** An early synthetic determinism test overlapped ongoing code edits: predictions/metrics differed by 0.0, but bundle/code provenance hashes changed. After code stabilized, the two-process test passed with byte-identical outputs. No real validation value was seen; no model setting, row set, label or feature was changed in response to a result.
9. **CLI/files.** All data/code/document/bundle/output paths are explicit arguments. Processing parallelism is exposed for `p3b`; the classifier's prescribed two threads remain fixed. Additional private audit files record calibration statuses, training provenance and test evidence. Stage outputs refuse reuse; the second `gate` finalization updates only that run's gate after determinism. Transfer lists and scripts live outside the repository.
10. **Stopped run 1 and Erratum 6.** The operator's first real S4 `train` attempt stopped in `fit_all` with `ValueError: Missing unfitted reference score`, after writing five fitted bundles. No metric, report or gate was produced; no validation value has been seen. Of the 52,239 target rows, 364 have null `result_score`: by part, train 251, V_A 62, V_B 51; by status, outoftime 326, timeout 29, insufficientMaterialClaim 9; by label, ABSTAIN 191, NOT 163, TILT 10. Erratum 6 treats these missing draw results as 0.5 for B-result only, giving `1 − result_score.fillna(0.5)` on the unchanged rows. `rules_v3` already treats a null result exactly like a draw: the loss-run scan only stops on a win; null and 0.5 both add nothing to loss counts; E6, E7 and the won-game rule do not apply. The frozen labels are therefore consistent and are not recomputed. The stopped run is preserved unchanged as `run1_failed_attempt1/`; its bundles were never evaluated and are not used. The missing draw result is a known defect of the normalisation step, not fixed here. All other reference scores, fitted candidates, matrices, imputation, metrics and gate remain unchanged. The operator must rerun the whole S4 script from the start in fresh directories, including the whole-game table, parity check, both complete runs and determinism comparison; the new `run1/` bundles are the frozen ones.

Beyond the registered Erratum 6 B-result fill, no threshold, label, feature block, split, exclusion, holdout assignment, model class or adoption condition changed. No commit, push, deployed write or local real-label fitting occurred.

## Operator runbook and exact transfers

`~/tilt-labels-v3/S4/operator_s4.sh` accepts eight required paths and optional processes/threads:

```bash
bash "$V3/S4/operator_s4.sh" \
  "$CODE" "$OLD_PROCESSED" "$NEW_PROCESSED" "$V3" \
  "$OLD_PROCESSED/models/deployed.json" \
  "$OLD_PROCESSED/models/phase5/by_player__P3-B.joblib" \
  "$REFERENCES/tilt-phase1/aligned/aligned_by_player.parquet" \
  "$REFERENCES/tilt-phase2/behavior_features.parquet" 2 2
```

It verifies the locks, reruns the suite and new tests on synthetic fixtures, records code-bound evidence, and invokes separate `p3b`, `train`, `report`, `gate` processes for run1 and then run2. Each run rebuilds its own whole-game table. Finally `compare` creates `S4/determinism.json` and finalizes both gates. A failed run1 validation gate is recorded; the prescribed identical run2 still finishes for determinism, and the final command returns 2. There is no retry with changed settings. Review both gates before considering S5.

Standalone stages use these common arguments:

```bash
ARGS=(--old-root "$OLD_PROCESSED" --new-root "$NEW_PROCESSED"
  --s1 "$V3/S1" --s2 "$V3/S2" --s3 "$V3/S3"
  --prereg "$CODE/reports/label_v3_preregistration.md" --lock "$V3/prereg.sha256"
  --snapshot "$V3/S3/prereg_at_S3/label_v3_preregistration.md"
  --snapshot-lock "$V3/S3/prereg_at_S3/prereg.sha256" --threads 2)
PY="$CODE/.venv/bin/python"
OUT="$V3/S4/run1"
"$PY" -m tilt.evaluation.v3_train p3b "${ARGS[@]}" --out "$OUT" \
  --deployment-pointer "$OLD_PROCESSED/models/deployed.json" \
  --deployed-bundle "$OLD_PROCESSED/models/phase5/by_player__P3-B.joblib" \
  --phase5-aligned "$REFERENCES/tilt-phase1/aligned/aligned_by_player.parquet" \
  --phase5-behavior "$REFERENCES/tilt-phase2/behavior_features.parquet" --processes 2
"$PY" -m tilt.evaluation.v3_train train "${ARGS[@]}" --out "$OUT" \
  --deployment-pointer "$OLD_PROCESSED/models/deployed.json" \
  --deployed-bundle "$OLD_PROCESSED/models/phase5/by_player__P3-B.joblib"
"$PY" -m tilt.evaluation.v3_train report "${ARGS[@]}" --out "$OUT"
"$PY" -m tilt.evaluation.v3_train gate "${ARGS[@]}" --out "$OUT" \
  --test-evidence "$V3/S4/test_evidence.json"
# Repeat those four commands in fresh processes with OUT="$V3/S4/run2".
"$PY" -m tilt.evaluation.v3_train compare "${ARGS[@]}" \
  --run1 "$V3/S4/run1" --run2 "$V3/S4/run2" \
  --determinism "$V3/S4/determinism.json" --test-evidence "$V3/S4/test_evidence.json"
```

Five exact relative-file lists in `S4/` are the transfer authority. Preserve bytes and relative paths:

| List | Source root | Required content |
|---|---|---|
| transfer_code_files.txt | repository `tilt/` | pyproject; package Python; tests and fixtures; templates; feature benchmark and dictionary; prereg and S1/S3/S4 reports |
| transfer_old_files.txt | old processed root | S3's exact 446 files plus deployed.json and its frozen Phase 5 bundle |
| transfer_new_files.txt | new processed root | S3's exact 215 files |
| transfer_v3_files.txt | `~/tilt-labels-v3/` | root lock; S1 frozen v3 inputs; S2 membership/provenance; S3 frozen runtime inputs, gate/build/test provenance, snapshot and lock; S4 operator/package scripts, lists, evidence and handoff |
| transfer_reference_files.txt | source home directory | `tilt-phase1/aligned/aligned_by_player.parquet`; `tilt-phase2/behavior_features.parquet` for mandatory full old-row parity only |

`transfer_sizes.json` records exact file counts and byte totals: code **75 files**; old root **448 files, 417,065,819 bytes**; new root **215 files, 326,637,333 bytes**; v3 **49 files**; Phase 5 references **2 files, 38,343,106 bytes**. The complete private package is approximately **846 MB uncompressed** including v3 inputs and code. `package_s4.sh CODE OLD NEW V3 REFERENCE_SOURCE DESTINATION` builds five archives from these lists and writes `SHA256SUMS`. The reference source is the directory containing `tilt-phase1/` and `tilt-phase2/`. The reference tables are used only to compare freshly computed whole-game values; they never supply training features or v1 labels. No salt, token, raw NDJSON/PGN, engine cache, normalized move shards, account-list file or unlisted S1/S2/S3 history is needed. Both SQLite copies must be consistent, quiescent copies; current sources use DELETE journaling. All five feature Parquets remain necessary because frozen source verification hashes them all.

Fresh Ubuntu 24.04 / Python 3.12 setup (example destination paths; none are embedded in the code):

```bash
set -euo pipefail
sudo apt-get update
sudo apt-get install -y python3.12 python3.12-venv libgomp1 stockfish
PACK="$HOME/label-v3-s4-transfer"
CODE="$HOME/label-v3-s4/code"
OLD_PROCESSED="$HOME/label-v3-s4/old-processed"
NEW_PROCESSED="$HOME/label-v3-s4/new-processed"
V3="$HOME/label-v3-s4/v3"
REFERENCES="$HOME/label-v3-s4/references"
(cd "$PACK" && sha256sum -c SHA256SUMS)
mkdir -p "$CODE" "$OLD_PROCESSED" "$NEW_PROCESSED" "$V3" "$REFERENCES"
tar -xzf "$PACK/code.tar.gz" -C "$CODE"
tar -xzf "$PACK/old-processed.tar.gz" -C "$OLD_PROCESSED"
tar -xzf "$PACK/new-processed.tar.gz" -C "$NEW_PROCESSED"
tar -xzf "$PACK/v3.tar.gz" -C "$V3"
tar -xzf "$PACK/phase5-references.tar.gz" -C "$REFERENCES"
python3.12 -m venv /tmp/label-v3-s4-uv
/tmp/label-v3-s4-uv/bin/python -m pip install uv
/tmp/label-v3-s4-uv/bin/uv venv --python python3.12 "$CODE/.venv"
cd "$CODE"
/tmp/label-v3-s4-uv/bin/uv pip install --python .venv/bin/python -e '.[test]'
bash "$V3/S4/operator_s4.sh" "$CODE" "$OLD_PROCESSED" "$NEW_PROCESSED" "$V3" \
  "$OLD_PROCESSED/models/deployed.json" \
  "$OLD_PROCESSED/models/phase5/by_player__P3-B.joblib" \
  "$REFERENCES/tilt-phase1/aligned/aligned_by_player.parquet" \
  "$REFERENCES/tilt-phase2/behavior_features.parquet" 2 2
```

On this restricted WSL environment only, prefix the operator invocation with `PYTHONPATH=/home/trantrien/tilt-labels-v2/test_runtime`. Ordinary Ubuntu needs no shim. Fresh-host dependency installation and full real-data execution were not performed here. The script refuses existing run directories; preserve failed runs instead of silently overwriting them.

## Results (operator placeholders)

### Full whole-game parity

Pending operator: run1/run2 rows, checked old rows, maximum difference, pass/fail, table hashes.

### Validation candidate table

| Part | Stratum | Candidate/head | n | Prevalence | PR-AUC [95% CI] | ROC AUC | Brier | ECE |
|---|---|---|---|---|---|---|---|---|
| V_A / V_B / pooled | all / <20 / 20–39 / ≥40 / <40 | each candidate; each fitted head | — | — | — | — | — | — |

### Train–validation gap

| Candidate/head | Labelled train n | Train PR-AUC | V_A PR-AUC | V_B PR-AUC | Pooled PR-AUC |
|---|---|---|---|---|---|
| Every fitted head | — | — | — | — | — |

### Composite length shortcuts

| Part | Candidate (beside B-skill) | AUC for <20 | AUC for <40 |
|---|---|---|---|
| V_A / V_B / pooled | every candidate | — | — |

### Paired differences

| Part/stratum | Comparator | ΔPR-AUC | Paired 95% CI | Skipped resamples |
|---|---|---|---|---|
| each report population | P3-B/v3 / R-pre / B-streak / B-skill | — | — | — |

### Calibration, determinism and gate

Pending operator: every frozen/cross Platt status, bundle hashes, largest prediction difference, metric identity and all gate conditions. S4 gate verdict: **not run on real labels**. S5 requires a separate user decision. No adoption decision is made by this handoff.

## End verification

`S4/end_checks.json` records the final current/snapshot lock checks, append-only equality, all five S3 input hashes plus the gate hash, frozen module/design hashes, both feature-content baselines, the unchanged deployment bundle/pointer hashes and passed synthetic/test evidence. Final `sha256sum -c` for current and snapshot documents: **OK**. No S3 file, processed-root file, deployment file or preregistration was changed. Source code and exact transfer lists are packaged outside the repository; no commit or push was made.

## Full-run Results (operator, 2026-11-17)

Run on a rented 24-CPU box (Ubuntu 24.04, Python 3.12), `p3b --processes 12`, classifier threads 2. Attempt 1 stopped in
`train` (Erratum 6, see Deviations) and is preserved as `S4/run1_failed_attempt1/`. Attempt 2 ran the whole operator
script from scratch in fresh directories; prereg lock `851858bc…`; it finished with exit 0 in 2 min 38 s.

### Status

- Tests on the box: full suite 532 passed, 2 skipped; S4 tests 44 passed.
- Whole-game parity: 36,329 old rows / 196 players, 11 columns, 0 mismatches, max |diff| 0.0 (tolerance 1e-9); table sha `578ad825…`.
- Determinism: run1 vs run2 largest prediction difference 0.0; passed.
- **S4 gate PASSED** in both runs (V_A and V_B beat `R-pre`, pooled CI > 0, calibration normal, parity, tests/isolation, determinism).
- Hashes: run1 predictions `3e216168…`, gate `a49aa494…`, determinism `099e2137…`. Frozen bundles are those of `run1/bundles/` (`bundles.sha256`).

### Validation PR-AUC (composite, cross-fitted Platt) with 95% player-clustered CI

**all games**

| Candidate | V_A | V_B | Pooled |
|---|---|---|---|
| n / positives / prevalence | 5,352 / 443 / 0.083 | 4,659 / 335 / 0.072 | 10,011 / 778 / 0.078 |
| M-v3 | 0.510 [0.460, 0.565] | 0.455 [0.401, 0.513] | 0.486 [0.448, 0.526] |
| P3-B/v3 | 0.171 [0.146, 0.203] | 0.151 [0.122, 0.188] | 0.161 [0.143, 0.183] |
| B-skill | 0.092 [0.073, 0.121] | 0.108 [0.082, 0.161] | 0.097 [0.081, 0.119] |
| R-pre | 0.293 [0.259, 0.337] | 0.270 [0.231, 0.323] | 0.282 [0.255, 0.313] |
| B-streak | 0.167 [0.137, 0.205] | 0.146 [0.122, 0.177] | 0.157 [0.137, 0.180] |
| M-v3-ns | 0.500 [0.449, 0.555] | 0.461 [0.405, 0.519] | 0.482 [0.446, 0.521] |
| P3-B@20/v3 | 0.107 [0.087, 0.139] | 0.096 [0.079, 0.122] | 0.102 [0.088, 0.120] |
| P3-B frozen | 0.144 [0.122, 0.172] | 0.121 [0.097, 0.150] | 0.131 [0.116, 0.150] |
| B-result | 0.204 [0.175, 0.234] | 0.175 [0.152, 0.199] | 0.190 [0.173, 0.209] |
| B-length | 0.058 [0.048, 0.071] | 0.056 [0.047, 0.069] | 0.057 [0.050, 0.064] |
| Δ M-v3-B-skill | +0.418 [+0.369, +0.469] | +0.347 [+0.289, +0.400] | +0.389 [+0.354, +0.425] |
| Δ M-v3-B-streak | +0.343 [+0.286, +0.401] | +0.310 [+0.258, +0.362] | +0.329 [+0.290, +0.366] |
| Δ M-v3-P3-B/v3 | +0.340 [+0.289, +0.391] | +0.304 [+0.244, +0.364] | +0.325 [+0.287, +0.364] |
| Δ M-v3-R-pre | +0.217 [+0.164, +0.262] | +0.185 [+0.137, +0.230] | +0.204 [+0.172, +0.235] |

**< 20 plies**

| Candidate | V_A | V_B | Pooled |
|---|---|---|---|
| n / positives / prevalence | 176 / 40 / 0.227 | 134 / 23 / 0.172 | 310 / 63 / 0.203 |
| M-v3 | 0.650 [0.471, 0.823] | 0.562 [0.380, 0.749] | 0.609 [0.460, 0.741] |
| P3-B/v3 | 0.375 [0.252, 0.567] | 0.342 [0.208, 0.568] | 0.345 [0.255, 0.502] |
| B-skill | 0.261 [0.171, 0.394] | 0.241 [0.142, 0.431] | 0.238 [0.179, 0.330] |
| R-pre | 0.603 [0.422, 0.768] | 0.521 [0.322, 0.738] | 0.554 [0.421, 0.686] |
| B-streak | 0.369 [0.251, 0.512] | 0.293 [0.180, 0.464] | 0.335 [0.249, 0.449] |
| M-v3-ns | 0.655 [0.485, 0.834] | 0.588 [0.400, 0.764] | 0.609 [0.477, 0.737] |
| P3-B@20/v3 | 0.244 [0.171, 0.354] | 0.376 [0.177, 0.582] | 0.295 [0.197, 0.411] |
| P3-B frozen | 0.268 [0.192, 0.406] | 0.340 [0.194, 0.529] | 0.267 [0.200, 0.386] |
| B-result | 0.567 [0.481, 0.660] | 0.523 [0.385, 0.659] | 0.548 [0.474, 0.635] |
| B-length | 0.251 [0.162, 0.377] | 0.136 [0.089, 0.209] | 0.193 [0.137, 0.266] |
| Δ M-v3-B-skill | +0.389 [+0.258, +0.507] | +0.321 [+0.094, +0.507] | +0.371 [+0.253, +0.473] |
| Δ M-v3-B-streak | +0.280 [+0.156, +0.395] | +0.269 [+0.091, +0.418] | +0.274 [+0.172, +0.374] |
| Δ M-v3-P3-B/v3 | +0.275 [+0.053, +0.434] | +0.220 [-0.060, +0.419] | +0.263 [+0.088, +0.390] |
| Δ M-v3-R-pre | +0.046 [-0.031, +0.120] | +0.042 [-0.105, +0.167] | +0.055 [-0.016, +0.123] |

**20–39 plies**

| Candidate | V_A | V_B | Pooled |
|---|---|---|---|
| n / positives / prevalence | 860 / 117 / 0.136 | 645 / 71 / 0.110 | 1,505 / 188 / 0.125 |
| M-v3 | 0.683 [0.594, 0.778] | 0.746 [0.648, 0.870] | 0.705 [0.640, 0.783] |
| P3-B/v3 | 0.242 [0.193, 0.323] | 0.200 [0.139, 0.281] | 0.223 [0.177, 0.277] |
| B-skill | 0.170 [0.128, 0.221] | 0.224 [0.128, 0.345] | 0.189 [0.143, 0.249] |
| R-pre | 0.322 [0.263, 0.410] | 0.380 [0.269, 0.517] | 0.334 [0.280, 0.407] |
| B-streak | 0.209 [0.171, 0.267] | 0.253 [0.162, 0.372] | 0.214 [0.179, 0.268] |
| M-v3-ns | 0.685 [0.592, 0.783] | 0.742 [0.654, 0.857] | 0.704 [0.635, 0.783] |
| P3-B@20/v3 | 0.159 [0.118, 0.240] | 0.143 [0.102, 0.197] | 0.149 [0.120, 0.198] |
| P3-B frozen | 0.193 [0.150, 0.258] | 0.133 [0.096, 0.184] | 0.162 [0.131, 0.200] |
| B-result | 0.351 [0.286, 0.427] | 0.285 [0.220, 0.349] | 0.324 [0.279, 0.370] |
| B-length | 0.145 [0.112, 0.187] | 0.103 [0.074, 0.134] | 0.126 [0.102, 0.152] |
| Δ M-v3-B-skill | +0.512 [+0.421, +0.605] | +0.522 [+0.399, +0.672] | +0.517 [+0.449, +0.603] |
| Δ M-v3-B-streak | +0.473 [+0.393, +0.558] | +0.494 [+0.352, +0.647] | +0.491 [+0.419, +0.566] |
| Δ M-v3-P3-B/v3 | +0.441 [+0.325, +0.538] | +0.547 [+0.406, +0.690] | +0.483 [+0.395, +0.579] |
| Δ M-v3-R-pre | +0.361 [+0.281, +0.425] | +0.366 [+0.237, +0.521] | +0.372 [+0.305, +0.439] |

**≥ 40 plies**

| Candidate | V_A | V_B | Pooled |
|---|---|---|---|
| n / positives / prevalence | 4,316 / 286 / 0.066 | 3,880 / 241 / 0.062 | 8,196 / 527 / 0.064 |
| M-v3 | 0.455 [0.389, 0.534] | 0.366 [0.310, 0.425] | 0.414 [0.368, 0.466] |
| P3-B/v3 | 0.126 [0.103, 0.156] | 0.124 [0.097, 0.164] | 0.123 [0.105, 0.146] |
| B-skill | 0.073 [0.058, 0.099] | 0.087 [0.067, 0.125] | 0.078 [0.065, 0.095] |
| R-pre | 0.278 [0.246, 0.321] | 0.236 [0.204, 0.283] | 0.257 [0.231, 0.288] |
| B-streak | 0.147 [0.115, 0.185] | 0.122 [0.101, 0.148] | 0.134 [0.116, 0.156] |
| M-v3-ns | 0.439 [0.374, 0.520] | 0.372 [0.317, 0.432] | 0.408 [0.363, 0.459] |
| P3-B@20/v3 | 0.091 [0.070, 0.122] | 0.080 [0.064, 0.107] | 0.085 [0.071, 0.105] |
| P3-B frozen | 0.088 [0.073, 0.112] | 0.083 [0.066, 0.108] | 0.085 [0.074, 0.100] |
| B-result | 0.159 [0.132, 0.189] | 0.148 [0.126, 0.170] | 0.154 [0.138, 0.171] |
| B-length | 0.049 [0.039, 0.062] | 0.052 [0.042, 0.066] | 0.050 [0.043, 0.059] |
| Δ M-v3-B-skill | +0.381 [+0.317, +0.452] | +0.278 [+0.222, +0.331] | +0.336 [+0.289, +0.384] |
| Δ M-v3-B-streak | +0.308 [+0.240, +0.386] | +0.244 [+0.193, +0.297] | +0.280 [+0.234, +0.327] |
| Δ M-v3-P3-B/v3 | +0.329 [+0.263, +0.402] | +0.242 [+0.179, +0.299] | +0.290 [+0.242, +0.340] |
| Δ M-v3-R-pre | +0.176 [+0.114, +0.237] | +0.129 [+0.080, +0.177] | +0.156 [+0.117, +0.196] |

### Train–validation gap (per fitted head, PR-AUC)

| Head | Train | V_A | V_B | Pooled |
|---|---|---|---|---|
| B-skill::p20 | 0.205 | 0.086 | 0.105 | 0.091 |
| B-skill::pre | 0.209 | 0.092 | 0.101 | 0.095 |
| M-v3-ns::p20 | 0.539 | 0.502 | 0.460 | 0.483 |
| M-v3-ns::pre | 0.385 | 0.315 | 0.274 | 0.296 |
| M-v3::p20 | 0.545 | 0.512 | 0.456 | 0.487 |
| M-v3::pre | 0.405 | 0.313 | 0.282 | 0.299 |
| P3-B/v3::whole | 0.237 | 0.171 | 0.151 | 0.161 |
| P3-B@20/v3::p20 | 0.153 | 0.102 | 0.088 | 0.095 |
| P3-B@20/v3::pre | 0.134 | 0.098 | 0.087 | 0.093 |

### Composite length shortcuts (symmetric ROC AUC of the score for the length class)

| Candidate | V_A <20 / <40 | V_B <20 / <40 | Pooled <20 / <40 |
|---|---|---|---|
| M-v3 | 0.742 / 0.557 | 0.737 / 0.544 | 0.740 / 0.551 |
| M-v3-ns | 0.740 / 0.581 | 0.740 / 0.556 | 0.741 / 0.570 |
| P3-B/v3 | 0.688 / 0.639 | 0.692 / 0.652 | 0.690 / 0.646 |
| B-skill | 0.594 / 0.505 | 0.607 / 0.514 | 0.601 / 0.504 |
| R-pre | 0.570 / 0.537 | 0.551 / 0.536 | 0.562 / 0.536 |
| B-streak | 0.575 / 0.552 | 0.585 / 0.544 | 0.579 / 0.549 |

### Operator notes

- M-v3 beats every adoption comparator (P3-B/v3, B-skill, `R-pre`, B-streak) on validation in every length stratum, except `R-pre` at < 20 plies (Δ +0.05, CI covers 0) and P3-B/v3 at < 20 plies on V_B (CI covers 0). The adoption decision itself is made only on A′/B′ in S5.
- M-v3 is a distillation of deterministic rules, and much of its signal is the session context the rules read (C1–C5); `R-pre` alone reaches PR-AUC 0.28. High scores measure agreement with the v3 rules, not with self-reported tilt.
- The composite score separates < 20-ply games from the rest with AUC ≈ 0.74 (< 20-ply prevalence ≈ 0.20 vs 0.078 overall); for < 40 plies it is ≈ 0.55. Reported only; not a gate in S4.
- No holdout (A′/B′) row was read. No refit before S5.
