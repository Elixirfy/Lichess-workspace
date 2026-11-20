# Label v3 — I2 (lila) and I3 (end-to-end) results

Date: 2026-11-17. Spec: `reports/label_v3_deployment.md` (I0, approved 2026-11-17). Operator: Claude.
The worker side is in `reports/label_v3_I1.md`. Counts only; no player names or game ids.

## I2: lila
### Code (branch `private/ai-coach-tilt`, not committed)
- `modules/tilt/src/main/TiltGame.scala`:
  - the queue doc stores `speed`;
  - the response holds an optional `skip`;
  - `Pred` reads the M-v3 fields (`v`, `prob`, `level`, `head`, `signs`, `fast`, `rules`) next to the P3-B ones;
  - `Level` (low < 0.10 ≤ attention < 0.30 ≤ high), as in §4.
- `TiltBanner.scala` (new):
  - the session is built from the M-v3 scored games, with a 30-minute gap;
  - reasons are "2 high in a row" and "high + strong rule context";
  - the banner shows at most once per session, at least 30 minutes apart, never while a game is in progress, and
    never after the player opts out;
  - `TiltStats` counts the last 30 days and the last 50 scored games.
- `TiltText.scala` (new): all tilt texts in English and Vietnamese, chosen by the page language.
- `TiltApi.scala`:
  - `tilt_banner` state (shown, dismissed, opted out);
  - `banner` records a shown banner;
  - deleting a user also deletes their banner doc;
  - the queue doc carries the game speed.
- `ui/TiltUi.scala`:
  - the game tab shows the level, score, meter, the "pre-game context only" note, early signs (§5), the fast reason
    (§6) and the rule check (§7);
  - a skipped or failed game says why;
  - older P3-B answers keep the previous panel, marked "older model";
  - the account page has the statistics, the opt-out switch and the recent games;
  - the home page banner.
- `app/controllers/Tilt.scala`: `POST /account/tilt/banner` (opt-out) and `POST /account/tilt/banner/dismiss`.
- Shared files:
  - `conf/routes` (2 routes) and `conf/base.conf` (`tilt.collection.banner`);
  - `app/mashup/Preload.scala`: the banner for a signed-in human, skipped during a game;
  - `app/views/lobby/home.scala` (banner at the top of the side column) and `app/views/analyse.scala`;
  - `ui/lib/css/component/_tilt.scss` (level colours, statistics, banner) and `ui/lobby/css/build/lobby.scss`.

### Checks
- `sbt compile` passes.
- `tilt/Test/testOnly lila.tilt.*` has 14 tests, all passing. They cover:
  - reading new, old and skipped docs, and `rules.reason: null`;
  - levels;
  - every banner rule;
  - statistics;
  - texts in both languages;
  - number formatting;
  - the legacy factor names.
- scalafmt passes.
- `./ui/build -n` passes.
- `stylelint` and `oxfmt --check` pass on the changed stylesheets.

- After I3, `.tilt-stats` gained `margin-bottom: 1.5em`, because the "Break suggestions" heading touched the
  statistics. `./ui/build -n`, stylelint and oxfmt pass.

## I3: end to end (PASSED, 2026-11-17)
### Setup
- The local site (lila, lila-ws, MongoDB, Redis) and the worker ran in one long-lived WSL session.
- The worker used an isolated models root: a copy of the real one, with M-v3 installed by `live_v3 install`.
  It also had its own empty data roots.
- 2 test accounts played 3 casual games through the Board API:
  - blitz 5+3, 14 plies, ending in mate;
  - blitz 5+3, 38 plies, ending in resignation;
  - rapid 10+5, 6 plies, ending in resignation.

### Worker answers
- All 6 queue docs were answered within 5 s of the last game.
- The 4 blitz docs were scored by M-v3:
  - the 14-ply game used the `pre` head, and the 38-ply game used the `p20` head, as §3 says;
  - all 4 are "low" (probability 0.0001 to 0.0964);
  - the rule check abstained on all 4;
  - the hidden P3-B shadow has a score on all 4.
- The 2 rapid docs were answered `skip: "speed"`, with no export or engine work.
- Every real score was low. To test the banner, a script set the 2 blitz docs of one account to "high" in Mongo.

### Browser checks: 40 of 40 passed
Playwright ran 19 checks in Vietnamese and the same 19 in English, plus 2 more.
- **Game tab:**
  - the long blitz game shows a level, its early signs and the rule check, and no "pre-game context only" note;
  - the short blitz game shows that note;
  - the panel says it does not measure emotions;
  - the rapid game says only blitz games are scored.
- **Account page:** statistics; 3 rows in the game list; the rapid row is "not scored".
- **Banner:**
  - it appears after 2 high blitz games and is recorded;
  - it is not shown again in the same session;
  - dismissing it returns to the home page and is recorded;
  - opting out is saved, and no banner shows while opted out;
  - opting back in is saved, and the banner returns.
- **Other:** an anonymous visitor sees no Tilt tab; the browser console has no errors.

After the stylesheet change, the 40 checks were run again and all passed.

### Defects found and fixed
1. **Blitz filter.** The worker asked the export for `perfType=blitz`, which lila answers from lila-search. The
   local site has no lila-search, so it got no games or an HTTP error. The fix is the `keep_perf` filter on the
   client; see `label_v3_I1.md`.
