# One-terminal local commentary stack

- [x] Add `./lichess-local` foreground launcher and `status` / `stop` commands.
- [x] Start MongoDB, Redis, WebSocket, fishnet proxy/worker, commentary and Lila;
      reuse existing ports without owning or stopping external processes.
- [x] Keep PID start-time checks, supervisor lock, logs, authenticated commentary
      readiness and HTTP homepage checks. Clean up owned processes after failure.
- [x] Build UI and stage Scala by default when launching Lila; allow explicit
      `--no-build`. Enable commentary through runtime config, preserving source config.
- [x] Document Docker-free WSL dependencies, paths, local URL and reproduction in `LOCAL.md`.
- [x] Regression tests: reused PID must never be killed, existing service must not
      be spawned/owned, failed startup must report service and log.
- [x] Real `--no-build` startup: commentary `/health` ready; Lila homepage HTTP 200;
      stop retains existing MongoDB/Redis/WS/proxy; duplicate supervisor rejected.
- [x] Default `./lichess-local` run: full UI build completed; Scala `stage`
      succeeded (63 s, cache 100%); commentary ready and Lila homepage HTTP 200.
      `./lichess-local stop` and supervisor both exited 0; external dependency
      ports remained open, owned Lila/commentary ports closed.
- [x] Final verification: 4 unittest cases passed; `bash -n lichess-local` passed;
      `status` and `--help` ran successfully. Duplicate supervisor was rejected.

Evidence (2026-11-17): runtime/build logs under
`~/.local/state/lichess-main/`; regression command:
`python3 -m unittest discover -s scripts/tests -p test_local.py`.

Limitations: Linux/WSL launcher for the dependencies already installed on this
machine, not an installer or public deployment. Existing MongoDB data from this
session is under `/tmp`; see `LOCAL.md` for durable data configuration. Browser
play/audio flow has not been exercised as part of this launcher change.

## Windows access follow-up (2026-11-17)

- [x] Reproduced WSL loopback issue: WSL `localhost:9663` HTTP 200,
      Windows PowerShell `localhost:9663` connection closed unexpectedly.
- [x] Launcher selects private WSL IPv4, binds HTTP there and sets matching
      domain/base URL/assets/WebSocket origin. `LICHESS_LOCAL_HOST` overrides it.
- [x] Six regression tests pass (includes WSL IPv4 and Linux localhost selection).
- [x] Restarted stack with updated launcher. Windows PowerShell confirmed
      `http://172.31.8.156:9663` HTTP 200 and TCP connection to WebSocket port 9664.
      Active URL is printed by launcher; WSL IP can change on restart.
- [x] Python syntax compilation and `git diff --check` passed.

Full browser gameplay/audio and WebSocket protocol flow remain untested here;
TCP reachability does not establish that those flows pass.

## Commentary delivery and phrasebook follow-up (2026-11-17)

- [x] Investigated existing fixed Piper pacing and model discovery: 396 main
      templates (390 distinct); male VIVOS model was absent locally.
- [x] Added 656 authored templates in `services/commentary/phrase_variants.py`.
      Phrasebook `vi-prebuilt-2` has 1,046 distinct main templates, excluding
      colour/bridging combinations; uses existing verified motif guards.
- [x] Added sentence pacing in `prosody.py` / `piper_worker.py`: subtle speed
      variation for exclamations/questions, 240–340 ms sentence breaks, intact
      clauses and Vietnamese tones. `BLV_PROSODY=0`, `BLV_SPEECH_RATE=1.0`
      restores uniform delivery; no new TTS dependency.
- [x] Added `BLV_PIPER_MALE_MODEL` to settings, local ignored `.env` and tracked
      `.env.example`. Installed VIVOS ONNX + JSON next to the default model;
      verified both SHA256 values against existing pinned `assets.json`.
      Existing UI voice ids Nam 1 / Nam 2 remain usable; no upstream edits.
- [x] Added regression tests first for sentence boundaries/pacing, at least 1,000
      distinct usable templates and explicit male-model discovery. Existing
      folder-discovery tests now explicitly isolate their settings from ambient
      model environment variables (initial full run exposed this fixture issue).
- [x] Full commentary suite: 48 tests passed, no skips, 53.492 s, including actual
      synthesis of all six voices. Command:
      `BLV_PIPER_DIR=/home/lehuy/lichess/lichess-research/.tools/commentary services/commentary/.venv/bin/python -m unittest discover -s services/commentary/tests`.
- [x] Launcher suite: `python3 -m unittest discover -s scripts/tests -p test_local.py`
      — 6 passed. `git diff --check` passed.
