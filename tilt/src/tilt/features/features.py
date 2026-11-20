"""Deterministic retrospective features. No human or synthetic labels live here."""
from bisect import bisect_left, bisect_right
from collections import defaultdict, deque, OrderedDict
from fractions import Fraction
from functools import lru_cache
import heapq
import hashlib
import json
import math
from pathlib import Path
import statistics

import chess
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ..data import storage
from ..core.engine import load_cache
from ..core.formulas import as_cp, chances, game_accuracy, judgement, move_accuracy, win_percent

PIECE_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
MOVE_BASELINES = {'cpl': 1.0, 'think_seconds': .1, 'accuracy': 1.0, 'risk': .05, 'wc_loss': .01}
GAME_BASELINES = {'mean_cpl': 1.0, 'cpl_std': 1.0, 'mean_think': .1, 'think_std': .1,
    'mean_accuracy': 1.0, 'error_rate': .01, 'blunder_rate': .01, 'risk_rate': .05,
    'attack_rate': .05, 'style_switch_rate': .05, 'post_event_cpl_delta': 1.0,
    'post_event_think_delta': .1, 'recovery_plies': 1.0, 'rest_gap_seconds': 1.0,
    'immediate_after_loss': .05}

_LEGAL_COUNTS = OrderedDict()
_POSITION_FEATURES = OrderedDict()


def legal_count(fen, board):
    """Bounded position-only memo; legal moves do not depend on game history."""
    count = _LEGAL_COUNTS.get(fen)
    if count is None:
        count = board.legal_moves.count()
        if len(_LEGAL_COUNTS) >= 4096:
            _LEGAL_COUNTS.popitem(last=False)
        _LEGAL_COUNTS[fen] = count
    else:
        _LEGAL_COUNTS.move_to_end(fen)
    return count


def valid(x):
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def mean(values):
    # Inline the same valid predicate on this hot aggregation path.
    vals = [x for x in values if x is not None and not (isinstance(x, float) and math.isnan(x))]
    if not vals:
        return None
    return _mean_values(tuple(vals)) if len(vals) <= 128 else _mean_values.__wrapped__(tuple(vals))


@lru_cache(maxsize=4096)
def _mean_values(vals):
    if all(isinstance(x, int) for x in vals):
        return sum(vals) / len(vals)
    return statistics.mean(vals)


def std(values):
    vals = [x for x in values if x is not None and not (isinstance(x, float) and math.isnan(x))]
    if not vals:
        return None
    return _std_values(tuple(vals)) if len(vals) <= 128 else statistics.pstdev(vals)


@lru_cache(maxsize=4096)
def _std_values(vals):
    return statistics.pstdev(vals)


def diff(a, b):
    return a - b if valid(a) and valid(b) else None


def material(board, color):
    return sum(v * (board.pieces_mask(p, color).bit_count() - board.pieces_mask(p, not color).bit_count())
               for p, v in PIECE_VALUES.items())


def position_features(fen, uci, before, after, move, color):
    """Cache only immutable board geometry, never evals, clocks or history."""
    key = (fen, uci)
    cached = _POSITION_FEATURES.get(key)
    if cached is not None:
        _POSITION_FEATURES.move_to_end(key)
        return cached
    captured, check = before.is_capture(move), after.is_check()
    moved = after.piece_at(move.to_square)
    square = move.to_square
    attackers = list(after.attackers(not color, square))
    exposed = bool(moved and moved.piece_type != chess.KING and attackers and (
        not after.is_attacked_by(color, square) or any(PIECE_VALUES[after.piece_type_at(s)] < PIECE_VALUES[moved.piece_type] for s in attackers)))
    offered = PIECE_VALUES[moved.piece_type] if exposed else 0
    king = after.king(not color)
    king_pressure = bool(king is not None and moved and any(chess.square_distance(s, king) <= 1 for s in after.attacks(square)))
    result = (captured, check, int(exposed), offered, int(captured or check or king_pressure),
              material(before, color), material(after, color), int(before.is_check()))
    if len(_POSITION_FEATURES) >= 4096:
        _POSITION_FEATURES.popitem(last=False)
    _POSITION_FEATURES[key] = result
    return result


