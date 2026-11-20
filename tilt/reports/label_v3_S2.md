# Label v3 S2 — implementation and Erratum 2

Status: Erratum 2 code and offline validation complete. The operator has completed S2 collection, engine analysis and features; the initial assignment stopped before publishing a manifest. **This Erratum 2 task ran no real-data assignment, S2 gate, network step, engine, labelling or training.** Results remain blank for the operator.

The binding instructions include §8, Erratum 1, Addendum S2 and Erratum 2. S1 selected v3 with known limitations; this stage does not revisit that selection or compute new labels.

## Deliverables

Only these repository files were added for this task:

- `src/tilt/data/cohort_v3.py`: standalone `sample`, `screen`, `collect`, `cache-subset`, `assign`, `gate` CLI.
- `tests/unit/test_cohort_v3.py`: synthetic, mocked HTTP tests.
- `reports/label_v3_S2.md`: this handoff.

Outside the repository, `~/tilt-labels-v3/S2/` contains `colab_s2.py`, its reproducible offline checks `test_colab_s2.py`, `baseline.json`, and `codex-last.md`. The baseline is a control-file snapshot, not collected data. The operator creates the remaining artifacts.

`sample` produces candidates and a hashed input manifest; `screen` produces eligibility and reasons. Collection keeps per-account download roots under `data/v3new/external/downloads/`, maintains a completion ledger outside the repository, and publishes only accepted players' games into the new normalized root. `cohort.csv` records intrinsic rating band, original slot band/rank, count, first/last game start and replacement history. `membership.csv` fixes the selected player-game sides, including the 150-game cap. The existing normalizer runs after publication. Repeating collection makes no HTTP request for a completed account; interrupted requests retry the same bounded latest-game window.

`cache-subset` reads the original SQLite cache with `mode=ro`, copies matching full FEN/settings keys without reserializing payloads, and makes a 500-row agreement extract. `assign` writes the immutable pseudonymous Parquet and hash, including explicit drop records for old and new development sides sharing holdout games. `gate` outputs only QC and the seven S2 gate decisions. No code imports or invokes the v3 labeller.

## Mechanical choices