- [x] Generated real female/male WAV comparisons in `/tmp/commentary-preview/`.
      Paced 3-sentence sample: female 3.61 s audio, male-45 4.48 s audio;
      cold synthesis including model startup 2.83 / 2.67 s respectively.
      These are spot checks, not a latency benchmark or listening evaluation.

Remaining manual verification: existing stack was left running; restart with
`./lichess-local stop` then `./lichess-local --no-build` to load changes. Open
`http://172.31.8.156:9663` (or current URL printed by launcher), start a game,
turn on commentary and select Nam 1 / Nam 2. Listen for intelligibility and
pacing across ordinary moves, captures and checks. Browser audio flow and
subjective naturalness were not verified. VIVOS retains its documented tone
accuracy and non-commercial licence limitations; no claim of human-like TTS.

## Single-file phrasebook follow-up (2026-11-17)

- [x] Merged the supplementary MOVE/IDLE templates directly into their respective
      groups in `services/commentary/phrases.py`; removed `phrase_variants.py`
      and the runtime merge/import. Updated the commentary README.
- [x] Compared all exported phrase groups with a JSON snapshot taken before the
      merge: exact equality of content, group membership and ordering. The
      phrasebook remains 1,046 distinct main templates; selection is unchanged.
- [x] Full commentary suite passed: 48 tests, no skips, including actual synthesis
      of all six installed voices (see `/tmp/commentary-merge-tests.log`).
      Same `BLV_PIPER_DIR=... python -m unittest discover -s services/commentary/tests`
      command as above. `py_compile` and `git diff --check` passed.

TTS alternatives researched for the user; no TTS backend changed in this follow-up.
No restart is needed for this content-preserving file consolidation to change
behavior; a future process start loads the single-file layout. Browser listening
limitations from the previous handoff remain.


## Piper restoration with expanded phrasebook (2026-11-17)

- [x] Restored commentary runtime, controller routes and round UI from `main` commit `b8fc69b`.
- [x] Kept `services/commentary/phrases.py` unchanged; it contains 1,046 distinct templates.
- [x] Removed the alternate TTS source, dependencies, model environment, generated samples and audio streaming changes.
- [x] Runtime `.env` uses the Piper default timeout and contains no alternate TTS or streaming settings.

UI build completed successfully; Scala `stage` completed successfully (126 s, cache 100%). No tests were run for this rollback. Runtime `/health` reports ready with Stockfish 19, six Piper voices and `vi-prebuilt-2`; Lila homepage returned HTTP 200. The local stack is running on Piper at `http://172.31.8.156:9663`.

## Google AI Studio speech integration (2026-11-17)

Implementation and tests assisted by Codex. This changes speech synthesis only;
chess facts and authored Vietnamese commentary stay in the existing pipeline.

- [x] Added server-side Gemini REST TTS in `services/commentary/gemini_tts.py`.
      Default model: `gemini-3.1-flash-tts-preview`; default voice: Kore. API key
      goes in `x-goog-api-key`, never URLs, response payloads or logs. Only the
      spoken text and delivery instructions go to Google, without game metadata.
- [x] `BLV_TTS_PROVIDER=auto` selects Gemini when `GEMINI_API_KEY` is nonempty,
      otherwise Piper; explicit `piper`/`gemini` are supported. Gemini needs no
      Piper model. Six existing voice ids map to distinct Google voices, keeping
      saved UI preferences and Scala whitelists compatible.
- [x] PCM/WAV validation, response/audio size bounds, seven-second cloud deadline,
      serialized HTTP calls, cancellation and 64-entry in-memory audio cache.
      Cloud startup/health do not generate paid speech or warm the phrasebook.
      Provider errors retain subtitles and never silently switch to Piper.
- [x] UI permits cloud results up to ten seconds old, including subtitle-only
      failures. Existing request/revision/position/status/expiry checks remain.
      Tests verify delayed current speech, obsolete speech and delayed subtitles.
- [x] Added configuration to `.env.example` and the private ignored `.env`
      (blank key, mode 0600); updated launcher dependency validation, `LOCAL.md`
      and commentary README. No key supplied or external Google request made.
- [x] Added pinned HTTP test dependencies in `requirements-test.txt`; aiohttp
      is an explicit runtime dependency already present in `requirements.lock`.
- [x] Preserved Lila changes in `patches/lila-gemini-commentary.patch`. Incremental
      patch against workspace `b8fc69b4ac107ebc5538c0693ed5066f00089db5`'s existing
      commentary implementation; upstream revisions in `upstream-lock.json` are
      unchanged. Reverse-apply check with `--directory=lila` passed.

Verification:

- TDD: eleven new Python cases initially failed because Google was unavailable;
  delayed-audio and delayed-subtitle UI cases failed before their changes; the
  launcher case exposed the unconditional Piper-model prerequisite.