def _score(cp, mate, board):
    # API mate=0 means side to move is checkmated, not necessarily White.
    if board.is_checkmate():
        return (1000 if board.turn == chess.BLACK else -1000), None
    return cp, mate


def move_features(game, moves, cache):
    result, previous = [], {}
    scores = []
    for i, row in enumerate(moves):
        before = after if i else chess.Board(row['fen_before'])
        move = chess.Move.from_uci(row['uci'])
        after = before.copy(stack=False)
        after.push(move)
        legal_moves = legal_count(row['fen_before'], before)
        color, sign, player = before.turn, 1 if before.turn else -1, row['player']
        cached_before, cached_after = cache.get(row['fen_before'], {}), cache.get(row['fen_after'], {})
        if i:
            prev = moves[i - 1]
            bcp, bmate = _score(prev['cp'], prev['mate'], before)
            before_source = prev['eval_source']
        else:
            bcp, bmate, before_source = None, None, None
        if bcp is None and bmate is None:
            bcp, bmate = cached_before.get('cp'), cached_before.get('mate')
            before_source = 'stockfish_cache' if cached_before else None
        if i == 0 and bcp is None and bmate is None and game['initial_fen'] == chess.STARTING_FEN:
            # lila/modules/tree/src/main/eval.scala legacyInitial, explicit provenance.
            bcp, before_source = 15, 'lichess_legacy_initial'
        acp, amate = _score(row['cp'], row['mate'], after)
        after_source = 'terminal_board' if after.is_checkmate() else row['eval_source']
        if acp is None and amate is None:
            acp, amate = cached_after.get('cp'), cached_after.get('mate')
            after_source = 'stockfish_cache' if cached_after else None
        if i == 0:
            scores.append((bcp, bmate))
        scores.append((acp, amate))
        bwin, awin = chances(bcp, bmate), chances(acp, amate)
        wp_before, wp_after = win_percent(bcp, bmate), win_percent(acp, amate)
        if sign == -1:
            bwin, awin = (-bwin if bwin is not None else None), (-awin if awin is not None else None)
            wp_before, wp_after = (100 - wp_before if wp_before is not None else None), (100 - wp_after if wp_after is not None else None)
        cpl = diff(as_cp(bcp, bmate), as_cp(acp, amate))
        cpl = min(1000, max(0, sign * cpl)) if cpl is not None else None
        wc_loss = max(0, bwin - awin) if bwin is not None and awin is not None else None
        rating, opp = game[f"{row['color']}_rating"], 'black' if color else 'white'
        first = previous.get(player or row['color'])
        increment = game['increment_seconds']
        observed_initial = first['observed_initial_seconds'] if first else row['clock_seconds']
        clock_mismatch = (observed_initial is not None and game['initial_seconds'] is not None and
                          abs(observed_initial - game['initial_seconds']) > max(.2, .05 * game['initial_seconds']))
        if game[f"{row['color']}_berserk"]:
            increment = 0
        elif clock_mismatch and increment not in (None, 0):
            # API exports can omit berserk flags. Do not infer spent time from a wrong increment.
            increment = None
        unclocked = first is None
        think, anomaly = None, False
        if (first is not None and row['clock_seconds'] is not None and first['clock_seconds'] is not None
                and increment is not None and row['increment_applied'] is not None):
            think = first['clock_seconds'] - row['clock_seconds'] + (increment if row['increment_applied'] else 0)
            anomaly = think < -.1
            think = None if anomaly else max(0, think)
        remaining_before = first['clock_seconds'] if first else observed_initial
        fraction = remaining_before / observed_initial if remaining_before is not None and observed_initial and observed_initial > 0 else None
        pressure = 'low' if fraction is not None and fraction < .2 else 'normal' if fraction is not None else 'unknown'
        advantage = 'winning' if bwin is not None and bwin >= .3524 else 'losing' if bwin is not None and bwin <= -.3524 else 'equal' if bwin is not None else 'unknown'
        cp_pre, cp_post = as_cp(bcp, bmate), as_cp(acp, amate)
        j = judgement(bcp, bmate, acp, amate, sign)
        if after.is_checkmate():
            j = 'good'
        captured, check, risk, offered, attack, material_before, material_after, defensive = position_features(
            row['fen_before'], row['uci'], before, after, move, color)
        prev_material = first['material_after'] if first else None
        gap = diff(as_cp(cached_before.get('cp'), cached_before.get('mate')),
                   as_cp(cached_before.get('second_cp'), cached_before.get('second_mate')))
        best = cached_before.get('best_move') or row['api_best']
        current = dict(game_id=game['game_id'], player=player, opponent=game[opp], color=row['color'],
            ply=row['ply'], uci=row['uci'], speed=game['speed'], start_ms=game['start_ms'],
            end_upper_ms=game['end_upper_ms'], rating=rating, opponent_rating=game[f'{opp}_rating'],
            rating_difference=diff(rating, game[f'{opp}_rating']),
            clock_seconds=row['clock_seconds'], remaining_before_seconds=remaining_before,
            observed_initial_seconds=observed_initial, think_seconds=think,
            unclocked_first_move=unclocked, clock_anomaly=anomaly, clock_config_mismatch=clock_mismatch,
            clock_fraction=fraction, clock_pressure=pressure,
            eval_before_cp=sign * bcp if bcp is not None else None,
            eval_before_mate=sign * bmate if bmate is not None else None,
            eval_after_cp=sign * acp if acp is not None else None,
            eval_after_mate=sign * amate if amate is not None else None,
            eval_before_source=before_source, eval_after_source=after_source,
            cpl=cpl, wc_loss=wc_loss, accuracy=move_accuracy(wp_before, wp_after), judgement=j,
            best_move=best, differs_from_best=(row['uci'] != best) if best else None,
            phase='endgame' if game['end_ply'] is not None and i >= game['end_ply'] else 'middlegame' if game['middle_ply'] is not None and i >= game['middle_ply'] else 'opening',
            material_balance=material_before, material_after=material_after,
            capture=captured, check=check, defensive=defensive,
            risk=risk, attack=attack, offered_material=offered,
            sacrifice_heuristic=(bool(offered and cpl >= 100) if cpl is not None else None),
            material_lost_since_turn=max(0, prev_material - material_before) if prev_material is not None else None,
            unsound_sacrifice_realized=(bool(material_before < prev_material and first['offered_material'] > 0 and first['cpl'] >= 100)
                if first and first['cpl'] is not None else None),
            unsound_attack=(bool(attack and cpl >= 100) if cpl is not None else None),
            style_switch=int(first['risk'] != risk) if first else 0,
            legal_moves=legal_moves, best_second_gap_cp=abs(gap) if gap is not None else None,
            think_per_legal_move=think / legal_moves if think is not None else None,
            advantage_state=advantage,
            just_blundered=j == 'blunder',
            just_lost_advantage=(bwin >= .3524 and awin < .3524) if bwin is not None and awin is not None else None,
            just_missed_win=(bwin >= .6 and awin < .3524) if bwin is not None and awin is not None else None,
            just_missed_mate=((bmate * sign > 0 and (amate is None or amate * sign <= 0) and not after.is_checkmate())
                if acp is not None or amate is not None else None) if bmate is not None else False,
            just_lost_material=(material_before < prev_material) if prev_material is not None else False,
            after_own_blunder=first['just_blundered'] if first else False,
            opponent_just_took_advantage=(advantage == 'losing' and first['post_advantage_state'] not in ('losing', 'unknown')) if first else False,
            post_advantage_state='winning' if awin is not None and awin >= .3524 else 'losing' if awin is not None and awin <= -.3524 else 'equal' if awin is not None else 'unknown')
        err = j in ('inaccuracy', 'mistake', 'blunder')
        current['consecutive_errors'] = ((first['consecutive_errors'] or 0) + 1 if first else 1) if err else (0 if j else None)
        if err and first and first['consecutive_errors'] is None:
            current['consecutive_errors'] = 1
        current['adverse_event'] = any(current[k] for k in ('just_blundered', 'just_lost_advantage', 'just_missed_win', 'just_missed_mate', 'just_lost_material', 'opponent_just_took_advantage'))
        previous[player or row['color']] = current
        result.append(current)
    return result, game_accuracy(scores, chess.Board(game['initial_fen']).turn)