- Sampling reuses `collect.staged_dump(headers_only=True)`. Its limit counts distinct valid blitz candidate games, as in `sample_players`, rather than every PGN header encountered. Bands are [400,600), …, [2800,3000); rating is the average observed in the header window. Ordering is exactly the existing sampler's `sha256("43:" + lower_username + ":blitz")`, then username. Exclusions occur before keeping the first 30. The sampler keeps only 30 entries per band in memory.
- The manifest hashes the exclusion file, code, locked document, existing features manifest, output candidates, source URL and the ordered eligible aggregated header records. The URL hash identifies the source; it is **not** a claim to have hashed the entire remote dump. The temporary spool is deleted by the existing context manager.
- The single enlarged re-sample replaces only named short bands' candidate lists, with limit 2,400,000. It preserves the other bands' candidates and completed cohort slots, excludes their accounts from the new selection, and reuses completed downloads. Intrinsic band and slot band are separate because a replacement can come from another band. If the enlarged attempt remains below 170, collection reports `stop_for_operator_decision`.
- Screening uses public POST batches of at most 300, the same global `data/external/http.lock` as `collect.serial_response`, the generic existing User-Agent and the same serial 60-second 429 retry policy. A POST wrapper is necessary because the existing helper only implements GET. Missing responses, disabled/closed accounts, violations and BOTs are recorded as exclusions. A later games-endpoint 404/410 is also replaceable.
- Verified original cursor parameters without printing account identifiers: blitz, clocks/evals/accuracy/opening/division/moves enabled, finished only, ongoing false; original request sizes included 150 and 300. S2 fixes max at 150, no since, exclusive until **1794787200000** (2026-11-16T00:00:00Z). Replacement candidates sort by distance from the original slot's band, then lower band, then reserve rank. Already used accounts cannot fill another slot.
- Accepted raw files and per-player staging stay in the new root. `membership.csv` distinguishes selected cohort sides from incidental opponent sides produced by the existing features pipeline. Analysis and features reuse that pipeline; assignment and QC select exactly the membership. Game totals for the size gate are player-game sides under §1.2; QC also reports unique physical games. Eval coverage deduplicates physical game/ply; clock coverage counts the selected players' own moves.
- Cache schema is `positions(fen TEXT, settings_key TEXT, payload TEXT, PRIMARY KEY(fen,settings_key))`. Agreement candidates require engine provenance, matching binary, nonzero actual nodes and a cp or mate value; terminal values generated without engine search do not qualify. Order is SHA-256 of full FEN, a NUL separator and settings key. Colab takes up to 500 from the subset first, supplementing with distinct hashed old-cache extract rows. It compares both first and second PV cp/mate values, records differences, and stops on any mismatch. Agreement calls `_batch`/`_position` directly, bypassing cache lookup; `_batch` quits its engine.
- Colab independently reconstructs and verifies the full binary hash and settings key before every phase. Analyze uses the existing function with nodes 5000, MultiPV 2, hash 32 MB, threads 1, fresh game per position and all CPUs as processes by default. It prints a 30-second heartbeat; committed batches survive interruption. Features uses (window 12, min prior 5, session gap 30 minutes, history 200). Features restarts the phase if interrupted. Normalized-input fingerprints bind phases to the same upload; the result also binds the returned features manifest.
- A′ uses the public assignment hash independently of pseudonymisation. Half-up rounding is integer `(3*n+5)//10`. B′ uses the nearest-rank 80th-percentile game, one-based `ceil(.8*n)`, ordered by start time then game ID; its existing session's earliest start is inclusive. No session IDs are recomputed. The shared-game rule writes `drop_shared_development` rows for later S3 exclusion; it never edits the old root.
- Pseudonyms use the pipeline's existing environment-only HMAC functions if a valid `TILT_SALT` is already present. Otherwise they use HMAC-SHA256 keyed by the public assignment string. Game/session IDs use the pipeline's `game:` / `session:` domain prefixes. No salt file is opened; no salt or token is printed. Keep the same environment for assignment and later joins. `assignment_metadata.json` records the scheme without the secret. An OS flock serializes assignment; an existing Parquet, hash or excluded-sides CSV refuses regeneration.
- The old root's normalized shards are selected via its committed-batch manifest using a read-only SQLite connection, avoiding `storage.read`'s schema/commit side effects. The old features-manifest hash is captured once, checked after S2, and never reset by reruns. Network errors are summarized without account URLs or headers.

## Deviations

**Erratum 2:** features omit games with normalized `plies ≤ 1` in both cohorts. The stopped assignment exposed collected sides outside that modelling universe. `cohort_sides` now excludes an absent feature side only after confirming its normalized game has at most one ply; missing normalized games, unknown ply counts and longer missing sides remain errors. Assignment writes pseudonymous `player_id`, `game_id`, `status` and `plies` to `excluded_sides.csv`, and records its SHA-256, exclusion counts by status, collected sides and kept sides in `assignment_metadata.json`. The new-cohort manifest contains only kept sides; existing shared-development drop handling is preserved.

Every cohort player must retain at least 60 sides before assignment creates any file, including its flock file. Players are not replaced. B′ uses nearest-rank `ceil(0.8*n)` over kept sides with the existing inclusive session cutoff; A′ selection remains per player. The size gate uses kept per-player counts and total, reports collected and kept sides beside `players_at_least_60`, and retains the other checks. QC coverage and date spans use kept sides; band and date tables report kept counts beside raw collection counts. The one-shot guard also rejects an existing excluded-sides CSV, including an interrupted publication with no manifest. An existing empty `assignment.lock` is accepted and the operator's file was left untouched.

These changes implement the newly locked Erratum 2; no LF, threshold, gate threshold or hash-selection rule changed. The code's lock constant now matches that document. The original S2a subset-cache alternative, POST adapter, membership table, percentile convention, pseudonym fallback and artifact layout remain the mechanical choices listed above.

