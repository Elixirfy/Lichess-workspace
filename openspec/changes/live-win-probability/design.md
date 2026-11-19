# Implementation decisions

## Data flow

1. The existing round WebSocket updates each player's and spectator's authoritative game history.
2. A new move or round reload invalidates the old WDL immediately. The client requests
   `GET /game/:id/win-probability`; it never submits a FEN or moves to the public endpoint.
3. The Scala controller loads the live game, checks feature access and standard variant,
   and passes its complete SAN history to the private prediction service.
4. A bounded Python scheduler coalesces requests by game, cancels superseded analysis,
   and shares cached results between spectators. Stockfish receives the full move stack.
5. The client accepts results only when game ID, SAN history, status and winner match.
   Pending results poll every 200 ms; ready results stop polling until another game event.

This keeps the existing socket protocol unchanged. Adding a custom WDL push protocol is
deferred until measurements justify maintaining changes in both lila and lila-ws.

## Correctness and failure handling

- WDL is always White / draw / Black, obtained from `PovWdl.white()`.
- Official game results bypass Stockfish in Scala and in the client. Aborts have no percentages.
- Historical replay hides the live-position percentages. Board orientation never changes meaning.
- The worker keeps at most 64 queued games and 512 cached predictions. The final local
  deployment uses two engines, each with one thread, 64 MiB hash and a 250 ms search,
  under a shared 2 CPU / 512 MiB container limit. The initial milestone used one engine.
- Cancellation discards the obsolete result while draining its bounded UCI search before
  reusing that engine; it must not cancel python-chess's ready handshake Future. Official
  results still bypass queued/active analysis without waiting for that drain.
- Scala coalesces identical requests for 150 ms, caps its cache at 1024 entries, and times out
  worker HTTP calls at 800 ms. Move processing never waits for the prediction service.
- UI requests time out at 1500 ms; unavailable/busy states retry after 2 s. Hidden tabs pause requests.
- Only the local reverse proxy is published, on `127.0.0.1:8080`; the worker stays internal.

## Scope and review

Since 2026-11-18, the user explicitly enables the panel for both participants in
standard games, including human opponents and the built-in AI. Player bootstrap
data advertises the server capability; the endpoint independently enforces
feature enablement, variant and existing block checks. Player-page theft checks
remain intact. The same conditional White/Black display, history guards and
bounded worker are used. Missing human-model context still selects engine WDL.

The current display is expected-score advantage, W+D/2 and B+D/2. The user
replaces the earlier W/(W+B) projection after draw-heavy estimates produced
misleading 0/100 displays. The raw outcome probabilities remain distinct from
this derived metric. The user's subsequent UI request removes the two live
caption lines; the panel title tooltip retains source, advantage, 50% midpoint
and draw treatment. Do not describe it as the participant's win probability.

The original engine milestone did not calibrate human outcomes; the later human
pilot has its own model card and limits. Public hosting and other variants remain deferred.

The analysis review extension (18/11/2026) moves WDL validation/expected-score
rounding into a shared pure ceval module. Browser UCI captures native WDL when
advertised; legacy cp-only nodes use an explicitly identified Stockfish 15.1 WDL
model conversion. Standard analysis reads the selected node and shows two values
on the existing vertical gauge. Original mainline path/ply/FEN guards limit the
recorded terminal result to that endpoint. Variations and earlier positions keep
their own evaluation; missing evaluations clear rather than reuse gaugeLast.
The old gauge remains for other callers/variants. No prediction service requests,
new server interfaces, human context reconstruction or ASR changes are introduced.
The live round page shows the official result when a watched game ends; a later page reload
may route to Lichess's separate analysis page.

Code and tests are AI-assisted using Codex. The user reviews and accepts this local fork.
No upstream issue, pull request or public deployment is part of this change.

## Verification

Meaningful regression cases cover point of view, repetition history, same-ply replacement,
rapid moves, duplicate spectators, cancellation, terminal results and engine failure recovery.
Report worker HTTP latency separately from browser end-to-end latency. A sub-second pilot
target is not a scalability claim: different concurrent games share bounded engine capacity.
