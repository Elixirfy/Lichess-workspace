# Label v3 — I1 worker results (M-v3 live path)

Date: 2026-11-17. Spec: `reports/label_v3_deployment.md` (I0, approved 2026-11-17). Operator: Claude.
All outputs are counts. Player names and game ids are not recorded.

## Code
- `src/tilt/core/live_v3.py` (new):
  - loads and checks `deployed_v3.json`: bundle and registry sha256, bands, the features manifest, and the six
    frozen v3 modules;
  - builds live headers;
  - scores with the frozen `predict_bundle`/`composite`;
  - computes SHAP signs (§5), the fast reason (§6) and the rule check (§7);
  - `install` writes the pointer.
- `src/tilt/workers/lila_worker.py`:
  - **v3 mode** when the pointer exists: skips non-blitz docs (`skip: "speed"`) and collects a blitz-only root
    `<lila-data>-v3`. It refuses engine settings other than `ca2f1c3a…`, writes `skip: "incomplete"`, runs
    the P3-B shadow until `shadow_until`, and refreshes the pending E7 of the player's earlier docs (at most 5).
  - **Without the pointer**, the previous P3-B path runs unchanged.
- `src/tilt/__main__.py`: `lila-worker --lila-data-v3`.
- `src/tilt/evaluation/v3_live_parity.py` (new): the parity gate.
- Tests:
  - `tests/unit/test_live_v3.py` (new, 17 tests);
  - `tests/unit/test_lila_worker.py`: 5 tests kept, 7 new v3 tests.

Frozen files are unchanged: `check_frozen()` passes. Hashes are in `~/tilt-labels-v3/I1/parity.json`.

## Parity gate (§11): PASSED
Output: `~/tilt-labels-v3/I1/parity.json`. Run time 8 min 10 s on WSL, peak RSS 1.5 GB.

**Players.** 26 development players: 13 old and 13 new. In each cohort, 12 were chosen by
`sha256("live-v3-parity-1:…")` and 1 extra was taken from the players with S3 incomplete drops.

**Batch path**, live headers → `build_player` → `scores`, compared with S3/S4. Every row matches exactly:
max |diff| 0, nulls equal.

| Table | Rows |
|---|---|
| Header rows (vs `split_v3.load_headers`) | 4,631 |
| Targets | 4,159 |
| `labels_dev` | 4,159 |
| `features_pre` | 4,150 |
| `features_p20` | 3,942 |
| S4 `M-v3::{pre,p20,composite}::frozen` | 4,150 |
| Incomplete drops (vs `excluded_incomplete_moves.csv`) | 9 |

**Per-game worker path** (`live_v3.evaluate`), on 78 sampled targets:
- the first game under 20 plies, the first P-20 game and the last target of each player, plus 1 dropped target;
- 75 scored, with a composite equal to the batch value and the correct head and level;
- 3 returned `skip: "incomplete"`;
- the rule label and context matched `labels_dev` in 75 of 75;
- 5 had E7 pending (no later game in the stored data);
- 73 signs were shown. For every scored call, the SHAP sum equalled the model margin.

## Fast reason on real rows
Output: `~/tilt-labels-v3/I1/fast_check.json`. Of the 3,942 P-20 rows of the same players, 113 have
`p20_z_think_frac_median ≤ −1.5`.

| Outcome | Rows |
|---|---|
| Recomputed z ≠ model input | 0 |
| Shown | 71 |
| Hidden: z_trim > −1 | 29 |
| Hidden: < 20 reference games | 13 |

## Latency
A full `evaluate` on a player's latest game, with headers, features, labels, SHAP and the fast reason, takes a
median of 3.7 s and at most 6.1 s on WSL.

## One-colour defect in the running P3-B root
`tilt/data/external/lila` has 5 games of 20 or more plies. All 5 are complete, so 0 have one colour only. The
defect does not affect any current P3-B score. That root holds only local test accounts.

## Unit tests and suite
- `test_live_v3.py` and `test_lila_worker.py`: 29 passed.
- The full suite ran in WSL, the same way as in S5: `pytest -q` over `tests/`, with `TILT_SALT` set to the test
  value and the same E7.2 deselection.
  - Result: 622 passed, 2 skipped, 1 deselected, in 3 min 24 s. S5 had 598 passed, so the difference is exactly
    the 24 new tests.
  - The only warning is the starlette `BlockingPortal` deprecation, which S5 also had.
- At suite time, `live_v3.py` has sha256 `b608b1ab…` (the same as at parity) and `lila_worker.py` has
  `e2a1b5af…`.

## Implementation choices within the spec
- E7 refresh: §3.5 asks for the previous scored game. The worker recomputes up to 5 of the player's docs whose
  rule check still has E7 pending, and skips the docs answered in the same pass.
- Speed: lila now sends `speed` with each queue doc. A doc without speed (written before I2) falls back to the
  speed stored in the P3-B root while the shadow runs. Otherwise it waits the export grace period and is
  answered `game not available`.
- `rules.reason` is `null` when the rule check has no abstain reason. lila reads it as absent.

## Fixes found in I3 (2026-11-17)
I3 found 2 defects in the worker's use of the site export. Neither changes a score. Both are fixed below.

### 1. Blitz filter on the client
- **Problem.** The first I3 run scored no blitz game. The v3 root was collected with `perfType=blitz`, but lila
  answers perf-filtered exports from lila-search (`GameApiV2`: `requiresElasticSearch` when a perf is set). The
  local site has no lila-search, so the export returned no games or an HTTP error. The worker then answered
  `export failed: HTTPError` or a pyarrow `FieldRef` error on an empty root. The parity gate never used the
  export, so it could not catch this.
- **Change.** `collect.collect_api` has a new `keep_perf` argument, which cannot be combined with `perf`.
  - It asks for every perf through the Mongo export path.
  - It keeps only lines whose `perf` equals `keep_perf`, both when normalising and in the raw `.ndjson.gz`, so
    `normalize_api` recovery also keeps the root blitz-only.
  - It uses its own resume cursor and resumes at `since = newest createdAt + 1`, the Mongo-path rule.
  - `max_games` then counts games of every perf.
  - The default call (no `keep_perf`) is byte-identical to before. The frozen `cohort_v3` uses only
    `normalize_api`, which did not change.
- The v3 worker calls `collect_api(..., keep_perf='blitz')`. The shadow P3-B call is unchanged.
- **Tests.** There is 1 new test in `tests/integration/test_collection.py`, and the worker test asserts the new
  argument.

### 2. Retry after lila's warm-up
- **Problem.** In the second I3 run, the docs of the first game were answered `export failed: HTTPError` and never
  retried. For 20 s after boot, lila's `HttpFilter.WarmupFilter` answers `Game.apiExportByUser` with 503 "Please
  retry in a few seconds". It does not log these requests. Every lila restart would have left the games that finish
  in that window with a permanent error.
- **Change.** In v3 mode, an export that fails with HTTP 5xx keeps the user's docs queued, like an unreachable
  site, so they are retried on the next pass. Other HTTP errors are answered `export failed: HTTP <status>`. The
  P3-B path without the pointer is unchanged.
- **Tests.** There is 1 new parametrised worker test with 3 cases: 503 and 500 stay queued, and 404 is answered.

### Suite after both fixes
- Worker tests: 15 passed.
- Full suite, run the same way: 626 passed, 2 skipped, 1 deselected, in 4 min 28 s. That is 622 plus the 4 new
  test cases.
- `collect.py` sha256 `55413ed4…`, `lila_worker.py` `4f9e0a6e…`. `live_v3.py` is unchanged (`b608b1ab…`).