No real-data label statistic or S2 gate value was computed. Assignment and gate tests used temporary synthetic roots only. Existing model tests use their temporary fixtures. The real-engine integration test was deselected to obey this task's explicit “No Stockfish” rule. Pre-existing workspace changes were left alone. No commit or push was made.

## Operator runbook

All durations below are **planning estimates**, not measured S2 runtimes. Network rate limiting, CPU count, cache hit rate, RAM and upload speed can change them substantially. Keep private archives and outputs on WSL/Colab. Do not copy raw data into the repository or Windows storage. Commands below are for this machine; run network commands only as the operator.

### 1. WSL: verify, sample, screen and collect

```bash
cd /home/trantrien/lichess-workspace/tilt
(cd reports && sha256sum -c /home/trantrien/tilt-labels-v3/prereg.sha256)
.venv/bin/python -m tilt.data.cohort_v3 sample
.venv/bin/python -m tilt.data.cohort_v3 screen
.venv/bin/python -m tilt.data.cohort_v3 collect
```

Expected: lock OK; `~/tilt-labels-v3/S2/candidates.csv` (up to 390 rows), `sample_manifest.json`, `screened.csv`, `screen_manifest.json`, `collection_state.json`, `cohort.csv`, `membership.csv`, `collection_manifest.json`; accepted raw/normalized data under `tilt/data/v3new/`. Console output contains counts, not usernames. Sampling may take 10–90 minutes, screening 1–5 minutes plus 429 cooldowns, and API collection 20 minutes–3 hours. Re-run **collect** after interruption; completed players are not requested again. Initial sampling refuses accidental overwrites.

Inspect only counts and band counts:

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
import pandas as pd
c = pd.read_csv(Path.home() / 'tilt-labels-v3/S2/cohort.csv')
print('players:', len(c), 'player-games:', int(c.games.sum()))
print(c.groupby('band').size().rename('players'))
PY
```

If there are fewer than 170 players, run this enlarged re-sample **once** before any Colab work or assignment:

```bash
mapfile -t s2_short_bands < <(.venv/bin/python - <<'PY'
from pathlib import Path
import pandas as pd
c = pd.read_csv(Path.home() / 'tilt-labels-v3/S2/cohort.csv')
assert len(c) < 170
for band in range(400, 3000, 200):
    if int((c.band == band).sum()) < 16:
        print(band)
PY
)
.venv/bin/python -m tilt.data.cohort_v3 sample --bands "${s2_short_bands[@]}"
.venv/bin/python -m tilt.data.cohort_v3 screen
.venv/bin/python -m tilt.data.cohort_v3 collect
```

Expected: `candidates_initial.csv`, `sample_resample.json` and updated collection tables. Allow roughly twice the first sampling duration, plus requests for newly attempted accounts. If still below 170, stop for the user's decision. At 170–199, proceed with 30% A′ per band as registered. The following guard stops packaging below 170:

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
import pandas as pd
c = pd.read_csv(Path.home() / 'tilt-labels-v3/S2/cohort.csv')
assert len(c) >= 170, 'STOP: below 170; follow S2.5.9'
PY
```

### 2. WSL: subset cache and prepare the three uploads

```bash
.venv/bin/python -m tilt.data.cohort_v3 cache-subset
S2_DIR=/home/trantrien/tilt-labels-v3/S2
tar -czf "$S2_DIR/tilt-code.tar.gz" -C "$PWD" src pyproject.toml \
    -C "$S2_DIR" colab_s2.py agreement_sample.sqlite
tar --exclude='v3new/external' -czf "$S2_DIR/v3new.tar.gz" -C data v3new
sha256sum "$S2_DIR/tilt-code.tar.gz" "$S2_DIR/v3new.tar.gz" /usr/games/stockfish
```

Expected: `cache_subset.json` with hits/remaining positions; new `processed/engine/cache.sqlite`, `selected.json`; and exactly 500 engine rows in `agreement_sample.sqlite`. Cache work may take 2–30 minutes; packing/uploading may take 5–60 minutes or more. The original 1.8 GB cache is not uploaded. The new cache size depends on overlap. `external/` download attempts and materialization scratch are excluded from the data archive.

