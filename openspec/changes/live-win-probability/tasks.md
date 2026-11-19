# Implementation and evidence

## Analysis vertical advantage gauge — 2026-11-18 (current)

- [x] Share the live W+D/2 display helper with standard-game analysis. Prefer
  native White-oriented engine WDL; explicitly identify Stockfish 15.1 model
  conversion for legacy cp-only evaluations. Preserve other variants/gauges.
- [x] Display percentages for the selected node, clear missing evaluations,
  preserve colors when flipped and handle mainline official results separately
  from earlier nodes or analysis variations. No future clocks/human features.
- [x] Verify regression failures before implementation, unit/full frontend,
  formatting/lint/style/build, real browser engine/replay/mobile/endings and
  live-panel compatibility. Refresh reproducible patch and branch README.
  Red 9/12; focused 38/38; full 360/360, no skips; 45 independent python-chess
  reference vectors. Production UI/type-aware lint/stylelint/format pass.
  Browser: four reviewed games, 22 snapshots including 18 actual native WDL
  comparisons; flip/reload/missing eval/same-ply variations/official results and
  unchanged PGN pass. Live AI both colors/nine samples and variant gate pass.
  Browser model installed/checked by pinned SHA/size. Patch: 27 WDL paths, 54
  combined with unchanged voice; replay/reverse/whitespace pass, index preserved.
  Evidence: `reports/acceptance/replay-advantage/`. No fresh Scala/ASR claim.
- [x] Commit and push on codex/vietnamese-voice-input, verify remote HEAD.
  Feature commit 58cc360 was matched by git ls-remote. Branch README now pins
  that code revision and records the implemented review behavior; final docs
  follow-up also fixes a hidden vertical-tab in the older voice command example.

## Compact advantage panel — 2026-11-18 (current presentation)

- [x] Remove the live source and half-point explanation lines at the user's
  request. Keep source/meaning in a title tooltip and existing accessibility
  metadata; preserve official result captions, the formula and lifecycle rules.
- [x] Existing view regressions: four of 19 fail against old presentation,
  19/19 pass after change. Full upstream frontend 341/341, no skips; production
  UI, type-aware lint, stylelint and format pass. Fresh bundle round.CMETBTNQ.js.
- [x] Browser: registered PvP 164 assertions/44 participant samples, zero JS
  exceptions; bot both colors, nine samples, official results and Chess960 gate.
  Desktop/mobile visibly show only the bar/two percentages, tooltip retained.
  No Scala/backend/model/ASR changes or fresh audio claim. Patch replay matches
  all 40 feature paths; real index and voice patch unchanged. Evidence:
  `reports/acceptance/compact-advantage/`.

## Expected-score advantage display — 2026-11-18 (current)

The user replaces conditional win percentages with a two-color advantage bar,
still totaling 100%. A draw contributes half a point to each color: W + D/2
and B + D/2. Label this expected-score advantage, not a personal win probability.

- [x] Reproduce the conditional-normalization defect: 10 of 19 focused tests
  fail before the fix. In particular, raw 0/87.6/12.4 becomes 0/100 instead of
  the requested 43.8/56.2 expected points. `artifacts/expected-score-red.log`.
- [x] Replace the display projection, rename the helper, identify the metric
  and source and explain the 50% midpoint/draw treatment. Keep raw WDL and
  server/model/access rules unchanged; official draws/results retain priority.
- [x] Verify focused and full UI checks, production build and browser flows
  for both human players, engine/human sources, AI, voice and official results.
  Focused 19/19; full 341/341, 34 suites, no skips. Lint/stylelint/format and
  production build pass. Browser assertions: anonymous 188, registered 164;
  88 participant samples, no JS exceptions. AI: both colors, nine samples,
  Chess960 gate; same real audio: b2b4, bot d7d5, no confirmation or wrong move.
- [x] Reproduce the reported and reference positions, inspect desktop/mobile,
  refresh the patch and update documentation. Independent python-chess expected
  points agree. All 40 feature paths replay, reverse/whitespace checks pass,
  real index and voice patch preserved; no backend/model source changes.
  Fresh local bundle `round.ZESERAB3.js` is loaded by all checked browser flows.
  `reports/acceptance/expected-score-advantage/` contains logs, JSON and images.
- [x] Check local demo without moving on the user's game: the real-audio test
  game shows 49.3/50.7 on desktop/mobile. Old game ROwDDu2g has ended in White
  checkmate; API returns its official result and a fresh navigation opens
  analysis, so it is not an active demo. Two image-helper waits with that wrong
  live-round assumption timed out; the final visual check uses the live test
  game and verifies the old result separately. In-app handoff remained queued;
  no callback, helper stopped/assets removed. Direct testing: localhost:8080,
  Ctrl+F5, start a new standard bot/human game. Scala/Python suites not rerun
  for this UI-only projection; earlier backend evidence remains historical.

## Live panel for all players — 2026-11-18 (access retained, earlier display)

The user's follow-up explicitly includes both human players. This supersedes
the earlier spectator-only and intermediate AI-player-only access requirements.

- [x] Preserve the verified intermediate AI scope under
  `reports/acceptance/ai-player-probability/`: 603 uncached Scala tests, 338 UI
  tests, four AI games, 18 player probability samples and one real-audio/bot
  flow with the live panel. Do not rewrite its old PvP-denial expectations.
- [x] Add a new browser regression for both active human participants. The
  deployed AI-only build fails with HTTP 403; `artifacts/player-probability-red.log`.