- `BLV_PIPER_DIR=/home/lehuy/lichess/lichess-research/.tools/commentary services/commentary/.venv/bin/python -m unittest discover -s services/commentary/tests`
  passed all 56 tests, no skips, 48.904 s, including real synthesis of all six
  Piper voices and eleven local fake-Google HTTP/contract cases. Initial run
  exposed two existing voice-discovery fixtures inheriting BLV_PIPER_DIR;
  fixtures now explicitly isolate the Piper path/provider. Final log:
  `/tmp/commentary-gemini-tests-final.log`.
- `python3 -m unittest discover -s scripts/tests -p test_local.py`: 7 passed.
- `node ui/test commentary.test.ts`: 18 passed; final log:
  `/tmp/commentary-gemini-ui-focused.log`.
- Full `pnpm test`: 283 passed, 2 failed (285 total). The failures are existing
  untracked `lobby/tests/coach.test.ts` and `round/tests/coach.test.ts`, importing
  absent `lobby/src/lobby.coach` and `round/src/coach`; no commentary failure.
  Log: `/tmp/commentary-gemini-ui-tests.log`. Existing test-environment
  `no indexedDB` messages also appear without causing commentary failures.
- Frozen pnpm install and `./ui/build round` passed (JS, TypeScript, Sass and
  asset generation); log: `/tmp/commentary-gemini-ui-build.log`. No Scala code
  changed. Scoped Oxfmt and type-aware Oxlint passed; removed one redundant
  pre-existing cast in the modified commentary test to satisfy lint.
- Python compilation, `bash -n lichess-local`, `git diff --check` and patch
  reverse-apply check passed. Existing homepage HTTP 200 at
  `http://172.31.8.156:9663`.

Remaining manual verification: fill `GEMINI_API_KEY` in
`services/commentary/.env`, then `./lichess-local stop` and
`./lichess-local --no-build`; reload the URL printed by the launcher, start a
standard game, enable commentary and try the voice picker. The running worker
was left on its existing Piper configuration until this restart. Real Google
credentials/model entitlement/quota, provider latency, browser audio flow and
subjective Vietnamese voice quality have not been verified. Health readiness
means configured credentials and engine readiness, not validated Google access.
Google may charge for generation; cancelling the local request cannot guarantee
cancellation of Google's work. No acceptance claim is made for the two missing
coach modules.

## Gemini real-response MIME fix (2026-11-17)

- [x] Reproduced user's subtitle-only result with a configured Gemini worker.
      Health identified `ttsProvider=gemini`. Logs also showed one HTTP 429;
      a direct Google request succeeded with HTTP 200 and nonempty PCM audio.
- [x] Root cause: Google returned `audio/l16; rate=24000; channels=1`, while the
      initial regex only accepted a rate/optional-codec form with no whitespace
      or channel parameter. Valid audio was rejected as a PCM-format error.
- [x] Added a regression using the exact observed MIME; it failed before the
      fix with `Gemini TTS PCM format invalid`. PCM parsing now accepts spaced
      parameters and different ordering, validates explicit mono channels and
      PCM codec, and rejects duplicate/unknown parameters and invalid rates.
- [x] All 12 Gemini tests passed, including the observed response and invalid
      stereo/duplicate-rate/non-PCM cases. Full commentary suite: 57 passed,
      no skips, 77.598 s, including actual Piper synthesis. Log:
      `/tmp/commentary-gemini-mime-tests.log`.
- [x] Restarted the local stack using `./lichess-local stop` then
      `./lichess-local --no-build`. All six service ports are open; homepage
      HTTP 200 at `http://172.31.8.156:9663`.
- [x] Real end-to-end HTTP voice sample through Lila -> worker -> Google:
      `GET /commentary/voice/piper-vais1000` returned HTTP 200, `audio/wav`;
      decoded WAV is mono, 16-bit, 24 kHz, 5.36 s, 257,324 bytes. Request took
      6.11 s. Verified sample saved at `/tmp/commentary-gemini-fixed.wav`.
      Python compilation and `git diff --check` passed. No UI/Scala changes.

The original external-API limitation above is now partially resolved: real
Google synthesis and the Lila voice route have been checked with the user's
configured key, which was neither printed nor committed. Browser playback and
subjective listening remain manual checks. The observed 429 was not reproduced
by the successful probes; quota/throughput errors may still occur on later
requests and remain distinct from the corrected MIME parser. Existing coach
test failures documented above are outside this Python fix.

## Confirmed Gemini daily quota exhaustion (2026-11-17 session)

- [x] Checked new gameplay logs after the MIME fix: two comments returned audio
      (3.410 s / 5.345 s), followed by repeated Gemini HTTP 429 responses.