def aggregate(rows):
    return dict(move_count=len(rows), mean_cpl=mean([r['cpl'] for r in rows]),
        cpl_std=std([r['cpl'] for r in rows]), mean_accuracy=mean([r['accuracy'] for r in rows]),
        accuracy_std=std([r['accuracy'] for r in rows]),
        mean_think=mean([r['think_seconds'] for r in rows]), think_std=std([r['think_seconds'] for r in rows]),
        mean_wc_loss=mean([r['wc_loss'] for r in rows]),
        error_rate=mean([int(r['judgement'] in ('inaccuracy', 'mistake', 'blunder')) for r in rows if r['judgement'] is not None]),
        mistake_rate=mean([int(r['judgement'] == 'mistake') for r in rows if r['judgement'] is not None]),
        blunder_rate=mean([int(r['judgement'] == 'blunder') for r in rows if r['judgement'] is not None]),
        risk_rate=mean([r['risk'] for r in rows]), attack_rate=mean([r['attack'] for r in rows]),
        defensive_rate=mean([r['defensive'] for r in rows]), sacrifice_rate=mean([r['sacrifice_heuristic'] for r in rows]),
        unsound_attack_rate=mean([r['unsound_attack'] for r in rows]),
        realized_sacrifice_rate=mean([r['unsound_sacrifice_realized'] for r in rows]),
        style_switch_rate=mean([r['style_switch'] for r in rows]),
        max_consecutive_errors=max((r['consecutive_errors'] for r in rows if r['consecutive_errors'] is not None), default=None),
        adverse_events=sum(r['adverse_event'] for r in rows),
        eval_missing_fraction=mean([r['cpl'] is None for r in rows]),
        # First turns have no prior own clock; zero-time/premove readings do
        # not provide a measurable think interval. Neither is missing telemetry.
        clock_missing_fraction=mean([not valid(r['think_seconds']) for r in rows
            if not r.get('unclocked_first_move', r.get('ply') in (1, 2))
            and r['think_seconds'] != 0]),
        tense_think_std=std([r['think_seconds'] for r in rows if r['advantage_state'] == 'equal']),
        mean_think_per_legal_move=mean([r['think_per_legal_move'] for r in rows]))


