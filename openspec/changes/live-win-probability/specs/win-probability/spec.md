# Requirements

## Engine estimate
- For standard chess, retain raw White win/draw/Black win probabilities and identify the selected source. Display only the bar and expected-score percentages W+D/2, B+D/2; identify advantage, source, balance and half-point draws in the hover tooltip and accessible label.
- Raw WDL values must be finite, non-negative and sum to one; the two displayed values must sum to 100.0%. A live all-draw estimate has equal expected points. An official draw is shown as the result without an estimated bar.
- Correctly transform engine side-to-move WDL to the White perspective.
- Supply move history to Stockfish so repeated positions and move counters are interpreted correctly.

## Freshness and lifecycle
- Refresh after authoritative moves and reconnects. A takeback followed by another move must not reuse an unrelated result at the same ply.
- Distinguish pending, ready, stale/unavailable, and finished states.
- Official server results for checkmate, resignation, timeout, and draw override engine predictions. Aborted or unfinished games must not invent a winner.

## Analysis review gauge
- Standard analysis reuses the vertical gauge to show White/Black expected-score percentages with the same shared W+D/2 projection as the live panel.
- Prefer validated native engine WDL, normalized to White. For historical cp-only scores, identify Stockfish 15.1 model conversion in the tooltip; never describe it as recovered original WDL or a calibrated personal win probability.
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
- Both players and a spectator see expected-score advantage update from authoritative responses, with 50% balance and half-point draw explanations in the tooltip, and can reload/reconnect without incorrect position results.
- Verify the White/Black perspective, takebacks, official results, and unavailable-worker behavior.
- Run unit/integration checks for numerical and scheduling invariants, upstream checks for changed code, and browser smoke checks.
- Report measured latency and test conditions. P95 under one second at pilot load is a target, not a claim before measurement.