- [x] One direct diagnostic request to the configured model returned HTTP 429,
      `RESOURCE_EXHAUSTED`, with structured QuotaFailure:
      `GenerateRequestsPerDayPerProjectPerModel-FreeTier`, quotaValue `10`, model
      `gemini-3.1-flash-tts`, and RetryInfo `56860s` (~15 h 48 m).
      This confirms per-day request exhaustion, rather than inferring it from a
      generic 429. No API key or full prompt was logged or committed.
- [x] Checked Google's current rate-limit documentation: daily request quotas
      apply per project/model and reset at midnight Pacific time. Tier 1 requires
      an active linked billing account. Reference:
      https://aistudio.google.com/docs/rate-limits .

Current blocker: this project's ten free daily requests are exhausted. A fresh
speech request cannot succeed until quota resets or the user provisions suitable
paid quota. Generated samples and diagnostic synthesis requests also consume this
small allowance. No further live synthesis probes were made after confirming
exhaustion. Billing, API key and selected model were left unchanged; this check
made no production code change and did not require another stack restart.

The current UI still shows the generic subtitle-only error for Google 429; it
does not identify daily quota exhaustion. No claim that browser playback works
is made. Existing MIME fix remains validated by the previous real WAV and tests.

## Provider switching and perceived Stockfish delay (2026-11-17)

- [x] Confirmed existing `BLV_TTS_PROVIDER=piper|gemini|auto` supports switching
      while preserving the API key; documented exact steps and restart scope
      in `LOCAL.md`. The current Nữ/Nam picker selects voices, not providers.
      No provider preference or running service was changed in this diagnostic.
- [x] Inspected `lila/modules/fishnet/src/main/FishnetPlayer.scala`: gameplay
      intentionally delays work before book lookup/engine dispatch. First reply
      is delayed two seconds; later delay depends on clock and ply, with a
      five-second base cap randomized by 0.5–1.5 (up to 7.5 s after ply 9).
      This is source inspection, not a measured gameplay latency benchmark.
- [x] Recent commentary logs show engine analysis around 210–646 ms, while
      successful cloud audio took about 3.7–4.8 s end-to-end. Commentary and
      gameplay use separate engine paths; these logs do not establish the
      user's actual computer-move response time.
- [x] Fishnet is configured for one core. A prior proxy log reported CPU
      starvation; current CPU pressure was low (~0.5 percent at inspection),
      so that old warning alone does not establish the current cause.

Asked whether the delay concerns computer replies or commentary/evaluation.
No engine strength, gameplay pacing, thread count or deadlines were changed.
Only documentation changed; `git diff --check` was run. Browser gameplay
latency and the user's intended pacing remain unverified.

## Lightweight Vietnamese TTS research (2026-11-17)

- [x] Checked host: Intel i3-1005G1, two physical cores / four logical CPUs.
      Search focused on small CPU/ONNX models, not GPU latency claims.
- [x] Verified primary model cards and Hugging Face metadata for three candidates:
  - `loanhviet/Kokoro-Vietnamese-Lite` revision
    `a4c4cfefa8caf35aaaeb5ec628be996858df2121`: Apache-2.0, 9.2 MB int8
    ONNX, two Vietnamese voices. Author reports RTF 0.075 in browser WASM on
    one i5-12500H thread. Needs the supplied text frontend and separate SEA-G2P
    dictionary. Author reports lower naturalness than teacher, unnatural pauses
    and weaker reading of numbers/identifiers. Speed is promising; improvement
    over installed Piper is unverified.
  - `pnnbao-ump/VieNeu-TTS-v3-Nano` revision
    `aba295eb96a6fa6003ebe417cc1f2802a7adc1dc`: Apache-2.0, 48M parameters,
    roughly 280 MB ONNX assets, torch-free. Author reports RTF 0.11–0.22 on
    a newer desktop CPU with six threads; model card and repository disagree
    on i7 vs i5 benchmark CPU. Preview limitations include flatter prosody,
    occasional dropped syllables and weak short/bilingual inputs.
  - `supertone-oss-archive/supertonic-3` revision
    `aafc6e32416a594460b32413efc49d7fe4ce6d46`: about 99M parameters,
    ONNX, explicitly supports Vietnamese, weights under OpenRAIL. Upstream
    repository was archived September 2026; maintenance status is a tradeoff.
- [x] Sources: https://huggingface.co/loanhviet/Kokoro-Vietnamese-Lite ,
      https://huggingface.co/pnnbao-ump/VieNeu-TTS-v3-Nano ,
      https://github.com/pnnbao97/VieNeu-TTS#-4-benchmarks ,
      https://github.com/supertone-oss-archive/supertonic ,
      https://huggingface.co/supertone-oss-archive/supertonic-3 .

