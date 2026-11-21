"""Unified standard-chess schema; clocks in seconds, scores in White POV.

API source: lila/modules/api/src/main/GameApiV2.scala and analyse/JsonView.scala.
clocks[i] is a Centis value AFTER played ply i+1, not a think time. A finished
async game may have one extra entry: the stopped active clock, NOT a move.
analysis[i] evaluates the position AFTER ply i+1; `eval` is cp, `mate` signed
moves-to-mate, `best` is the alternative to the move just played (Advice/Info).
division.middle/end are zero-based indices of BEFORE-move boards (ply boundary).
createdAt/lastMoveAt are epoch milliseconds. lastMoveAt is NOT necessarily end:
GameExt.finish doesn't update movedAt. See docs/du-lieu-lichess.md for end bounds.
"""
from datetime import datetime, timezone
import hashlib
import time

import chess

from ..common.formulas import division, speed


def _stamp(date, clock):
    if not date or not clock or '?' in date + clock:
        return None
    try:
        return int(datetime.strptime(date + ' ' + clock, '%Y.%m.%d %H:%M:%S').replace(
            tzinfo=timezone.utc).timestamp() * 1000)
    except ValueError:
        return None


def api_game(raw, observed_ms=None):
    if raw.get('variant', 'standard') != 'standard':
        raise ValueError('Only standard chess is supported')
    board = chess.Board(raw.get('initialFen', chess.STARTING_FEN))
    if not board.is_valid():
        raise ValueError('Invalid initial position')
    players = raw['players']
    clock = raw.get('clock', {})
    observed_ms = observed_ms or int(time.time() * 1000)
    game = dict(game_id=raw['id'], source='api', rated=raw.get('rated', False),
        white=players['white'].get('user', {}).get('id'),
        black=players['black'].get('user', {}).get('id'),
        white_rating=players['white'].get('rating'), black_rating=players['black'].get('rating'),
        white_berserk=players['white'].get('berserk', False), black_berserk=players['black'].get('berserk', False),
        speed=raw.get('speed'), initial_seconds=clock.get('initial'),
        increment_seconds=clock.get('increment'), start_ms=raw.get('createdAt'),
        last_move_ms=raw.get('lastMoveAt'), observed_ms=observed_ms,
        status=raw.get('status'), winner=raw.get('winner'), initial_fen=board.fen())
    sans = raw.get('moves', '').split()
    clocks, analysis = raw.get('clocks', []), raw.get('analysis', [])
    game['plies'] = len(sans)
    finished = game['status'] not in ('created', 'started', None)
    if not finished:
        raise ValueError('Import only finished games')
    game['result'] = ('1-0' if game['winner'] == 'white' else '0-1' if game['winner'] == 'black'
                      else '1/2-1/2' if game['status'] in ('draw', 'stalemate') else '*')
    moves, boards = [], []
    for i, san in enumerate(sans):
        before, color = board.fen(), 'white' if board.turn else 'black'
        boards.append(board.copy(stack=False))
        move = board.parse_san(san)
        board.push(move)
        ev = analysis[i] if i < len(analysis) else {}
        moves.append(dict(game_id=game['game_id'], ply=i + 1, color=color, player=game[color],
            uci=move.uci(), san=san, fen_before=before, fen_after=board.fen(),
            clock_seconds=clocks[i] / 100 if i < len(clocks) else None,
            # First moves are handled separately; mate/autodraw final move lacks increment.
            increment_applied=i >= 2 and not (i == len(sans) - 1 and len(clocks) == len(sans)),
            cp=ev.get('eval'), mate=ev.get('mate'), eval_source='lichess' if ev else None,
            api_best=ev.get('best')))
    boards.append(board.copy(stack=False))
    middle, end = division(boards)
    div = raw.get('division', {})
    game['middle_ply'], game['end_ply'] = div.get('middle', middle), div.get('end', end)
    game['end_ms'] = None
    game['end_upper_ms'], game['end_kind'] = observed_ms, 'observed_upper_bound'
    if board.is_game_over() and game['last_move_ms'] is not None:
        game['end_ms'] = game['last_move_ms']
        game['end_upper_ms'], game['end_kind'] = game['end_ms'] + 20, 'terminal_move'
    elif len(sans) >= 2 and len(clocks) == len(sans) + 1 and game['last_move_ms'] is not None:
        # Stopped active clock: GameExt.finish + ClockHistory.bothClockStates.
        elapsed_ms = max(0, (clocks[-3] - clocks[-1]) * 10)
        game['end_ms'] = game['last_move_ms'] + elapsed_ms
        game['end_upper_ms'], game['end_kind'] = game['end_ms'] + 1000, 'stopped_clock_estimate'
    return game, moves