Upload exactly three files directly from WSL to Colab `/content`: `tilt-code.tar.gz`, `v3new.tar.gz`, and `/usr/games/stockfish` as `stockfish`. The helper script and agreement extract are inside the code archive. Compare the printed archive hashes after upload if desired; the script always verifies the binary independently.

### 3. Colab: unpack and install runtime dependencies

Use notebook cells; `%run` executes the script in the kernel. No subprocess CLI wrapper is needed. Use Python 3.12 or later, matching the package requirement.

```python
import sys
assert sys.version_info >= (3, 12)
```

```python
!mkdir -p /content/tilt-code
!tar -xzf /content/tilt-code.tar.gz -C /content/tilt-code
!tar -xzf /content/v3new.tar.gz -C /content
!cp /content/tilt-code/agreement_sample.sqlite /content/agreement_sample.sqlite
!chmod u+x /content/stockfish
%pip install pandas==2.2.3 pyarrow==19.0.1 numpy==2.2.6 python-chess==1.999 chess==1.11.2 requests==2.32.3 zstandard==0.23.0
```

These are operator-run dependency installs on Colab; Codex did not execute them. Only the data/engine/feature dependencies are needed. Restart the kernel if package installation requests it, then continue with the files still in `/content`.

### 4. Colab: check, analyze, features, pack

```python
%run /content/tilt-code/colab_s2.py --phase check
```

Expected: binary hash `00628bd9c9855c1b7ff93d7f8d51b413586cdc6336fe637f9a14a61531a05aca` and settings key `ca2f1c3ac567a14c1b85bd95c43f5aa1bd29f565a42e9cd932db274ca91239ae` match; progress every 50 positions; `/content/colab_result.json` reports 500 tested, 500 identical, zero mismatches. Allow 1–15 minutes. Binary/settings mismatch aborts before engine analysis. An incompatible executable also stops; do not replace it with another binary. Any eval mismatch requires stopping under §8 and retaining the JSON differences.

```python
%run /content/tilt-code/colab_s2.py --phase analyze
%run /content/tilt-code/colab_s2.py --phase features
%run /content/tilt-code/colab_s2.py --phase pack
```

Expected: analysis heartbeats and completion counts, new selected-cache manifest, five feature Parquets and their manifest, then `/content/s2_processed.tar.gz` and a final **`S2_COMPLETE`** line with its SHA-256. Analysis may take 2–24+ hours; features 20 minutes–3 hours; packing 5–30 minutes. All CPU cores are used as analysis processes, one engine thread each. Use `--phase all` instead of the four cells only for a fresh uninterrupted run.

If analyze is interrupted, preserve `/content/v3new`, `colab_result.json`, the code and binary, then re-run analyze; committed cache batches are reused. If the whole VM disappears, first preserve/download the partial new root and result, re-upload them and re-run check, then analyze. A fresh check resets phase completion metadata and uses 500 hashed rows from the current cache. Features can be rerun in full after an interruption. Pack requires completed features and a matching manifest.

Download the processed archive directly into WSL as `~/tilt-labels-v3/S2/s2_processed.tar.gz`. Keep its printed hash for transfer verification. This archive contains private processed data, not raw NDJSON.

### 5. WSL: restore processed outputs, assign once, gate

```bash
cd /home/trantrien/lichess-workspace/tilt
S2_DIR=/home/trantrien/tilt-labels-v3/S2
mkdir -p "$S2_DIR/returned"
tar -xzf "$S2_DIR/s2_processed.tar.gz" -C "$S2_DIR/returned"
cp -a "$S2_DIR/returned/v3new/processed/." data/v3new/processed/
cp "$S2_DIR/returned/colab_result.json" "$S2_DIR/colab_result.json"
.venv/bin/python -m tilt.data.cohort_v3 assign
(cd "$S2_DIR" && sha256sum -c holdout_manifest.sha256)
.venv/bin/python -m tilt.data.cohort_v3 gate
(cd reports && sha256sum -c /home/trantrien/tilt-labels-v3/prereg.sha256)
```