Research only: no model was downloaded, installed, benchmarked or activated;
no stack restart or gameplay change. Published RTFs are not local measurements
or time-to-first-audio guarantees. Next meaningful evaluation is a bounded
comparison of short chess utterances, first audio/full generation latency,
CPU interference with Stockfish and listening to Vietnamese tones/prosody.
Keep the current Piper available until a replacement meets those checks.

## VieNeu v3 Nano trial and voice removal (2026-11-17)

Implementation and tests assisted by Codex.

- [x] Removed public Nam 1 (`piper-vivos-28`) and Nữ 2 (`piper-vivos-40`) from
      Python catalogue, Scala whitelist and UI. Removed saved selections fall
      back to the default through the existing UI validation. Four voices remain.
- [x] Added `BLV_TTS_PROVIDER=vieneu`, isolated persistent `nano_worker.py`,
      configurable model path/interpreter/deadline/steps/threads, PCM-to-WAV
      conversion and existing bounded request/audio cache behavior. No GPU or
      Google API is used. Model loads once at startup; inference occurs off the
      HTTP/game processing loop in a subprocess, serialized by existing transport.
- [x] Installed `vieneu==3.8.4` in ignored `.venv-nano`, recorded its entire
      dependency environment in `requirements-vieneu.lock`. Downloaded only six
      inference files (281,756,486 bytes) from pinned model revision
      `aba295eb96a6fa6003ebe417cc1f2802a7adc1dc`. Paths/URLs/SHA256/license are in
      `services/commentary/nano-assets.json`; local files under
      `~/.cache/lichess-commentary/vieneu-v3-nano/<revision>`.
- [x] Mapped the remaining voice slots to Mỹ Duyên, Trúc Ly, Xuân Tiên and
      Đức Trí. Configured the private `.env` for Nano, 8 steps, one CPU thread,
      seven-second synthesis deadline. Preserved API key and Piper installation.
      README and LOCAL.md document switching back using provider `piper`.
- [x] Samples now carry a timestamp query to bypass browser caches when provider
      changes; existing server RAM cache still avoids duplicate generation.
      Confirmed the old route used a one-hour private browser cache before this.
- [x] Regression tests failed before implementing removed-voice validation,
      Nano registration and sample cache invalidation. Real Nano test exercises
      all four voices, RAM caching, no phrasebook warmup and process cleanup.
- [x] All 60 commentary tests passed, no skips, 254.494 s under concurrent build
      load; includes four real Piper and four real Nano voices. Final Gemini-only
      rerun: 12 passed. Log `/tmp/nano-python-tests.log`. Launcher: 7 passed.
- [x] Full frontend suite: 283/285 passed; the same two pre-existing missing-module
      failures remain in `lobby/tests/coach.test.ts` and `round/tests/coach.test.ts`.
      All 18 commentary tests passed; log `/tmp/nano-ui-tests-final2.log`.
      One intermediate voice-switch fixture mistakenly selected its existing
      voice; corrected it to select the remaining male voice and reran the suite.
- [x] UI build passed (`/tmp/nano-ui-build-final.log`); Scala stage passed in
      231 s, cache 99% (`/tmp/nano-scala-build.log`). Scoped Oxfmt and type-aware
      Oxlint passed. Python compilation and `git diff --check` passed.
- [x] Saved cumulative Lila delta against workspace base `b8fc69b` in
      `patches/lila-vieneu-nano.patch`; reverse apply check passed. This patch
      includes the previous Gemini UI delta; use it instead of applying both
      cumulative patches to the same base. Upstream revisions unchanged.
- [x] Restarted local stack and verified `/health`: ready, Stockfish 19,
      `ttsProvider=vieneu`, exactly four voices. First restart exposed a local
      setup error: resolving the virtualenv Python symlink selected system Python
      without the SDK. Corrected the private interpreter path without resolving
      the executable symlink; subsequent startup succeeded.
- [x] Live Lila voice routes all returned HTTP 200 / 24 kHz WAV. Samples:
      Mỹ Duyên 5.75 s audio / 3.613 s request; Trúc Ly 4.83 / 2.525;
      Xuân Tiên 4.10 / 2.335; Đức Trí 6.29 / 2.706. WAVs saved as
      `/tmp/nano-piper-<voice-id-suffix>.wav`. Removed voice routes returned
      HTTP 400. Existing homepage ready at `http://172.31.8.156:9663`.