def baseline_stats(history, columns, min_games, game_key='game_id'):
    """Prepare once per game/context; scoring never scans historical moves."""
    out = {}
    for name, floor in columns.items():
        vals, ids = [], set()
        for row in history:
            value = row.get(name)
            if valid(value):
                vals.append(value)
                ids.add(row[game_key])
        out[name] = value_stats(vals, len(ids), floor, min_games)
    return out


def value_stats(vals, count, floor, min_games):
    vals = sorted(vals) if count >= min_games else []
    median = statistics.median(vals) if vals else None
    mad = statistics.median([abs(x - median) for x in vals]) if vals else None
    return count, median, mad, floor, vals


def move_history_stats(history, min_games):
    pooled, counts, latest = {}, {}, {}
    normal_values, normal_games = [], 0
    for game in history:
        normal_values.extend(game['_normal_values'])
        normal_games += bool(game['_normal_values'])
        for context, columns in game['_context_values'].items():
            if context not in pooled:
                pooled[context] = {name: [] for name in MOVE_BASELINES}
                counts[context] = dict.fromkeys(MOVE_BASELINES, 0)
            latest[context] = game['end_upper_ms']
            for name, vals in columns.items():
                pooled[context][name].extend(vals)
                counts[context][name] += bool(vals)
    prepared = {context: ({name: value_stats(vals, counts[context][name], MOVE_BASELINES[name], min_games)
                          for name, vals in columns.items()}, latest[context])
                for context, columns in pooled.items()}
    return prepared, normal_values, normal_games


