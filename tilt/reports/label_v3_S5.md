# Label v3 — S5 holdout evaluation

Status: **ready for operator execution**; real holdout evaluation remains operator work.
Authority: Addendum S5, acknowledged S5.0 (2026-11-17), and Errata 7–8.
No holdout value column, label, feature or score was read or computed by this
Codex run. Real checks were input verification, development equivalence on five
old-cohort players, and the E8.6 keys-only read plan for all development players. No fitting, recalibration, network, commit or push.

## Design

`src/tilt/evaluation/v3_holdout.py` provides `verify`, `equivalence`, `build`,
`score`, `evaluate`, `compare`, and the standalone keys-only `header-plan` phase. Every root, stage directory, document, lock,
snapshot, bundle directory, deployed pointer/bundle and destination is explicit.
`--players 1..5` is accepted only by equivalence, chooses old development players,
and produces `complete: false`, which cannot unlock build. `--processes` controls
ordered, bounded, spawned player workers; it changes no persisted configuration.

Verification hashes the complete current document and lock, verifies S4 and S3
snapshots and their locks, and checks both byte-prefix relationships. Frozen S4
verification receives the S4 document and passes the S3 document to frozen S3
verification. It checks S3 design/table/manifest hashes, root feature content
hashes (E3.7), all recorded S4 code hashes including `cohort_v3.py`, S4 prediction
and whole-game hashes, all five bundles and deployed P3-B. The S4 code-hash file,
bundle-hash list and training provenance are independently pinned in S5.
Paths, worker counts, clocks and memory measurements never enter run outputs.

`verify.json` additionally records phase artifact hashes and the premetric build
audit. Each subsequent process revalidates inputs, prerequisites and previous
outputs. Existing phase outputs are refused. The operator refuses any existing
run or test outputs. `compare` requires precisely the S5.9 file inventory, checks
every artifact and compares every output byte, including verify/equivalence.
Only then is the adoption verdict written to `S5/adoption.json`. A valid
“not adopted” decision exits zero. No pointer or deployment artifact is changed.

The plain-target adapter changes only the transport frame's `assignment` and
`part` for frozen guards. Original A′/B′ parts are restored outside the frozen
functions. Rule aggregation, eligibility, evidence, label combination, prior
labels, S′ context, exact gaps, complete-prefix windows, prefix features and
whole-game dynamics all execute inside the unchanged S3/S4 functions. Build
selects only manifest A′/B′ targets and preserves all same-player history.
Development rows are history only. Shared-game holdout sides remain targets.

Equivalence rebuilds all development labels, including the S3 incomplete targets
whose labels were retained, both feature tables, the incomplete-exclusion table,
whole-game features and frozen inference. The full operator path retains the
same start/session-only next-game boundary metadata that S3 needed for E7; it
reads no holdout moves or whole-game aggregates and builds no holdout labels or
features. Smoke uses old players and does not read even that boundary metadata.
The development loader filters membership before projecting header values.

E7.1 compares every fitted head/composite `::raw` and `::frozen`, plus all
unfitted/deployed reference columns. It inspects the S4 prediction schema, then
projects only compared columns: fitted cross-fold `::calibrated` values are
never loaded, copied or used. Every column must occur on exactly one explicit
compared/excluded list in `equivalence.json`; missing or unknown columns stop.
Every table/column must match exactly, with null equal to null and tolerance 0.

Scoring applies the stored all-validation Platt object through `predict_bundle`.
There is no fitting call. The two-head composite switches at 20 plies; P3-B/v3
has one whole-game head. B-result alone fills null results as draws (0.5).
Whole-game tables remain isolated from every early-model matrix. ABSTAIN rows
receive predictions but enter no metric, calibration diagnostic or bootstrap.

Before the first metric, all S5.7 stops are checked: hashes, full equivalence,
one-colour exclusions and E4.5 own-colour stop, registered target/drop counts,
label/pre/P-20/whole row coverage and parts, exact manifest membership and the
0.5% known-end overlap bound. Build publishes no metrics or label statistics.
The count/overlap audit is retained inside verify.json for rechecking by score
and evaluate. Unexpected incomplete patterns raise in the frozen functions.