The stack is left running with Nano for the user's listening trial. These are
four sample spot checks, not a benchmark distribution or proof of naturalness.
Nano is materially slower than Piper on this CPU. Browser listening and actual
match commentary remain manual checks: reload the current local URL, enable
commentary and switch voices. No claim of matching Piper speed or subjective
quality. Existing game-state/expiry guards remain in force; slow/obsolete
utterances may still be omitted. No billing or key changes were made.

## Five named commentators, personalized welcomes and faster delivery (2026-11-18)

Implementation and tests assisted by Codex. Interpreted the requested “Uc Tri”
as the existing VieNeu preset Đức Trí.

- [x] Replaced public voice ids and UI labels with Mỹ Duyên, Đức Trí, Hữu Quân,
      Anh Khôi and Mạnh Dũng (`vieneu-my-duyen`, `vieneu-duc-tri`,
      `vieneu-huu-quan`, `vieneu-anh-khoi`, `vieneu-manh-dung`). Updated Python,
      Scala whitelist and UI together. Obsolete saved ids use the default.
- [x] Each selection synthesizes exactly “Xin chào, tôi là {tên}, sẽ cùng bạn
      tận hưởng ván cờ này.” The sample cache key includes voice and personalized
      text. Choosing a different commentator stops the current sentence, clears
      obsolete pending speech and starts their welcome; requests reconnect with
      the selected id. Existing stale-response checks remain.
- [x] Set Nano speech speed to 1.2 via SDK duration control, retaining 24 kHz
      playback. Added configurable `BLV_NANO_SPEED` (0.8–1.5). Raised default and
      local `BLV_NANO_STEPS` to 16; retained one CPU thread and seven-second
      request deadline. This favors quality over eight-step synthesis throughput.
- [x] Investigated reported distortion: four prior WAVs had zero clipped samples,
      so clipping was not established as the cause. Added `nano_audio.pcm16`
      proportional peak attenuation above 0.9 full scale, without amplifying quiet
      noise or flattening peaks. Sixteen-step Nano may reduce model artifacts;
      subjective improvement/hiss elimination is not claimed without listening.
- [x] Updated Gemini/Piper fallback mappings and documentation. Names refer to
      Nano presets; fallback engines do not clone their identity (Piper has one
      female and one shared male voice). No API key or billing changes.
- [x] TDD evidence: named-welcome test failed on the old generic sample, UI label
      test failed on gender/pitch labels, active-selection test failed because old
      speech blocked the welcome, and real speed test failed when speed was
      ignored. Added PCM peak-shape protection and real five-voice synthesis tests.
- [x] Final complete commentary suite: 63 passed, no skips, 51.843 s. Includes
      real five-voice Nano and Piper fallback synthesis, speed comparison at
      1.0/1.2, personalized texts, peak handling and prior contracts. Log:
      `/tmp/named-python-final.log`. An earlier concurrent build/test run hit a
      seven-second Nano timeout; after builds finished the whole suite passed
      unchanged. Production deadlines were not relaxed.
- [x] All 18 commentary UI tests passed. Full `pnpm test`: 283/285 passed;
      the two existing missing-module failures remain in
      `lobby/tests/coach.test.ts` and `round/tests/coach.test.ts`.
      Log: `/tmp/named-ui-final.log`. Launcher suite: 7 passed.
- [x] UI build passed (`/tmp/named-ui-final-build.log`); Scala stage passed in
      213 s (`/tmp/named-scala-build.log`); scoped Oxfmt/type-aware Oxlint,
      Python compilation and `git diff --check` passed. Cumulative Lila patch
      saved as `patches/lila-named-commentators.patch` against workspace base
      b8fc69b, superseding previous cumulative commentary patches for that base;
      reverse apply check passed. Upstream revisions unchanged.
- [x] Restarted local stack and generated all five real named welcomes via
      Lila HTTP routes: all HTTP 200 / valid 24 kHz PCM WAV, peaks <=29490.
      Generated files and exact texts/measurements are in
      `/tmp/named-commentator-greetings/`. The running worker now caches these
      five welcomes for the user's trial. Homepage ready at
      `http://172.31.8.156:9663`.

Live sample spot checks (generation includes HTTP/proxy overhead):
- Mỹ Duyên: 3.96 s audio, 4.086 s request.
- Đức Trí: 4.27 s audio, 3.84 s request.
- Hữu Quân: 2.55 s audio, 2.147 s request.
- Anh Khôi: 3.05 s audio, 2.337 s request.
- Mạnh Dũng: 2.594 s audio, 2.075 s request.


Manual acceptance: Ctrl+F5 the local URL, enable commentary, select each name
and listen to the personalized welcome and normal move speech. Browser audio
playback, subjective clarity and the source of the reported roughness remain
listening checks; no claim that Nano now matches Piper latency or is free of
model artifacts. Sixteen-step mode consumes more CPU time than eight-step mode.