Expected: immutable `holdout_manifest.parquet`, `holdout_manifest.sha256`, `excluded_sides.csv`, `assignment_metadata.json`; then `s2_gate.json`, `qc_bands.csv`, `qc_dates.csv`. Assignment and QC should take 1–10 minutes each. Assignment refuses regeneration even if only its Parquet, hash or excluded-sides CSV survived an interruption. Do not delete/recreate it to choose a different partition. Shared-development drops in the manifest must be honored by S3, including old-cohort drop records. No old dataset is rewritten here.

All seven gate checks must pass. Copy only allowed QC aggregates into Results below; do not compute labels or show behaviour distributions by holdout membership. A failed gate is not permission to change a threshold or continue to training.

## Validation

All network tests use mocked HTTP; the unit fixture rejects any unmocked request. Coverage includes bounded/hash-ordered band sampling and case-insensitive exclusion; POST chunking, 429 handling and screening reasons; the compressed dump GET path; API parameters, interruptions and cursor/ledger resume; ordered replacements and accepted-root materialization; one-time short-band re-sampling; byte-identical subset payloads and read-only source; A′ rounding and public-key ordering; B′ session boundary; shared old/new development drops; refusal to regenerate; gate boundaries, failures and empty denominators. Erratum 2 tests additionally cover short-side exclusions and their pseudonymous audit under both pseudonym schemes; missing normalized, unknown-ply and longer games; early/late exclusions leaving the kept-side anchor unchanged; rejection below 60 kept sides, including zero, before any write; kept-count size boundaries and raw-count reporting; kept-side coverage/QC; and the active document lock.

- Repository unit module: **58 passed in 1.41 s** using `PYTHONPATH=/home/trantrien/tilt-labels-v2/test_runtime .venv/bin/python -m pytest -q tests/unit/test_cohort_v3.py` from `tilt/`.
- The seven outside-repository Colab checks passed during S2a; they were not rerun for Erratum 2. They mock process/engine execution and cover pre-analysis hash rejection, exact settings reconstruction, supplement uniqueness, agreement success/mismatch, phase guards, exact analysis/feature parameters and packing.
- Full suite from `tilt/`: `PYTHONPATH=/home/trantrien/tilt-labels-v2/test_runtime .venv/bin/python -m pytest -q` — **413 passed, 1 deselected, 1 existing warning in 49.24 s**. The supplied asyncio wake-up shim was used. `PYTEST_ADDOPTS='--deselect=tests/integration/test_engine.py::test_real_fixed_budget_multipv_cache_and_settings_invalidation'` excluded the sole real Stockfish test to honor the explicit engine prohibition. Warning: existing Starlette/AnyIO BlockingPortal deprecation.
- CLI help and Colab syntax compilation passed during S2a. Real Colab ABI compatibility, resources, network availability and end-to-end durations remain operator checks; they were not simulated as successful real runs.

## Hash checks

Active lock: `~/tilt-labels-v3/prereg.sha256`.

- Erratum 2 start: `sha256sum -c /home/trantrien/tilt-labels-v3/prereg.sha256` from `tilt/reports/`: **OK**, **`0d59ce9d79e6e9e9e9992e5116b83e39440eacfc1f3a53b83772030d8b2a0b06`**.
- Erratum 2 end: the same `sha256sum -c` from `tilt/reports/` returned **OK**, with the same full hash. The pre-registration was not edited; the lock's basename is relative to `tilt/reports/`.
- Original S2a features-manifest baseline: **`1ea2383b730329b9f3301263a42aaa788b9ff0ae961df03d921cd1bbc16ec000`**. `baseline.json` preserves it for the operator's post-S2 comparison. This Erratum 2 task did not modify either data root.

## Results — operator to fill after S2b

Filled by the operator on 2026-11-17.

**Collection**
- Sample, screen and collect ran on WSL on 2026-11-16. The engine/features run went from 2026-11-16 to 2026-11-17
  (see deviations).
- Sampling:
  - one attempt at limit 1.2 M; the S2.5.9 enlarged re-sample was not needed;
  - the 196 old accounts were excluded;
  - screening dropped 47 candidates: BOT 35, tosViolation 7, disabled 5.