- [x] Advertise and initialize the panel for every enabled standard game,
  including AI and human participants. Remove the player denial at the server;
  retain feature enablement, variant, theft and block checks, internal worker,
  authoritative histories and conditional White/Black display.
- [x] Final checks: 603 uncached Scala tests, 338 UI tests, scalafmt, lint,
  formatting, stage and production UI build pass. The repeated Scala build
  reuses 150 freshly generated I18n resources with input/output hash checks;
  repository build configuration unchanged. `testFull` remains mandatory.
- [x] Final browser: anonymous 188 assertions and registered 164, no JS errors;
  88 actual participant-response/display samples across both colors. Human
  player reload, takeback/same-ply replacement and official win/draw pass.
  AI: both colors, nine samples, reconnect/mobile/official result; Chess960
  remains HTTP 404, including with forged client flags.
- [x] Same recorded whole utterance, direct ASR to `b2b4`, legal bot reply and
  matching probability panel before/after: 1/1, no confirmation/wrong move.
  First attempt was stopped at signup by a rejected random fixture username;
  keep its failed setup report, zero ASR cases, and the successful retry.
- [x] Patch replay/reverse/whitespace checks match all 40 feature paths, real
  upstream index preserved and voice patch unchanged. Final evidence:
  `reports/acceptance/player-win-probability/`. Actual signed-in in-app board
  `ROwDDu2g` verified with vi/Shift/direct and the panel; no agent moves, helper
  stopped/assets removed, canonical board opened with a refresh query.

## Live panel for the AI player — 2026-11-18 (intermediate)

The user now authorizes the same probability panel directly on their game
against the built-in Lichess AI. Human opponents retain the existing restriction.

- [x] Reproduce the old behavior with a real anonymous AI-player session:
  `node scripts/ai-smoke.mjs --probability` fails on HTTP 403 instead of 200.
  Evidence: `artifacts/ai-player-probability-red.log`, raw run
  `artifacts/ai-smoke/2026-11-18T13-08-26.142Z/`.
- [x] Restrict the server exception to authoritative `game.hasAi`; advertise
  the capability only for standard games against an actual AI opponent. Keep
  feature enablement, standard variant, theft checks and block checks intact.
- [x] Initialize the existing live UI for an AI opponent or spectator when the
  server capability is present. Keep raw WDL and conditional White/Black math.
- [x] Intermediate checks completed: 603 Scala, 338 UI, four AI games and old
  PvP-denial acceptance; retained separately and superseded by the scope above.
- [x] Intermediate real-audio/live-panel flow and actual user board verified;
  patch refreshed at that stage, then updated again for the final scope above.

- [x] Pin upstream repositories and establish a reproducible local stack.
- [x] Run Lichess and verify the core game flow between browser sessions.
- [x] Build the bounded Stockfish WDL prediction service and meaningful regression tests.
- [x] Integrate authoritative game state and server-side spectator access.
- [x] Add the probability panel using existing Lichess UI conventions.
- [x] Verify stale responses, takebacks, reconnect, official results, and worker failures.
- [x] Run relevant Scala/TypeScript/Python checks and browser acceptance.
- [x] Save patches, exact versions, startup/check scripts, and handoff instructions.

## Verified delivery — 2026-11-05
Python: 19 tests passed; real Stockfish 15.1 HTTP smoke passed for 21 positions.
Worker HTTP p95 was 268.6 ms with 50 ms polling; first position was 528.7 ms.
100 requests for a cached position caused zero extra evaluations. These are worker-only measurements.
Evidence: `artifacts/check-final.log`, `artifacts/prediction-smoke.json`.
Pytest reports one upstream Starlette deprecation warning about its httpx TestClient;
all tests pass. This warning does not affect the running worker.

Scala: 603 tests passed, zero failures/errors; scalafmtCheckAll and stage passed (exit 0).
Evidence: `artifacts/scala-checks-final.log`.
The full UI build passed. Frontend: 260 tests passed across 34 suites,
including 8 WDL regression cases; changed UI files passed oxlint and oxfmt.
Browser acceptance passed with two anonymous players and a spectator: 20 initial plies,
takeback and same-ply replacement, orientation/replay/reload, mobile layout, worker outage
and recovery, player endpoint denial, and the official resignation result. Browser p95 was
504 ms for the first 20 moves on the final precompiled runtime, measured from the move
interaction until WDL appeared. The earlier development-mode run measured 490 ms.
These local pilot measurements do not establish capacity across many simultaneous games.
Evidence: `artifacts/ui-build.log`, `artifacts/ui-suite.log`, `artifacts/browser-smoke-final.log`,
`artifacts/browser-smoke.json`
and the `artifacts/wdl-*.png` screenshots.

The feature patch applies to pinned upstream HEAD and reverses from the working checkout
(`artifacts/patch-check.log`). Pinned Docker images built successfully.
The documented `start`, `check`, and `browser -WithOutage` commands passed. The application
is running at http://localhost:8080 using staged JARs, without a persistent sbt process.
Its observed memory use after startup was approximately 627 MiB; JVM maximum heap is 1 GiB.
Evidence: `artifacts/docker-build-final.log`, `artifacts/start-verified.log`.
Bootstrap components were exercised on this workspace; a second clean-machine bootstrap
was not repeated. Windows CRLF sources are normalized by the preparation script, and the
readiness probe uses IPv4 to match Docker's local bind.

The integration was added during the first dependency/build run; an unmodified browser baseline
was not separately run. Core gameplay was verified alongside the feature.

Project-local Superpowers skills installed: systematic-debugging, test-driven-development,
verification-before-completion. See `workflow-lock.json`; existing work is not retroactively
claimed to have followed their full process.