Metrics cover A′, B′ and pooled; all, <20, 20–39, ≥40 and <40 strata; composites
and individual heads on their available populations. PR-AUC, prevalence, ROC AUC
are reported for all candidates; Brier/ECE/reliability for fitted candidates.
ECE uses the unchanged 10 quantile bins with collapsed duplicate edges from
`phase1.calibration_bins`. Length diagnostics use labelled rows only.

Bootstrap calls the frozen S4 implementation of Phase 5's player-clustered,
paired, 1,000-resample seed-42 percentile-95% procedure. Rows from a sampled
player repeat together. One-class draws are skipped and both skip reasons are
recorded. Columns sharing a population share the identical draw stream; the
P3-B@20 frozen reference uses P-20 for its paired comparison. Every composite
comparator is paired with M-v3 in every stratum, including descriptive references.

Adoption has exactly 16 cells: two parts × two length strata × four comparators.
Each needs CI lower bound >0, ≥30 TILT rows and ≤100 skipped draws. Both parts'
all-labelled M-v3 composite ECE must be ≤0.05. All failures are listed. Pooled
and all-games comparison figures do not decide. Success means adopted in
principle; deployment still requires the separate deployment addendum.

## Deviations

Attempt 1 correctly stopped under §8 because cross-fold Platt models were not
saved, so S4 `::calibrated` scores could not be independently reproduced without
forbidden fitting. Its audit and test evidence remain unchanged in
`~/tilt-labels-v3/S5/attempt1_stop/`. Erratum 7.1 resolves this by requiring raw
and frozen score equivalence and explicitly excluding the fitted cross-fold
columns. No model was refitted and the S4 predictions were not modified.

The attempt-1 suite also exposed a frozen S4 test that pins the earlier document
hash. E7.2 resolves this without changing the frozen test. The suite deselects
exactly `tests/unit/test_v3_p3b.py::test_frozen_s3_files_and_real_document_are_unchanged`.
The new append-only test verifies both snapshot prefixes/locks, the current lock,
and all six protected modules. `test_evidence.json` records the node id, reason,
counts and the two existing opt-in real-sample skips. No additional skip, xfail
or deselection is allowed. `S3_REAL_CONFIG` is unset; the original S3 real-data
sample is not reopened.

Mechanical choices: underscore part names `A_prime`/`B_prime`; canonical key
order; frozen fitted inference columns retain the S4 suffix `::frozen`; unfitted
references retain their S4 `::calibrated` names. Timing/memory evidence is outside
the deterministic run directories. Synthetic process tests substitute only test
input seams; no production synthetic mode or verification bypass is exposed.

## Input hashes

| Input | SHA256 |
|---|---|
| Current document / lock | `7ec4570b50b374c95280d4d15159007b1ebc238a5ec6ffaf2d51f2e8fa241f47` |
| S4 snapshot | `851858bca40d46ff6ee76a1b62bcab19e89581b03f59e9193e43eca1f072204f` |
| S3 snapshot | `827890324bdd0e17cef555b770920c972ba10d6bbc9552e830b4f1b7b06c665e` |
| rules_v3.py | `9f2d8234377999965699be45aa466595447fad3dcf93709cf7ff89ed5a2a0a8a` |
| prefix_v3.py | `71b92e6e8ca3bde07508cc29a88aa1563e8ece7af1a640de4f3e5a4536b53f3d` |
| split_v3.py | `f426e79254167d3f998f1b075f720b3b89098d52b37930f4bf975bd3fb6fa4ff` |
| v3_train.py | `ee8c3ca08f154d350da46c297677b0b898f9983b71ce1d879a4f7da53eae99b5` |
| v3_p3b.py | `1fa43330c85884b3bdeab3ae6645a4beb9b46098962f51d1110fa1ebf3bffa0e` |
| cohort_v3.py | `08f33a448fdf199556fc879491eb4b9f3b9d3f6e4ed938c105d3e5c5dbd2dc9d` |

Full S1/S2/S3/S4 input and bundle hashes are recorded in smoke `verify.json`;
the operator records them independently in each full run. S5 code hash and
final test counts are added below after verification completes.

## Operator attempt 1 crash and Erratum 8