def pgn_game(pgn, observed_ms=None):
    h = pgn.headers
    if pgn.errors:
        raise ValueError(f'Invalid PGN: {pgn.errors[0]}')
    if h.get('Variant', 'Standard') not in ('Standard', 'From Position') or pgn.board().chess960:
        raise ValueError('Only standard chess is supported')
    site = h.get('Site', '')
    import re
    match = re.fullmatch(r'https?://lichess.org/(?:game/)?([A-Za-z0-9]{8})(?:/(?:white|black))?', site)
    game_id = h.get('GameId') or (match[1] if match else hashlib.sha256(str(pgn).encode()).hexdigest()[:16])
    tc = h.get('TimeControl', '')
    initial = increment = None
    if re.fullmatch(r'\d+\+\d+', tc):
        initial, increment = map(int, tc.split('+'))
    board = pgn.board()
    initial_fen = board.fen()
    moves, boards = [], []
    nodes = list(pgn.mainline())
    for i, node in enumerate(nodes):
        before, color = board.fen(), 'white' if board.turn else 'black'
        boards.append(board.copy(stack=False))
        san = board.san(node.move)
        board.push(node.move)
        ev = node.eval()
        score = ev.white() if ev is not None else None
        terminal = i == len(nodes) - 1 and board.is_game_over()
        ambiguous_draw = (i == len(nodes) - 1 and h.get('Result') == '1/2-1/2' and not terminal
                          and (board.is_repetition(3) or board.halfmove_clock >= 100))
        moves.append(dict(game_id=game_id, ply=i + 1, color=color,
            player=h.get(color.title(), '?').lower(), uci=node.move.uci(), san=san,
            fen_before=before, fen_after=board.fen(), clock_seconds=node.clock(),
            # PGN lacks the extra stopped clock: claim-draw vs automatic end may be ambiguous.
            increment_applied=None if ambiguous_draw else i >= 2 and not terminal,
            cp=score.score() if score is not None else None,
            mate=score.mate() if score is not None else None,
            eval_source='lichess_dump' if score is not None else None, api_best=None))
    boards.append(board.copy(stack=False))
    middle, end = division(boards)
    end_ms = _stamp(h.get('EndDate') or h.get('UTCEndDate'), h.get('EndTime') or h.get('UTCEndTime'))
    start = _stamp(h.get('UTCDate'), h.get('UTCTime'))
    rating = lambda key: int(h[key]) if h.get(key, '').isdigit() else None
    result = h.get('Result', '*')
    game = dict(game_id=game_id, source='dump', rated='rated' in h.get('Event', '').lower(),
        white=h.get('White', '?').lower(), black=h.get('Black', '?').lower(),
        white_rating=rating('WhiteElo'), black_rating=rating('BlackElo'),
        white_berserk=False, black_berserk=False,
        initial_seconds=initial, increment_seconds=increment,
        speed=speed(initial, increment) if initial is not None else 'correspondence',
        start_ms=start, last_move_ms=None, end_ms=end_ms,
        end_upper_ms=end_ms + 1000 if end_ms is not None else None,
        end_kind='pgn_end_header' if end_ms is not None else 'unknown',
        observed_ms=observed_ms or int(time.time() * 1000),
        status=h.get('Termination', 'unknown'), result=result,
        winner='white' if result == '1-0' else 'black' if result == '0-1' else None,
        initial_fen=initial_fen, middle_ply=middle, end_ply=end, plies=len(moves))
    return game, moves