## Frontend still showed obsolete voices: asset manifest correction (2026-11-18)

- [x] Reproduced at HTTP boundary: actual served round page loaded
      `round.7GTNMOJG.js` and `lib.UZT2YQ53.js`, containing old Piper voice ids.
      Served bytes matched disk; this was not merely browser caching. New named
      bundles existed on disk but were not referenced by the asset manifest.
- [x] Root cause of prior incomplete handoff: `./ui/build round` intentionally
      does not emit a manifest. This is explicit in `ui/.build/src/main.ts` and
      `env.buildOk()`. Earlier successful scoped builds did not establish that
      the browser could load the new catalogue; prior handoff evidence above
      should be read with this correction.
- [x] Ran full unqualified `./ui/build`, exit 0, 8.443 s. It generated
      `manifest.defe18ea.js`, server manifest hash e269baee and
      `round.IX5TYIR3.js` importing the named catalogue in `lib.VXV7JF4V.js`.
      Log: `/tmp/named-manifest-full-build.log`.
- [x] Restarted local stack with `./lichess-local stop` and
      `./lichess-local --no-build` to reload the production manifest. HTTP page
      now references the new manifest and round bundle.
- [x] Actual Chromium/Playwright verification on a freshly created anonymous
      local AI test game: enabled commentary and asserted the rendered select
      options are exactly Mỹ Duyên, Đức Trí, Hữu Quân, Anh Khôi, Mạnh Dũng.
      Browser used `round.IX5TYIR3.js`. Screenshot:
      `/tmp/named-commentary-browser.png`; reproducible local check script:
      `/tmp/verify-named-commentary.cjs`. The initial read-only attempt to use
      an existing player's page correctly redirected the isolated browser to
      spectator mode, so verification used its own anonymous game/cookie.
- [x] Updated LOCAL.md and commentary README to require full UI build before
      runtime acceptance and explain that package-only builds cannot publish
      the new manifest. `git diff --check` passed. No production source changed
      in this follow-up; no Scala rebuild or further acoustic changes needed.

Running URL remains `http://172.31.8.156:9663`. Existing tabs still executing
old JavaScript need one page reload; fresh browser rendering is now verified.
This browser check establishes catalogue visibility, not subjective audio quality.

## Per-voice pace adjustment and bounded Nano queue (2026-11-18)

- [x] Compared all five presets on the identical spoken sentence “Trắng vừa đưa
      mã lên ép ba, kiểm soát khu trung tâm.”, one CPU thread, 16 steps, seed 42.
      Inspected SDK: its speaker-conditioned duration predictor determines audio
      length, divided by the speed parameter. Longer output also increases latent
      frame count/decoder work. This accounts for measured voice-specific pacing;
      identical base speed does not make all presets speak at the same rate.
- [x] Found and reproduced a second waiting cause: shielded Nano renders could
      accumulate obsolete sentences when the active comment was cancelled. The
      regression rendered old -> obsolete -> latest before the fix; after the fix
      it renders old -> latest. Worker now tracks at most one in-flight Nano
      render, shares equal requests and lets cancelled waiters disappear without
      creating queued synthesis jobs. Shutdown cancels/joins that tracked task.
      Current-position/expiry checks and deadlines remain unchanged.
- [x] Added Nano-only pacing factors in `voices.py`: Mỹ Duyên 1.40, Đức Trí 1.45,
      Anh Khôi 1.15; Mạnh Dũng/Hữu Quân remain 1.00. With base 1.2, effective
      speeds are 1.68, 1.74, 1.38, 1.2 and 1.2, capped at 2.0. The model still
      generates at 24 kHz with 16 steps, one CPU thread and the existing PCM
      headroom. No playback-rate resampling, quality-step reduction or retuning
      of the two user-approved voices.
- [x] Tests failed before the pacing/queue fixes and pass afterward. All seven
      focused Nano tests passed initially; full suite with three added cases:
      66 passed, no skips, 59.224 s (`/tmp/voice-pace-full-tests.log`). Launcher:
      7 passed. Python compilation and `git diff --check` passed. This follow-up
      changed Python/docs only, so no UI/Scala build or manifest replacement.
- [x] Restarted local stack. All five real Lila voice routes returned HTTP 200,
      valid 24 kHz WAV. Welcome durations: Mỹ Duyên 2.75 s, Đức Trí 2.87 s,
      Anh Khôi 2.67 s; Mạnh Dũng 2.594 s and Hữu Quân 2.55 s exactly match the
      previously measured welcome durations. Requests took 1.886–2.827 s in
      these spot checks. `/tmp/voice-pace-live.json` records results; welcomes
      are now cached in the running worker.