Operator run 1 verified its inputs, then crashed in `development_headers` before
writing `equivalence.json`. The two independent player/game filters selected a
cross product. A new development player's `drop_shared_development` side shared
a physical game with another development player's B′ side. The value read
returned both sides; the boundary read returned them again and hard-tagged both
B′. The resulting duplicate keys caused the merge to fail. No build, score or
evaluate phase started. The crashed logs, verify file and test evidence remain
in `S5/operator_attempt1_crash/`.

E8.3 deviation: the old reader materialised header values of exactly **10 B′
sides**, measured from keys alone in `S5/header_plan.json`. These values were not
used for computation, written or shown. The operator's module hash before the
fix was `2225bed059dc14728023414a4da01c5cf29b29737d7dda8f19f3e07e1e08d49b`;
the corrected module hash is `42028a46fc8c60396fb72757631c8bc17dfbc2ea32e64597edae6b98d720a819`.
Both hashes now appear in `verify.json` under `s5_module_sha256`.

The corrected loader builds its per-side plan from keys and assignments before
projecting values. Each read selects one processed player, exact game ids and
colour. Non-holdout histories include both cohorts' `drop_shared_development`
sides and new incidental history. Erratum 2 sides are already absent from the
stored feature keys. Boundary reads select only the processed player's own B′
sides and only start/session metadata. Assignment comes from the manifest.
Raw and exported player/game identities are retained as keys for the frozen
aggregator; every other boundary column is null. A′ sides never enter the
header frame. The four E8.4 assertions run before the target merge and each
failure raises a clear §8 stop. `equivalence.json` records their results and
counts only under `headers`.

Cross-product audit: the two affected `features/games.parquet` reads were the
value and boundary reads in `development_headers`; both are replaced. The old
cohort's call to frozen `target_bridge` also selected header values by a set of
start times. That call is removed from equivalence: S3's deterministic player
identity `split_key` selects the raw players from keys alone, and the old export
metadata bridges only those selected non-holdout histories. The frozen S3
header loader is never called in equivalence. Old export metadata is limited
to the selected old players. S3/S4 reference tables contain development rows
only. The remaining game-id reads are physical-game raw metadata and moves;
move selection remains per processed player's non-holdout games, including
shared development histories. Frozen whole-game workers receive only that
player's exact development targets. There is no remaining cross-product
per-side value projection in the S5 module. The keys-only old-reader reference
is used solely to count E8.3; the executable old value reader exists only in tests.

Build retains the frozen S3 loader. Before labels/features, it asserts unique
header keys and exact manifest target membership, uses the frozen E4 move
presence audit to derive incomplete-prefix drops, and asserts the retained set
equals manifest A′/B′ sides minus those drops. Incomplete rows still reach the
frozen label path for the E4 own-colour stop; frozen feature exclusion is unchanged.

The keys-only phase uses `player`, `game_id`, `color` from both stored roots;
manifest identity keys (including S3 `split_key`) and assignment/part only. An IO
guard rejected any other projection during the real check. It read zero value
columns. One preliminary key-plan invocation stopped before producing an output:
it incorrectly tried to identify all old players through S2, which records only
shared old sides and uses a different pseudonym from S3's legacy exports. This
was corrected with S3's deterministic player key, with a synthetic regression
for sparse S2 old membership and an unrelated stored player. The intended row
set, locked rules and assertions did not change. The stop log is preserved in
`S5/header_plan_preflight_stop_e8.txt`; its module hash was
`698d404f1dea17190226909901c4f349c812a6319c36ff564b52c7d3a85600c8`, followed
by the corrected hash above. No value was read by either key-plan invocation.
There was one completed keys-only check; it passed all three assertions.

`header_plan.json` counts (all 338 development players):

| Count | Old | New |
|---|---:|---:|
| Development players | 196 | 142 |
| Stored sides of those players | 36,401 | 20,854 |
| Non-holdout value-plan sides | 36,401 | 16,015 |
| Own B′ boundary sides | 0 | 4,839 |
| Shared physical games within selected players | 114 | 51 |
| Assignment `development` | 36,389 | 15,943 |
| Assignment `drop_shared_development` | 12 | 16 |
| Assignment `history_only` | 0 | 56 |
| Assignment `B_prime` | 0 | 4,839 |