2. **Warm-up 503.** lila answers exports with 503 for 20 s after boot, without a log line. The first game's docs
   got a permanent error. In v3 mode, a 5xx now keeps the docs queued for the next pass.
3. **I3 setup only.** The isolated models root lacked `processed/out/weak_manifest.json`, so the shadow failed
   with `FileNotFoundError`. The shown answer was not affected. The real root has this file.
4. **Spacing** on the account page (see I2).

### Not covered on the live site
- The 503 retry happens only within 20 s of a lila restart. It is covered by the unit test only.
- The "high score + strong rule context" banner reason, the E7 refresh and mobile widths. The first two are covered
  by unit tests.

### Cleanup
- All 21 `coach*` test accounts were deleted: the 2 from I3 and 19 left over from tests on 2026-11-13/14. This
  removed 151 documents in 13 collections, including games, tokens, `tilt_queue` and `tilt_banner`.
  - The backup is `~/tilt-coach-backup-20261117-1744.json`, in WSL only.
  - Afterwards there are 0 test accounts, 0 `tilt_queue` docs and 0 `tilt_banner` docs.
- The I3 roots were removed. The old P3-B worker root `tilt/data/external/lila`, which held only test accounts,
  was archived to `~/tilt-external-lila-backup-20261117-1744.tar.gz` and removed.
- Evidence is in `~/tilt-labels-v3/I3/`: answers by role and game, the worker log and 6 screenshots. The
  screenshots show the deleted test accounts.

## Switch (2026-11-17)
- `tilt/data/processed/models/deployed_v3.json` was written by `live_v3 install`:
  - model M-v3, bundle sha256 `9ebc9730…`;
  - files `v3/M-v3.joblib` and `v3/feature_registry.csv`;
  - `deployed_on` 2026-11-17, `shadow_until` 2026-12-01.
- `live_v3.load` accepts the pointer, and the shadow is on.
- The next `start-lichess.sh` starts the worker in v3 mode, with the blitz root `tilt/data/external/lila-v3`.
- The P3-B pointer `deployed.json` stays; the shadow uses it. After 2026-12-01 the worker stops running the shadow.
- **Rollback:** delete `deployed_v3.json` and restart the worker.

## Plain-words revision (2026-11-17, user request)
The user found the game tab too wordy and too technical. Examples were the note that the listed signals are
model patterns and not evidence of emotion, and the word "model", which players do not know. The user chose a
short game tab that keeps the after-game check, and asked for the account page intro to match.

### What changed (departs from the I0 wording of §5–§7; scoring is unchanged)
- **Game tab:**
  - The heading is "This score mostly comes from" / "Điểm này chủ yếu đến từ", with no shares (%).
  - The note about model patterns and emotions is gone.
  - The fast reason has no z number. It reads "faster than your usual pace early in the game (compared with your
    last N blitz games)". The §6 filter still decides whether the reason shows.
  - The after-game check is one line, "After the game: signs of tilt | no sign of tilt | not enough to tell",
    plus the rules that fired. It has no context line and no pending E7 line.
  - The about line is gone; the link reads "See all your tilt scores".
  - The short-game note reads "This game was too short, so the score is based only on your earlier games."
  - Family names are plain words, for example `session` = "kết quả các ván trước trong phiên" and `time` = "cách
    dùng thời gian ở đầu ván".
- **Account page:**
  - The new intro says each finished blitz game gets a tilt score from 0 to 100, based on results and how the
    player plays. It says other speeds are not scored and that the score is only an estimate that does not
    measure emotions.
  - "Most common reasons" replaces the model-signals heading.
  - The rule share reads "signs of tilt in X of N games clear enough to tell". With N = 0 it reads "no game was
    clear enough to tell yet".
- **Stylesheet:** the base stylesheet sets `li { list-style: none }`, so the reason lists now set `list-style:
  disc` on `li`. The unused `&__about` rule is gone.
- **Not changed:**
  - scores, levels and thresholds;
  - which families are shown (top 3, share ≥ 10%, no skill or meta family);
  - the banner texts and rules.

### Checks
- `lila.tilt.*`: 14 tests pass. The text test is now "player texts use plain words": no shown text contains
  "model", "mô hình", "plies", "nửa nước", "v3", "z =", "rule" or "luật". `sbt compile`, scalafmt,
  `./ui/build -n`, stylelint and oxfmt pass.
- The I3 setup was run again with 2 new test accounts and the same 3 games.
  - The first run passed 48 of 48 checks, but its screenshots showed missing list bullets and "0 of 0 clear
    cases". Both were fixed, and 2 checks were added for them.
  - The second run passed 52 of 52: 25 per language plus the anonymous and console checks. The new checks cover:
    - plain words on the long and short game tabs and on the account page;
    - no percentages on the game tab;
    - a bulleted reason list;
    - the "does not measure emotions" line on the account page;
    - no "0 of 0".
- **Cleanup:** each run's 2 test accounts and their 22 documents were deleted. The backups are
  `~/tilt-coach-backup-20261117-1907.json` and `-1910.json`, in WSL only. Afterwards there are 0 test accounts,
  0 `tilt_queue` docs and 0 `tilt_banner` docs. Evidence from the second run is in
  `~/tilt-labels-v3/I3/text-revision/`: 12 screenshots, the answers and the worker log.
