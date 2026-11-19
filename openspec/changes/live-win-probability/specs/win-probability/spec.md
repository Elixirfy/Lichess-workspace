# Requirements

## Engine estimate
- For standard chess, retain raw White win/draw/Black win probabilities in the API. Display a bar and whole White/Black percentages from Lichess Win% using the White-oriented engine score clamped to ±1000 cp. Treat a nonzero mate score as the corresponding signed bound. Show the metric in the tooltip and accessible label.
- When no usable score is available, display the engine's W+D/2 and B+D/2 with a WDL label. Raw WDL must be finite, nonnegative and sum to one. The two whole percentages must sum to 100%. An official draw on the live board is shown as the result without an estimated bar.
- Use the White perspective for both the engine score and WDL.
- Supply move history to Stockfish so repeated positions and move counters are interpreted correctly.

## Freshness and lifecycle
- Refresh after authoritative moves and reconnects. A takeback followed by another move must not reuse an unrelated result at the same ply.
- Distinguish pending, ready, stale/unavailable, and finished states.
- Official server results for checkmate, resignation, timeout, and draw override engine predictions. Aborted or unfinished games must not invent a winner.

## Analysis review gauge
- Standard analysis reuses the vertical gauge with the same Win% projection, integer rounding and WDL fallback as the live panel. The tooltip identifies the selected metric. A settled position uses its proven result.
- Use only the selected node's evaluation. No previous-node gauge value may remain when the new node has no evaluation. Flip labels without exchanging their White/Black meaning.
- Recorded game results apply only to the original complete mainline endpoint, identified by path, ply and FEN; earlier positions and variations with the same ply retain their own evaluation.
- Keep existing local engine permissions/toggles and other variants' gauge behavior. The two-column vertical layout remains hidden on single-column mobile.

## Isolation and access
- Serve predictions to both players and spectators of enabled standard games, including human-versus-human and built-in AI games. Enforce feature enablement, variant and existing block/access checks on the server using authoritative game data.
- The worker accepts authoritative internal requests, is not published publicly, and has bounded CPU, memory, concurrency, queue length, cache, and search duration.
- Share evaluation of a game position across viewers. Superseded requests must not overwrite a newer position.
- Worker failures, timeouts, and queue saturation must not impair gameplay.

## Acceptance
- Start the local stack from documented commands and play a game between two browser sessions.
- Both players and a spectator see the White/Black Win% update from authoritative engine responses and can reload or reconnect without incorrect position results.
- Verify the White/Black perspective, takebacks, official results, and unavailable-worker behavior.
- Run unit/integration checks for numerical and scheduling invariants, upstream checks for changed code, and browser smoke checks.
- Report measured latency and test conditions. P95 under one second at pilot load is a target, not a claim before measurement.