Unique keys, no holdout side in the value plan, and boundary sides exactly equal
to own B′ sides: all true. E8.3 count: **10**. Value columns read: **0**.
No holdout value-path equivalence or real build/score/evaluate was run locally.

## Validation and smoke

Final-code development equivalence passed on **5 old players, 750 rows, max
absolute difference 0.0**, across labels, F-pre, F-p20, whole-game features and
required predictions. Scope remains 42 compared columns and 14 fitted
cross-fold columns explicitly excluded. Evidence is fresh:
`S5/smoke_dev_e8/{verify,equivalence}.json`, `S5/smoke_dev_e8.log`, and
`S5/smoke_dev_e8_runtime.txt`. The headers assertions all pass; no boundary or
holdout side is read on this smoke. Elapsed 53.67 seconds, peak RSS 1,119,720 KiB (1.07 GiB), processes=1.
Prior smoke directories remain intact.

S5 implementation SHA256: `42028a46fc8c60396fb72757631c8bc17dfbc2ea32e64597edae6b98d720a819`.
All six protected module hashes remain unchanged (table above). The complete
code and frozen-file hash list is in `S5/code_hash.txt` and `S5/codex-last.md`.

Final full suite: **598 passed, 2 baseline skips, 1 E7.2
deselection**, no failures or xfails (196.60 seconds). New suite:
**67 passed**, no skips or deselections (73.20 seconds).
Evidence: `S5/tests_full_e8_final.{txt,xml}`,
`S5/tests_new_e8_final.{txt,xml}`, `S5/test_evidence_e8.json`.
The operator count identity holds: 600 collected after deselection = 533 + 67;
598 passed = 531 + 67. The only suite warning is the existing Starlette/AnyIO
deprecation. The real smoke additionally emitted pandas' existing all-null
concatenation FutureWarning; its exact comparisons passed.
Synthetic coverage now includes all E8.5 sharing cases, old/new dropped
history, exact value projections, each loader assertion, wrong-player and
wrong-assignment boundary stops, the old reader failing the assertions,
keys-only IO, old identity bridging and pre-computation build guards.
The end-to-end fixture uses the actual header loader with shared games and six
B′ boundary rows, full non-`--players` equivalence, and every CLI phase in fresh
processes. One-worker and two-worker runs must produce byte-identical outputs.

## Runbook

Start from the accepted S4 package and environment, with the incremental S5
archives extracted. Exact tar input lists and the S4-list audit are in
`S5/transfer_code_files.txt`, `S5/transfer_v3_files.txt`, `S5/transfer_notes.md`.
The incremental package adds all five S4 bundles, bundle/code hashes, the two
S4 run1 tables, training_provenance.json, both S4-snapshot files, current lock,
current report/preregistration and new code/tests/scripts. The S4 package already
includes every S1/S2/S3 file S5 reads, including the holdout manifest.

Package without network:

```bash
V3/S5/package_s5.sh CODE V3 FRESH_PACKAGE_DEST
```

Under E8.7, move the crashed `run1/` and test outputs/logs into
`v3/S5/operator_attempt1_crash/` before extracting the new package over the
accepted S4 trees. Keep that directory. Start fresh `run1/`, `run2/` and test
outputs; reuse no crashed phase file. Restart from `verify`.

Run once on the rented box (paths must be absolute or resolve correctly):

```bash
V3/S5/operator_s5.sh CODE OLD_PROCESSED NEW_PROCESSED V3 DEPLOYED_JSON BUNDLE 2
```

In this WSL environment export
`PYTHONPATH=/home/trantrien/tilt-labels-v2/test_runtime` first. Remote dependencies
are the already-provisioned S4 environment; neither script installs anything.
Operator checks locks/snapshots/inputs, runs full and new suites with JUnit XML
and JSON evidence, then runs every phase in fresh processes for run1 and run2,
without reading run1 between them, and compares. Any stop exits nonzero. Preserve
all outputs; do not change settings or restart after a metric exists except for
the preregistered value-preserving crash-fix procedure. A not-adopted verdict is
successful script completion and keeps P3-B deployed.

## Results placeholders (S5.9)

All holdout entries remain pending operator execution. Expected counts in the
preregistration are guards, not measured results in this report.