Controlled same-sentence comparison (audio duration / synthesis seconds):
- Mạnh Dũng: 2.18 -> 2.18 s audio; 1.835 -> 1.77 s synthesis.
- Hữu Quân: 2.14 -> 2.14 s audio; 1.763 -> 1.824 s synthesis.
- Mỹ Duyên: 3.52 -> 2.496 s audio; 2.438 -> 1.993 s synthesis.
- Đức Trí: 3.64 -> 2.51 s audio; 2.549 -> 2.078 s synthesis.
- Anh Khôi: 2.53 -> 2.21 s audio; 1.778 -> 1.913 s synthesis.


The three slower presets now finish within 30% of Mạnh Dũng on the controlled
regression sentence. Measurements in `/tmp/voice-pace-before.json` and
`/tmp/voice-pace-after.json` are single-sentence spot checks, not a latency
benchmark distribution. Anh Khôi's small synthesis-time difference is within
observed run-to-run variation; do not claim every individual generation became
faster. Listening must confirm intelligibility/prosody at the higher per-voice
rates. Very fast gameplay can still intentionally discard stale comments;
shorter speech and bounded queued work do not guarantee narration of every move.

Current URL: `http://172.31.8.156:9663`. Reload and select each name to listen;
Mạnh Dũng and Hữu Quân keep their approved settings. No API/billing changes.

## Final three-commentator catalogue and current-state document (2026-11-18)

- [x] Removed `vieneu-my-duyen` and `vieneu-duc-tri` from Python catalogue,
      Nano/Gemini mappings, Scala whitelist and frontend. Remaining UI order:
      Mạnh Dũng (default), Hữu Quân, Anh Khôi. Retained all three voices' pacing.
- [x] Obsolete stored selections fall back to Mạnh Dũng. Negative tests explicitly
      reject the two removed ids; welcome/voice/timing fixtures now cover the
      final three presets. All remaining Piper fallback roles share VIVOS speaker
      45; updated default fallback model path in launcher, example/private config
      and model-discovery tests to keep the default-voice model contract valid.
      API key and active Nano provider were preserved.
- [x] Created `docs/binh-luan-vien-tieng-viet.md`: current user experience, three
      voices/welcomes, architecture diagram, authoritative snapshots/SSE,
      python-chess/Stockfish/templates, Nano process/audio pipeline, bounded work,
      cancellation/cache/expiry, endpoints/security, pinned model/dependencies,
      current config, full-build/restart instructions and validation limits.
      This document contains final-state design only, without discarded voice
      profiles or the experiment history. Rewrote commentary README as a concise
      operating guide linking to that document. Historical task evidence remains
      here for reproducibility.
- [x] Red-green evidence: removed-voice service test and three-name picker test
      failed against the five-voice implementation. Full commentary Python suite
      passed: 66 tests, no skips, 148.527 s under concurrent build load, including
      real three-voice Nano and Piper synthesis (`/tmp/three-voices-python.log`).
      Launcher suite: 7 passed. Full UI suite: 283/285 passed, all 18 commentary
      cases passed; existing missing-module coach failures remain in
      `lobby/tests/coach.test.ts` and `round/tests/coach.test.ts`
      (`/tmp/three-voices-ui-tests.log`).
- [x] Full unqualified UI build passed in 8.065 s, generated
      `manifest.344752a3.js` / server manifest hash 6a21e761. Scala stage passed
      in 95 s, cache 99%. Logs `/tmp/three-voices-ui-build.log` and
      `/tmp/three-voices-scala.log`. Scoped Oxfmt/type-aware Oxlint, Python
      compilation and `git diff --check` passed.
- [x] Saved cumulative Lila changes against workspace b8fc69b in
      `patches/lila-commentary-three-voices.patch`, superseding previous cumulative
      commentary patches for that same base. Reverse apply check passed;
      upstream revisions unchanged.
- [x] Restarted local stack. Chromium check on its own anonymous test game:
      rendered options exactly Mạnh Dũng, Hữu Quân, Anh Khôi and selected
      `vieneu-manh-dung` despite injected obsolete localStorage selection.
      Browser loads `round.NCBCPC73.js`. Screenshot
      `/tmp/three-voices-browser.png`, check `/tmp/verify-three-voices.cjs`.
- [x] Live Lila sample routes: removed ids HTTP 400; all three retained ids
      HTTP 200 and nonempty 24 kHz WAV. Current URL
      `http://172.31.8.156:9663`; existing tabs need a reload.

The stack remains on Nano with three voices. Existing whole-project coach test
failures are not fixed or hidden. Browser catalogue/default behavior and WAV
routes were verified; subjective listening quality still belongs to the user's
trial. Source changes and documentation were assisted by Codex.
