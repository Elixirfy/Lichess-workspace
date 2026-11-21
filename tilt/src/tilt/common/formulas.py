"""Ports pinned to the Lichess source in this monorepo; all scores are White POV."""
import math
import statistics
from functools import lru_cache

import chess


def chances(cp=None, mate=None):
    # lila/ui/lib/src/ceval/winningChances.ts: mate=0 is negative here.
    if mate is not None:
        value = (21 - min(10, abs(mate))) * 100 * (1 if mate > 0 else -1)
    elif cp is not None:
        value = max(-1000, min(1000, cp))
    else:
        return None
    return 2 / (1 + math.exp(-0.00368208 * value)) - 1


def as_cp(cp=None, mate=None):
    # lila/modules/tree/src/main/eval.scala forceAsCp, then Eval.Cp.ceiled.
    return max(-1000, min(1000, cp)) if cp is not None else (
        (1000 if mate > 0 else -1000) if mate is not None else None
    )


def win_percent(cp=None, mate=None):
    # scalachess/core/src/main/scala/eval.scala WinPercent.fromScore.
    value = as_cp(cp, mate)
    return None if value is None else 50 + 50 * chances(value)


def move_accuracy(before, after):
    # lila/modules/analyse/src/main/AccuracyPercent.scala fromWinPercents.
    if before is None or after is None:
        return None
    if after >= before:
        return 100.0
    return max(0.0, min(100.0, 103.1668100711649 * math.exp(
        -0.04354415386753951 * (before - after)) - 3.166924740191411 + 1))


def judgement(cp_before, mate_before, cp_after, mate_after, sign=1):
    # lila/modules/tree/src/main/Advice.scala: server uses >=, liveAnnotate.ts uses >.
    if (cp_before is None and mate_before is None) or (cp_after is None and mate_after is None):
        return None
    if cp_before is not None and cp_after is not None:
        # Server winningChances is not cp-clamped (unlike the UI).
        raw = lambda cp: 2 / (1 + math.exp(max(-700, min(700, -0.00368208 * cp)))) - 1
        loss = sign * (raw(cp_before) - raw(cp_after))
        return next((name for threshold, name in ((.3, 'blunder'), (.2, 'mistake'),
                                                  (.1, 'inaccuracy')) if loss >= threshold), 'good')
    # Advice.scala MateSequence / MateAdvice, expressed in the mover's POV.
    prev = mate_before * sign if mate_before is not None else None
    post = mate_after * sign if mate_after is not None else None
    created = mate_before is None and post is not None and post <= 0
    lost = prev is not None and prev > 0 and (post is None or post <= 0)
    if created:
        cp = (cp_before or 0) * sign
        return 'inaccuracy' if cp < -999 else 'mistake' if cp < -700 else 'blunder'
    if lost:
        cp = (cp_after or 0) * sign
        return 'inaccuracy' if cp > 999 else 'mistake' if cp > 700 else 'blunder'
    return 'good'


@lru_cache(maxsize=4096)
def _accuracy_window_std(values):
    return statistics.pstdev(values)


def game_accuracy(scores, start_white=True):
    """White/black game accuracy from position scores, including the initial position.

    None values stay missing. This is the volatility-weighted/harmonic mean in
    lila/modules/analyse/src/main/AccuracyPercent.scala gameAccuracy.
    """
    if len(scores) < 3:
        return {'white': None, 'black': None}
    wps = [win_percent(*s) if s is not None else None for s in scores]
    size = max(2, min(8, (len(scores) - 1) // 10))
    windows = [wps[:size]] * (min(size, len(wps)) - 2)
    windows += [wps[i:i + size] for i in range(len(wps) - size + 1)]
    groups = {'white': [], 'black': []}
    for i, (before, after, window) in enumerate(zip(wps, wps[1:], windows)):
        if before is None or after is None or any(x is None for x in window):
            continue
        color = 'white' if ((i % 2 == 0) == start_white) else 'black'
        accuracy = move_accuracy(before, after) if color == 'white' else move_accuracy(100 - before, 100 - after)
        weight = max(.5, min(12, _accuracy_window_std(tuple(window))))
        groups[color].append((accuracy, weight))
    result = {}
    for color, values in groups.items():
        if not values:
            result[color] = None
        else:
            weighted = sum(a * w for a, w in values) / sum(w for _, w in values)
            harmonic = 0 if any(a == 0 for a, _ in values) else len(values) / sum(1 / a for a, _ in values)
            result[color] = (weighted + harmonic) / 2
    return result


def _mix_score(y, w, b):
    # scalachess/core/src/main/scala/Divider.scala score, verbatim decision table.
    if w == 0:
        return {1: 1 + y, 2: 2 + (6 - y) if y < 6 else 0,
                3: 3 + (7 - y) if y < 7 else 0, 4: 3 + (7 - y) if y < 7 else 0}.get(b, 0)
    if w == 1:
        return {0: 1 + (8 - y), 1: 5 + abs(4 - y), 2: 4 + (7 - y), 3: 5 + (7 - y)}.get(b, 0)
    if w == 2:
        return {0: 2 + y - 2 if y > 2 else 0, 1: 4 + y - 1, 2: 7}.get(b, 0)
    if w == 3:
        return {0: 3 + y - 1 if y > 1 else 0, 1: 5 + y - 1}.get(b, 0)
    return 3 + y - 1 if w == 4 and b == 0 and y > 1 else 0


def division(boards):
    # scalachess Divider.scala; runtime CanPlay.playBoards includes initial + after-boards.
    middle = end = None
    for i, board in enumerate(boards):
        pieces = (board.occupied & ~(board.kings | board.pawns)).bit_count()
        sparse = ((board.occupied_co[chess.WHITE] & chess.BB_RANK_1).bit_count() < 4 or
                  (board.occupied_co[chess.BLACK] & chess.BB_RANK_8).bit_count() < 4)
        mixed = sum(_mix_score(y + 1,
                              (board.occupied_co[chess.WHITE] & (0x0303 << (x + 8 * y))).bit_count(),
                              (board.occupied_co[chess.BLACK] & (0x0303 << (x + 8 * y))).bit_count())
                    for y in range(7) for x in range(7))
        if middle is None and (pieces <= 10 or sparse or mixed > 150):
            middle = i
        if end is None and pieces <= 6:
            end = i
    if middle is None:
        return None, None
    return (middle if end is None or middle < end else None), end


def speed(initial, increment):
    # scalachess Speed.scala; Clock.Config estimates initial + 40 * increment.
    seconds = initial + 40 * increment
    return next(name for bound, name in ((30, 'ultraBullet'), (180, 'bullet'),
        (480, 'blitz'), (1500, 'rapid'), (21600, 'classical'), (float('inf'), 'correspondence'))
                if seconds < bound)