| Output (both run1 and run2 unless stated) | Status |
|---|---|
| verify.json | Full operator runs pending |
| equivalence.json | Full development equivalence pending; smoke passed |
| labels_holdout.parquet | Not built |
| features_pre_holdout.parquet | Not built |
| features_p20_holdout.parquet | Not built |
| features_p3b_whole_holdout.parquet | Not built |
| excluded_incomplete_moves_holdout.csv | Not built |
| predictions_holdout.parquet | Not scored |
| metrics_holdout.json | Not evaluated |
| bootstrap_holdout.json | Not evaluated |
| length_auc_holdout.json | Not evaluated |
| S5/determinism.json | Real runs not compared |
| S5/adoption.json | No real verdict written |

Target/exclusion and label counts: pending. Full metric tables by part, stratum
and head: pending. Sixteen deciding intervals and estimability checks: pending.
M-v3 composite ECE for each part: pending. Length-shortcut table: pending.
Failed adoption cells and adoption verdict: pending.

The result describes how well M-v3 predicts the v3 rule early, not how well it
measures emotion.

## Full-run Results (operator, 2026-11-17)

These results supersede the placeholders above. Operator attempt 2 ran on the rented box
(24 CPU, `--processes 8`) from the Erratum 8 package: lock `7ec4570b…`, S5 module
`42028a46…` (before: `2225bed0…`, both in `verify.json`). The six frozen modules were unchanged.
It started at 07:52 UTC and finished with `EXIT=0` after 13 min 14 s, covering both runs and `compare`.

**Status: M-v3 ADOPTED in principle.** All 16 deciding cells were met, and ECE ≤ 0.05 on both parts.
Determinism: all 11 run files were byte-identical between run1 and run2. No deployment artifact was
changed (`deployment_changed: false`). P3-B stays deployed until the deployment addendum is approved.

### Checks before metrics
- Suites: the full suite had 598 passed, 2 baseline skips and the 1 E7.2 deselection. The new suite had 67 passed.
- Equivalence covered all 338 development players and matched with max |diff| 0.0:
  - labels: 52,273;
  - F-pre: 52,239;
  - F-p20: 49,847;
  - whole-game: 52,239;
  - incomplete drops: 34;
  - predictions: 52,239.
- Equivalence `headers`: B′ boundary rows 4,839; shared games 165; sides were 52,332 development,
  28 `drop_shared_development` and 56 `history_only`. All four E8.4 assertions held.
- Build: targets A′ 9,658 and B′ 4,989. Incomplete-prefix drops were exactly A′ 7 and B′ 0.
- E3.2 known-end overlap: 7 of 14,647 targets (0.05%, threshold 0.5%). The upper-bound overlap of 192 is
  diagnostic only.

### Labels
| Part | Rows | TILT | NOT | ABSTAIN | Labelled | Prevalence |
|---|---:|---:|---:|---:|---:|---:|
| A′ | 9,658 | 404 | 4,957 | 4,297 | 5,361 | 0.075 |
| B′ | 4,989 | 212 | 2,722 | 2,055 | 2,934 | 0.072 |

Labelled rows by stratum, with TILT counts in brackets:

| Part | ≥ 40 | < 40 | 20–39 | < 20 |
|---|---:|---:|---:|---:|
| A′ | 4,485 (304) | 876 (100) | 748 (84) | 128 (16) |
| B′ | 2,427 (159) | 507 (53) | 416 (39) | 91 (14) |

### PR-AUC, all labelled rows (95% CI)
| Model | A′ | B′ |
|---|---|---|
| **M-v3 composite** | **0.458 [0.403, 0.520]** | **0.451 [0.385, 0.520]** |
| R-pre | 0.267 [0.232, 0.312] | 0.253 [0.221, 0.292] |
| B-result | 0.182 [0.154, 0.213] | 0.164 [0.135, 0.189] |
| B-streak | 0.150 [0.127, 0.176] | 0.136 [0.114, 0.162] |
| P3-B/v3 | 0.139 [0.116, 0.170] | 0.148 [0.120, 0.189] |
| P3-B frozen (deployed) | 0.113 [0.092, 0.138] | 0.098 [0.077, 0.129] |
| B-skill | 0.096 [0.075, 0.127] | 0.083 [0.067, 0.104] |
| B-length | 0.055 | 0.056 |