def score_baseline(current, stats):
    scores, out = [], {}
    for name, (count, median, mad, floor, vals) in stats.items():
        value = current.get(name)
        scale = max(1.4826 * mad, floor) if mad is not None else None
        z = (value - median) / scale if median is not None and valid(value) else None
        out[f'baseline_{name}_games'] = count
        out[f'baseline_{name}_median'], out[f'baseline_{name}_mad'], out[f'deviation_{name}_z'] = median, mad, z
        fraction = None
        if z is not None:
            # Conservative bisect interval; preserve the original abs comparison
            # at floating-point boundaries without scanning all values per row.
            low = bisect_left(vals, math.nextafter(value - scale, -math.inf))
            high = bisect_right(vals, math.nextafter(value + scale, math.inf))
            if low < high and abs(vals[low] - value) > scale:
                low = bisect_right(vals, vals[low], lo=low, hi=high)
            if high > low and abs(vals[high - 1] - value) > scale:
                high = bisect_left(vals, vals[high - 1], lo=low, hi=high)
            fraction = (high - low) / len(vals)
        out[f'historical_{name}_similar_fraction'] = fraction
        if z is not None:
            scores.append(min(10, abs(z)))
    out['behavioral_deviation_score'] = mean(scores) * 10 if scores else None
    out['deviation_feature_count'] = len(scores)
    return out


def robust(current, history, columns, min_games, game_key='game_id'):
    """Every caller supplies only games with end_upper_ms < current.start_ms."""
    return score_baseline(current, baseline_stats(history, columns, min_games, game_key))


class PriorHistory:
    """Sweep by start, activate by strict end, retain K games per speed.

    Uncapped cross-game counters preserve their original semantics without
    rescanning old games. Only capped history retains historical move-value pools.
    """
    def __init__(self, cap):
        self.pending = []
        self.by_speed = defaultdict(lambda: deque(maxlen=cap))
        self.recent = deque(maxlen=5)
        self.count = self.losses = self.rematches = 0
        self.last_opponent = self.last = None
        self.started = defaultdict(int)
        self.session_risk = defaultdict(lambda: [Fraction(0), 0])

    def before(self, start):
        while start is not None and self.pending and self.pending[0][0] < start:
            _, _, game = heapq.heappop(self.pending)
            self.by_speed[game['speed']].append(game)
            self.recent.append(game)
            self.count += 1
            self.losses = self.losses + 1 if game['result_score'] == 0 else 0
            self.rematches = self.rematches + 1 if game['opponent'] == self.last_opponent else 1
            self.last_opponent = game['opponent']
            total = self.session_risk[game['session_id']]
            if valid(game['risk_rate']):
                total[0] += Fraction(game['risk_rate'])
                total[1] += 1

    def add(self, summary, moves):
        self.last = summary
        self.started[summary['session_id']] += 1
        if summary['end_upper_ms'] is not None:
            contexts = {}
            for row in moves:
                context = contexts.setdefault((row['clock_pressure'], row['advantage_state']), {name: [] for name in MOVE_BASELINES})
                for name in MOVE_BASELINES:
                    if valid(row[name]):
                        context[name].append(row[name])
            heapq.heappush(self.pending, (summary['end_upper_ms'], summary['game_id'],
                {**summary, '_context_values': contexts, '_normal_values': [r['cpl'] for r in moves if valid(r['cpl'])]}))