- Replacements:
  - 36 players have a replacement history;
  - 13 of them fill a slot from another band. The 2800 band yielded only 3 players; its shortfall went to the
    nearest bands, lower first.
- Final players per band:

  | Band | 400–2200 (each) | 2400 | 2600 | 2800 |
  |---|---|---|---|---|
  | Players | 16 | 22 | 23 | 3 |

**Size and dates**
- 208 players, all with ≥ 60 kept games.
- Player-game sides: 30,695 collected, 30,613 kept after Erratum 2. Unique games among kept sides: 30,571.
- Dates run from 2025-05-29 to 2026-11-15. The per-player span has median 18 days, p10 5 days and p90 48 days
  (`qc_dates.csv`).

**Engine**
- Positions: 1,874,225. Of these, 41,330 were reused from the old cache by subset, and 1,832,895 were analysed in S2b.
- Engine settings key `ca2f1c3a…` matched, and the binary sha256 `00628bd9…` matched on every host.
- The 500-position agreement check gave 500/500 identical results, 0 mismatches, on each of 3 runs:
  - two Colab TPU VMs;
  - the vast.ai host, on hashed rows from the merged cache, which included rows computed on Colab.
- `analyze` final run: computed 624,063, cache hits 1,250,162, settings key `ca2f1c3a…`.

**Coverage**
- Clocks on own moves: 96.2% (1,019,305 / 1,059,580). Evals on plies: 100% (2,114,674 / 2,114,674).
- Per-band coverage is in `qc_bands.csv`. Clocks range from 94.0% to 97.6% across bands.

**Checks**
- No overlap with the old cohort.
- The existing features manifest `1ea2383b…` is unchanged.
- Pre-registration lock `0d59ce9d…` (Erratum 2) is OK.

**Holdout manifest**
- `holdout_manifest.parquet` sha256 `d21e5b02dbaf07c6fee3a7c608973c9f5608f8f62a9aa9cd97120c517a89ff3d`, 30,625 rows.
- `excluded_sides.csv` sha256 `0ce5efcd…` lists 82 sides: noStart 69, outoftime 7, resign 6.
- Rows by assignment (counts only):

  | Cohort | Assignment | Rows | Players |
  |---|---|---|---|
  | new | A′ | 9,665 | 65 |
  | new | B′ | 4,989 | 143 |
  | new | development | 15,943 | 142 |
  | new | drop_shared_development | 16 | 11 |
  | old | drop_shared_development | 12 | 8 |

  One non-A′ player has no development rows: their 80th-percentile session starts at their first game.

**Gate (`s2_gate.json`)**
- settings ✓, agreement ✓, clocks ✓, evals ✓, size ✓, no_overlap ✓, old_manifest_unchanged ✓.
- Verdict: **PASS**.

**Operator deviations (no §8 stop)**
1. Colab TPU v5e1 runtimes were reclaimed twice, after about 1 h and 2 h. Afterwards only a 2-core CPU runtime was
   available.
   - Work continued from cache increments: rows exported as gzipped JSONL every 20–40 minutes and stored in
     `~/tilt-labels-v3/S2/incs/`.
   - On each new host the increments were re-inserted into the subset cache and `check` was re-run before `analyze`.
2. With the user's approval, the rest of `analyze`, and then `features` and `pack`, ran on a rented vast.ai container
   (Ubuntu 24.04, glibc 2.39, 18 CPUs) with `--processes 18`.
   - The same uploaded binary and code archive were used, and the hashes were verified.
   - The pack sha256 `4d479204…` matched after transfer to WSL.
3. Uploads:
   - the data archive was split into 20 MB parts for the Colab upload, and the joined archive's sha256 was verified;
   - on vast.ai, a launcher bug (spawn re-executing the setup script) truncated the already-extracted upload tarball;
     the extracted data and cache were unaffected, and `check` passed afterwards.
4. Erratum 2: the first `assign` attempt stopped before writing a manifest (see Deviations). The empty
   `assignment.lock` flock file from that attempt remains.