M-v3 composite ROC AUC: 0.918 (A′) and 0.916 (B′). ECE: 0.0058 (A′) and 0.0050 (B′).
The S4 validation pooled PR-AUC was 0.486; the holdout values are slightly lower, with overlapping intervals.

### PR-AUC by stratum (M-v3 composite vs comparators)
| Part · stratum | M-v3 | R-pre | P3-B/v3 | B-streak | B-skill |
|---|---:|---:|---:|---:|---:|
| A′ ≥ 40 | 0.379 | 0.244 | 0.115 | 0.135 | 0.083 |
| A′ < 40 | 0.747 | 0.374 | 0.222 | 0.217 | 0.164 |
| A′ < 20 (16 TILT, not deciding) | 0.407 | 0.331 | 0.436 | 0.215 | 0.127 |
| B′ ≥ 40 | 0.390 | 0.246 | 0.128 | 0.126 | 0.072 |
| B′ < 40 | 0.662 | 0.307 | 0.208 | 0.189 | 0.155 |
| B′ < 20 (14 TILT, not deciding) | 0.443 | 0.435 | 0.350 | 0.318 | 0.279 |

### Sixteen deciding cells (Δ PR-AUC M-v3 − comparator, 95% CI, 1,000 resamples, 0 skipped)
| Part | Stratum | P3-B/v3 | R-pre | B-streak | B-skill |
|---|---|---|---|---|---|
| A′ | ≥ 40 (304 TILT) | +0.263 [0.215, 0.318] | +0.135 [0.084, 0.190] | +0.244 [0.197, 0.301] | +0.296 [0.247, 0.353] |
| A′ | < 40 (100 TILT) | +0.526 [0.398, 0.621] | +0.373 [0.258, 0.463] | +0.530 [0.440, 0.607] | +0.584 [0.474, 0.677] |
| B′ | ≥ 40 (159 TILT) | +0.262 [0.185, 0.341] | +0.144 [0.081, 0.217] | +0.264 [0.192, 0.350] | +0.318 [0.246, 0.401] |
| B′ | < 40 (53 TILT) | +0.454 [0.307, 0.564] | +0.354 [0.235, 0.458] | +0.473 [0.343, 0.573] | +0.507 [0.383, 0.626] |

Every cell had ≥ 30 TILT rows and 0 skipped resamples. The lowest lower bound is +0.081 (B′ ≥ 40 vs `R-pre`).

### Length shortcut (symmetric AUC of the score for separating short games; reported, not deciding)
| Score | A′ < 20 | A′ < 40 | B′ < 20 | B′ < 40 |
|---|---:|---:|---:|---:|
| M-v3 | 0.738 | 0.540 | 0.748 | 0.536 |
| P3-B frozen (deployed) | 0.927 | 0.881 | 0.913 | 0.865 |
| P3-B/v3 | 0.697 | 0.680 | 0.647 | 0.640 |
| R-pre | 0.562 | 0.524 | 0.579 | 0.528 |

M-v3 still separates games under 20 plies (AUC ≈ 0.74, as in S4). It is far less length-driven than the
deployed P3-B (0.87–0.93).

### Notes
- `< 20` is tiny (16 and 14 TILT) and does not decide. There, M-v3 is not better than every reference:
  on A′, P3-B/v3 is 0.436 against 0.407.
- M-v3 is a distillation of the v3 rule. A high score means "likely to match the v3 rule after the game", not
  measured emotion.
- After S5, A′ and B′ are open. No later model may be evaluated on them as untouched data.
- Hashes:
  - `adoption.json`: `8e7fb902…`
  - `determinism.json`: `754013cd…`
  - `predictions_holdout.parquet`: `55fd7f74…`
  - `metrics_holdout.json`: `d278124d…`
  - `labels_holdout.parquet`: `ef9529ed…`
  - `equivalence.json`: `fee8e525…`
- Local copies:
  - `~/tilt-labels-v3/S5/{run1,run2,determinism.json,adoption.json}`;
  - operator test evidence and log in `S5/operator_attempt2/`, with all 29 file hashes checked against the box.