def windows_and_events(rows, window, normal_cpl=None):
    windows, events = [], []
    for row in rows:
        current = [r for r in rows if row['ply'] - window < r['ply'] <= row['ply']]
        windows.append(dict(game_id=row['game_id'], player=row['player'], start_ply=max(1, row['ply'] - window + 1),
            end_ply=row['ply'], available_after_ply=row['ply'], **aggregate(current)))
        if not row['adverse_event']:
            continue
        anchors = [(row['ply'], ('just_blundered', 'just_lost_advantage', 'just_missed_win', 'just_missed_mate')),
                   (row['ply'] - 1, ('just_lost_material', 'opponent_just_took_advantage'))]
        for anchor, types in anchors:
            types = [key for key in types if row[key]]
            if not types:
                continue
            # Opponent events happened on the previous ply: include the first response.
            pre = [r for r in rows if anchor - window <= r['ply'] < anchor]
            post = [r for r in rows if anchor < r['ply'] <= anchor + window]
            a, b = aggregate(pre), aggregate(post)
            recovery = None
            if normal_cpl is not None:
                following = [r for r in rows if r['ply'] > anchor]
                for left, right in zip(following, following[1:]):
                    if left['cpl'] is not None and right['cpl'] is not None and max(left['cpl'], right['cpl']) <= normal_cpl:
                        recovery = right['ply'] - anchor
                        break
            events.append(dict(game_id=row['game_id'], player=row['player'], event_ply=anchor,
                event_types=','.join(types),
                available_after_ply=rows[-1]['ply'] if recovery is not None else min(anchor + window, rows[-1]['ply']),
                pre_count=len(pre), post_count=len(post), pre_mean_cpl=a['mean_cpl'], post_mean_cpl=b['mean_cpl'],
                post_event_cpl_delta=diff(b['mean_cpl'], a['mean_cpl']),
                pre_mean_think=a['mean_think'], post_mean_think=b['mean_think'],
                post_event_think_delta=diff(b['mean_think'], a['mean_think']), recovery_plies=recovery,
                recovery_censored=recovery is None, recovery_baseline_missing=normal_cpl is None,
                continued_error_rate=b['error_rate']))
    return windows, events


def feature_frame(records):
    # Explicit logical types keep earlier rows/schema stable when a later game fills a null column.
    strings = {'player', 'opponent', 'game_id', 'color', 'uci', 'speed', 'clock_pressure',
        'eval_before_source', 'eval_after_source', 'judgement', 'best_move', 'phase',
        'advantage_state', 'post_advantage_state', 'session_id', 'event_types', 'end_kind',
        'previous_game_id', 'game_ids', 'session_gap_basis'}
    booleans = {'capture', 'check', 'unclocked_first_move', 'clock_anomaly', 'clock_config_mismatch',
        'differs_from_best', 'sacrifice_heuristic', 'unsound_attack', 'unsound_sacrifice_realized', 'just_blundered',
        'just_lost_advantage', 'just_missed_win', 'just_missed_mate', 'just_lost_material',
        'after_own_blunder', 'opponent_just_took_advantage', 'adverse_event',
        'recovery_censored', 'recovery_baseline_missing'}
    frame = pd.DataFrame(records) if records else pd.DataFrame({'player': pd.Series(dtype='string')})
    for col in frame:
        if col in strings:
            frame[col] = frame[col].astype('string')
        elif col in booleans:
            frame[col] = frame[col].astype('boolean')
        elif col.endswith(('_ms', '_ply', '_games', '_count')) or col in {'ply', 'game_count', 'consecutive_errors', 'max_consecutive_errors', 'available_after_ply', 'pre_count', 'post_count'}:
            frame[col] = pd.to_numeric(frame[col]).astype('Int64')
        else:
            frame[col] = pd.to_numeric(frame[col]).astype('float64')
    return frame


class FrameSink:
    """Stream per-move rows into one Parquet file in bounded chunks.

    feature_frame picks dtypes from column names, so every chunk gets the same schema.
    """
    def __init__(self, path, chunk_rows=50000):
        self.path, self.chunk_rows = Path(path), chunk_rows
        self.temp = self.path.with_suffix('.tmp')
        self.rows, self.writer, self.count = [], None, 0

    def extend(self, rows):
        self.rows.extend(rows)
        if len(self.rows) >= self.chunk_rows:
            self.flush()

    def flush(self):
        if not self.rows:
            return
        table = pa.Table.from_pandas(feature_frame(self.rows), preserve_index=False)
        if self.writer is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.writer = pq.ParquetWriter(self.temp, table.schema, compression='zstd')
        else:
            if set(table.schema.names) != set(self.writer.schema.names):
                raise ValueError(f'Inconsistent feature columns for {self.path.name}')
            table = table.select(self.writer.schema.names).cast(self.writer.schema)
        self.writer.write_table(table)
        self.count += len(self.rows)
        self.rows = []

    def close(self):
        self.flush()
        if self.writer is None:
            storage.write_frame(self.path, feature_frame([]))
        else:
            self.writer.close()
            self.temp.replace(self.path)
        return self.count


def compute(data, window=12, min_prior_games=5, session_gap_minutes=30, max_history_games=200):
    if window < 1 or min_prior_games < 1 or session_gap_minutes < 1 or max_history_games < 1:
        raise ValueError('Window, minimum history, session gap and maximum history must be positive')
    games = storage.records(storage.read(data, 'games'))
    normalized = storage.read(data, 'moves')
    grouped = {gid: storage.records(group.sort_values('ply')) for gid, group in normalized.groupby('game_id')}
    del normalized
    cache, settings = load_cache(data, fields=('cp', 'mate', 'second_cp', 'second_mate', 'best_move'))
    output = Path(data) / 'processed' / 'features'
    # Per-move tables are streamed to disk; only game summaries stay in memory.
    sinks = {name: FrameSink(output / f'{name}.parquet') for name in ('moves', 'windows', 'events')}
    all_moves, all_windows, all_events = sinks['moves'], sinks['windows'], sinks['events']
    all_games = []
    histories = {}
    for game in sorted(games, key=lambda g: (g['start_ms'] is None, g['start_ms'] or 0, g['game_id'])):
        rows, accuracies = move_features(game, grouped.pop(game['game_id'], []), cache)
        for color in ('white', 'black'):
            player = game[color]
            if not player or player == '?':
                continue
            own = [r for r in rows if r['color'] == color]
            if not own:
                continue
            history = histories.setdefault(player, PriorHistory(max_history_games))
            history.before(game['start_ms'])
            similar = list(history.by_speed[game['speed']]) if game['start_ms'] is not None else []
            prepared, normal_values, normal_games = move_history_stats(similar, min_prior_games)
            empty_stats = baseline_stats([], MOVE_BASELINES, min_prior_games)
            for row in own:
                stats, latest = prepared.get((row['clock_pressure'], row['advantage_state']), (empty_stats, None))
                row.update(score_baseline(row, stats))
                row['baseline_latest_end_ms'] = latest
            normal_cpl = None
            if normal_games >= min_prior_games and normal_values:
                med = statistics.median(normal_values)
                normal_cpl = med + max(1, 1.4826 * statistics.median(abs(x - med) for x in normal_values))
            windows, events = windows_and_events(own, window, normal_cpl)
            ordered = list(history.recent) if game['start_ms'] is not None else []
            prev = ordered[-1] if ordered else None
            streak = history.losses if ordered else 0
            rematch_streak = history.rematches if ordered and own[0]['opponent'] is not None and history.last_opponent == own[0]['opponent'] else 0
            gap = (game['start_ms'] - prev['end_ms']) / 1000 if prev and prev['end_ms'] is not None else None
            session_prev = history.last
            session_anchor = (session_prev['end_ms'] if session_prev and session_prev['end_ms'] is not None else session_prev['start_ms'] if session_prev else None)
            session_basis = 'end_time' if session_prev and session_prev['end_ms'] is not None else 'start_gap_proxy'
            new_session = session_anchor is None or game['start_ms'] is None or (game['start_ms'] - session_anchor) > session_gap_minutes * 60000
            session_id = hashlib.sha256(f'{player}:{game["game_id"]}'.encode()).hexdigest()[:20] if new_session else session_prev['session_id']
            risk_sum, risk_count = history.session_risk[session_id] if ordered else (0, 0)
            prior_session_risk = float(risk_sum / risk_count) if risk_count else None
            summary = dict(game_id=game['game_id'], player=player, opponent=own[0]['opponent'], color=color,
                start_ms=game['start_ms'], end_ms=game['end_ms'], end_upper_ms=game['end_upper_ms'],
                end_kind=game['end_kind'], speed=game['speed'], rating=own[0]['rating'],
                opponent_rating=own[0]['opponent_rating'], rating_difference=own[0]['rating_difference'],
                result_score=1.0 if game['winner'] == color else 0.0 if game['winner'] else .5 if game['result'] == '1/2-1/2' else None,
                session_id=session_id, session_gap_basis=session_basis, games_in_session_before=history.started[session_id], losing_streak_before=streak,
                rest_gap_seconds=gap, immediate_after_loss=int(prev['result_score'] == 0 and gap <= 60)
                    if prev and gap is not None and prev['result_score'] is not None else None,
                rematch=int(prev['opponent'] == own[0]['opponent'])
                    if prev and prev['opponent'] is not None and own[0]['opponent'] is not None else 0 if not prev else None,
                rematch_streak_before=rematch_streak,
                recent_form=mean([p['result_score'] for p in ordered[-5:]]),
                previous_game_id=prev['game_id'] if prev else None,
                history_games=history.count if ordered else 0, baseline_speed_games=len(similar),
                baseline_latest_end_ms=max((p['end_upper_ms'] for p in similar), default=None),
                game_accuracy=accuracies[color], **aggregate(own))
            for phase in ('opening', 'middlegame', 'endgame'):
                subset = [r for r in own if r['phase'] == phase]
                summary[f'{phase}_accuracy'] = mean([r['accuracy'] for r in subset])
                summary[f'{phase}_think'] = mean([r['think_seconds'] for r in subset])
            summary['phase_accuracy_change'] = diff(summary['endgame_accuracy'], summary['opening_accuracy'])
            summary['phase_speed_change'] = diff(summary['endgame_think'], summary['opening_think'])
            for name in ('post_event_cpl_delta', 'post_event_think_delta', 'recovery_plies'):
                summary[name] = mean([r[name] for r in events])
            summary['cpl_change_after_loss'] = diff(summary['mean_cpl'], prev['mean_cpl']) if prev and prev['result_score'] == 0 else None
            summary['style_drift_in_session'] = diff(summary['risk_rate'], prior_session_risk)
            summary['cpl_volatility_after_losses'] = std([h['mean_cpl'] for h in ordered[-5:]]) if streak >= 2 else None
            summary.update(robust(summary, similar, GAME_BASELINES, min_prior_games))
            for row in own:
                row['session_id'] = session_id
            for row in windows + events:
                row['session_id'] = session_id
            all_moves.extend(own)
            all_windows.extend(windows)
            all_events.extend(events)
            all_games.append(summary)
            history.add(summary, own)
    sessions = []
    for (player, session_id), subset in pd.DataFrame(all_games).groupby(['player', 'session_id']) if all_games else []:
        entries = storage.records(subset)
        sessions.append(dict(player=player, session_id=session_id,
            game_ids=json.dumps(sorted(subset.game_id.tolist())),
            start_ms=min((g['start_ms'] for g in entries if g['start_ms'] is not None), default=None),
            end_upper_ms=max(g['end_upper_ms'] for g in entries) if all(g['end_upper_ms'] is not None for g in entries) else None,
            game_count=len(entries), mean_cpl=mean([g['mean_cpl'] for g in entries]),
            mean_think=mean([g['mean_think'] for g in entries]), mean_accuracy=mean([g['mean_accuracy'] for g in entries]),
            risk_rate=mean([g['risk_rate'] for g in entries]),
            cpl_volatility=std([g['mean_cpl'] for g in entries]),
            behavioral_deviation_score=mean([g['behavioral_deviation_score'] for g in entries])))
    counts = {name: sink.close() for name, sink in sinks.items()}
    for name, records in {'games': all_games, 'sessions': sessions}.items():
        storage.write_frame(output / f'{name}.parquet', feature_frame(records))
        counts[name] = len(records)
    (output / 'manifest.json').write_text(json.dumps(dict(window_plies=window, min_prior_games=min_prior_games,
        session_gap_minutes=session_gap_minutes, max_history_games=max_history_games, engine=settings,
        baseline_rule='end_upper_ms < current.start_ms; same speed; move baselines also pressure+advantage',
        deviation_score='10 * mean(min(10, abs(z))) over available features; z=(x-median)/max(1.4826*MAD,unit_floor)',
        version=1), indent=2))
    return {name: counts[name] for name in ('moves', 'games', 'windows', 'events', 'sessions')}
