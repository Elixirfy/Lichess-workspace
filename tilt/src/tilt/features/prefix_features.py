"""S3 prefix features and portable, separate build steps; no training on labels.

Only player-sized move tables are read. Process workers have independent read-only
sources; the parent writes output in fixed player order. No engine is started.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
import hashlib
import json
import multiprocessing
from pathlib import Path
import resource
import time

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ..labels import tilt_rules as rules
from ..labels import dev_split as split
from ..common.formulas import win_percent
from ..service.score import dynamics

IDS = split.KEYS
HISTORY = ('rematch_streak_before', 'losing_streak_before', 'rest_gap_seconds', 'recent_form')
LEVEL = {'none': 0., 'stale': 1., 'weak': 2., 'strong': 3.}
STATE = {'not_fired': 0., 'fired': 1., 'missing': np.nan}
LABEL = {'NOT': 0., 'TILT': 1., 'ABSTAIN': 2.}
STATUS = {s: float(i) for i, s in enumerate(('mate', 'resign', 'outoftime', 'timeout', 'draw',
    'stalemate', 'variantEnd', 'cheat', 'noStart', 'aborted', 'unknownFinish'))}
FLOORS = dict(rules.DESIGN.floors)
PZ = ('cpl_mean_w300', 'think_frac_median', 'think_cv', 'risk_rate', 'attack_rate', 'sacrifice_rate')
B = ('attack_trend_3w', 'risk_volatility_3w', 'behavior_change_point')
X5 = ('cpl_mean_w300', 'blunders_per20', 'think_frac_median', 'think_cv', 'aggression_score')
Z5 = ('z_cpl_mean_w300', 'z_blunders_per20', 'z_think_frac_median', 'z_think_cv', 'aggression_score')
MOVE_COLS = ['player', 'game_id', 'color', 'ply', 'cpl', 'judgement', 'think_seconds', 'risk',
    'attack', 'defensive', 'style_switch', 'sacrifice_heuristic', 'eval_after_cp',
    'eval_after_mate', 'clock_seconds', 'material_after', 'legal_moves', 'phase']
DROP_INCOMPLETE = 'drop_incomplete_moves'
E4_EXPECTED = dict(train=20, V_A=9, V_B=5)
EXCLUSION_COLS = IDS + ['part', 'plies', 'color_present', 'status']


def prefix_status(game, moves):
    """Frozen E4 rule, also for S5 holdouts; inspect only physical plies 1..20."""
    if game['plies'] < 20:
        return 'short'
    m = moves[moves.game_id.eq(game['raw_game_id']) & moves.ply.between(1, 20)].sort_values('ply')
    plies = m.ply.tolist()
    if plies == list(range(1, 21)):
        return 'complete'
    for first, colour in ((1, 'white'), (2, 'black')):
        if plies == list(range(first, 21, 2)) and m.color.eq(colour).all():
            return DROP_INCOMPLETE
    raise ValueError('P-20 must have exactly physical plies 1..20 (unhandled incomplete pattern)')


def incomplete_targets(targets, inventory):
    """Derive status outside the immutable manifest; keys are existing pseudonyms."""
    rows = targets.merge(inventory[IDS + ['color_present', 'status']], on=IDS,
                         suffixes=('_game', ''), validate='one_to_one')
    return rows.loc[rows.status.eq(DROP_INCOMPLETE), EXCLUSION_COLS].copy()


def check_incomplete_count(exclusions, expected=None):
    expected = E4_EXPECTED if expected is None else expected
    counts = {part: int(exclusions.part.eq(part).sum()) for part in expected}
    if counts != expected or len(exclusions) != sum(expected.values()):
        raise ValueError('Erratum 4 incomplete-target count stop: ' + json.dumps(counts, sort_keys=True))
    return counts


def check_own_colour(inventory, labels):
    """Never change a label to hide missing own moves; ABSTAIN alone is permitted."""
    missing = inventory[inventory.color_present.notna() & inventory.color.ne(inventory.color_present)]
    if missing.empty:
        return
    keys = IDS if 'cohort' in labels else [c for c in IDS if c != 'cohort']
    joined = missing[keys].merge(labels[keys + ['label']], on=keys, validate='one_to_one')
    if joined.label.isin(['TILT', 'NOT']).any():
        raise ValueError('Erratum 4 own-colour stop: missing own moves on a TILT/NOT game')


def move_inventory(headers, moves):
    """Counts-only projection: no eval, clock, behaviour, label or score is read."""
    prefix = moves[moves.ply.between(1, 20)].copy()
    prefix['bit'] = np.left_shift(1, prefix.ply.to_numpy(dtype=np.int64) - 1)
    summary = prefix.groupby('game_id').agg(prefix_count=('ply', 'size'),
        prefix_unique=('ply', 'nunique'), prefix_bits=('bit', 'sum'),
        prefix_colours=('color', 'nunique'), prefix_colour=('color', 'first'))
    all_colours = moves.groupby('game_id').color.agg(['nunique', 'first']).rename(
        columns={'nunique': 'all_colours', 'first': 'color_present'})
    rows = headers.merge(summary, left_on='raw_game_id', right_index=True, how='left', validate='many_to_one')
    rows = rows.merge(all_colours, left_on='raw_game_id', right_index=True, how='left', validate='many_to_one')
    complete = rows.prefix_count.eq(20) & rows.prefix_unique.eq(20) & rows.prefix_bits.eq((1 << 20) - 1)
    incomplete = rows.prefix_count.eq(10) & rows.prefix_unique.eq(10) & rows.prefix_colours.eq(1) & (
        (rows.prefix_bits.eq(sum(1 << i for i in range(0, 20, 2))) & rows.prefix_colour.eq('white')) |
        (rows.prefix_bits.eq(sum(1 << i for i in range(1, 20, 2))) & rows.prefix_colour.eq('black')))
    if (rows.plies.ge(20) & ~(complete | incomplete)).any():
        raise ValueError('P-20 must have exactly physical plies 1..20 (unhandled incomplete pattern)')
    if (rows.plies.ge(20) & incomplete & rows.all_colours.ne(1)).any():
        raise ValueError('Erratum 4 unhandled mixed-colour incomplete game')
    rows['status'] = np.where(rows.plies.lt(20), 'short', np.where(incomplete, DROP_INCOMPLETE, 'complete'))
    return rows.loc[rows.all_colours.eq(1), IDS + ['plies', 'color_present', 'status']].copy()


def audit_incomplete(args, headers):
    """E4 permits only these holdout move-presence counts in S3."""
    inventories = []
    for cohort, root in [('old', args.old_root), ('new', args.new_root)]:
        own = headers[headers.cohort.eq(cohort)]
        if own.empty:
            continue
        moves = pd.read_parquet(Path(root) / 'features/moves.parquet', columns=['game_id', 'ply', 'color'],
            filters=[('game_id', 'in', own.raw_game_id.unique().tolist())])
        inventories.append(move_inventory(own, moves))
    inventory = pd.concat(inventories, ignore_index=True)
    exclusions = incomplete_targets(headers[headers.part.isin(split.PARTS)], inventory)
    counts = check_incomplete_count(exclusions)
    result = dict(development_excluded=counts, cohorts={})
    for cohort, group in inventory.groupby('cohort'):
        result['cohorts'][cohort] = dict(one_colour_games=group.game_id.nunique(), one_colour_sides=len(group),
            plies_lt20=int(group.plies.lt(20).sum()), plies_ge20=int(group.plies.ge(20).sum()),
            own_colour_present=int(group.color.eq(group.color_present).sum()),
            own_colour_missing=int(group.color.ne(group.color_present).sum()))
    hold = headers[headers.assignment.isin(['A_prime', 'B_prime'])].merge(inventory, on=IDS, suffixes=('', '_inventory'))
    result['holdout_incomplete_counts'] = {part: int((hold.assignment.eq(part) & hold.status_inventory.eq(DROP_INCOMPLETE)).sum())
        for part in ('A_prime', 'B_prime')}
    # Check existing labels only where the diagnostic finds missing own moves.
    # No holdout labels are read or constructed.
    for path in [Path(args.s1) / f'labels_{n}_train.parquet' for n in ('by_player', 'by_time')] + [Path(args.out) / 'labels_dev.parquet']:
        if path.exists():
            labels = pd.read_parquet(path, columns=['game_id', 'color', 'player_id', 'label'])
            if 'cohort' not in labels:
                # S1 is old only; S3 keys remain unique across cohorts.
                labels = labels.merge(headers[IDS], on=['game_id', 'color', 'player_id'], validate='one_to_one')
            check_own_colour(inventory, labels)
    (Path(args.out) / 'incomplete_moves_audit.json').write_text(json.dumps(result, indent=2) + '\n')
    return inventory, exclusions, result


def registry(excluded=()):
    rows = []
    def add(name, block, family, source, minimum='one header', missing='null when unavailable'):
        rows.append(dict(column=name, block=block, family=family, source_fields=source,
                         minimum_data=minimum, missing_value_rule=missing))
    for name in ('initial_seconds', 'increment_seconds', 'rating', 'opponent_rating_delta', 'color_white'):
        source = {'opponent_rating_delta': 'header.opponent_rating;header.rating',
                  'color_white': 'header.color'}.get(name, 'header.' + name)
        add(name, 'pre', 'meta', source)
    for name in ('L', 'losses5', 'losses10', 'D', 'rating_delta', 'games_before', 'session_seconds',
                 'loss_seconds', 'gap0', 'gap1', 'gap2', 'C1', 'C2', 'C3', 'C4', 'C5', 'n_C',
                 'context_rank', 'prev_lost', 'prev_result'):
        add('ctx_' + name, 'pre', 'session',
            'available_session_history.result_score;available_session_history.rating;'
            'available_session_history.start_ms;available_session_history.end_ms;'
            'header.start_ms;header.rating;header.session_id',
            'S-prime(g); gaps require true ends')
    for name in HISTORY:
        if name not in excluded:
            add(name, 'pre', 'history', 'stored_prior_history.' + name, 'strict end cutoff verified')
    for name in X5:
        add('prev_x_' + name, 'pre', 'previous', 'prior_game.x.' + name, 'model previous game')
    for name in Z5:
        add('prev_' + name, 'pre', 'previous', 'prior_game.z.' + name, 'model previous game')
        add('session_mean_' + name, 'pre', 'session_behavior', 'available_prior_game.z.' + name,
            'last 3; mean of nonnull values, null if none')
    for name in (*rules.EVIDENCE, 'n_fired', 'plies', 'status', 'label'):
        add('prev_' + name, 'pre', 'previous', 'prior_game.' + name, 'model previous game',
            'null if absent; E missing=null; NOT/TILT/ABSTAIN=0/1/2; fixed status enum')
    for name in ('tilts10', 'evidence_mean10'):
        add('session_' + name, 'pre', 'session_behavior', 'available_prior_game.' + name, 'last 10')
    for name in rules.FEATURES:
        for stat in ('median', 'mad'):
            add('baseline_' + name + '_' + stat, 'pre', 'baseline', 'available_pooled_history.' + name,
                'last <=200 same speed; >=5 nonnull games')
    for name in ('baseline_games', 'baseline_risk_rate_games'):
        add(name, 'pre', 'baseline', 'available_pooled_history.count', 'last <=200 same speed')
    families = {
        'quality': ('cpl_mean_w300', 'cpl_max', 'inaccuracies', 'mistakes', 'blunders', 'opponent_cpl'),
        'time': ('think_frac_median', 'think_cv', 'think_max_frac', 'clock_used', 'first_think'),
        'style': ('risk_rate', 'attack_rate', 'defensive_rate', 'style_switch_rate', 'sacrifice_rate', *B),
        'position': ('win_percent', 'win_percent_min', 'material_balance', 'legal_moves_mean', 'phase'),
        'prefix_z': tuple('z_' + x for x in PZ) + ('aggression',)}
    for family, names in families.items():
        for name in names:
            source = ('cpl' if name in ('cpl_mean_w300', 'cpl_max', 'opponent_cpl', 'z_cpl_mean_w300') else
                'judgement' if name in ('inaccuracies', 'mistakes', 'blunders') else
                'think_seconds;header.initial_seconds;header.increment_seconds' if 'think' in name else
                'clock_seconds;header.initial_seconds' if name == 'clock_used' else
                'eval_after_cp;prefix_1_20.eval_after_mate;prefix_1_20.color' if name.startswith('win_percent') else
                'material_after;prefix_1_20.color' if name == 'material_balance' else
                'legal_moves' if name == 'legal_moves_mean' else 'phase' if name == 'phase' else
                'risk;prefix_1_20.attack;prefix_1_20.defensive;prefix_1_20.style_switch;prefix_1_20.sacrifice_heuristic')
            source = 'prefix_1_20.' + source
            if family == 'prefix_z':
                source += ';available_prefix_history.same_statistic;available_prefix_history.end_upper_ms'
            minimum = 'exactly 20 physical plies, 10 own'
            if name in ('think_frac_median', 'think_cv'):
                minimum += '; >=5 known own think times; positive budget/mean respectively'
            elif name == 'think_max_frac':
                minimum += '; >=1 known own think; positive budget'
            elif name == 'first_think':
                minimum += '; first own move think time'
            elif name == 'clock_used':
                minimum += '; tenth own clock; positive initial clock'
            elif name == 'win_percent':
                minimum += '; evaluation at physical ply 20'
            elif name == 'win_percent_min':
                minimum += '; >=1 evaluation in prefix'
            elif family == 'prefix_z':
                minimum += '; last <=200 available complete prior prefixes; >=5 nonnull statistics per component'
            add('p20_' + name, 'p20', family, source, minimum,
                'null stays null; flag rates/dynamics treat null flags as false; judgement counts ignore nulls')
    return pd.DataFrame(rows)


def model_matrix(frame, head, candidate='M-v3', excluded=()):
    reg = registry(excluded)
    if head not in ('pre', 'p20') or candidate not in ('M-v3', 'P3-B@20'):
        raise ValueError('Unknown head or candidate; whole-game comparators are outside S3')
    cols = reg.loc[reg.block.isin(['pre'] if head == 'pre' else ['pre', 'p20']), 'column'].tolist()
    if candidate == 'P3-B@20':
        selected = ['initial_seconds', 'increment_seconds', 'rematch_streak_before', 'baseline_risk_rate_games']
        if head == 'p20':
            selected += ['p20_' + x for x in ('risk_rate', 'attack_rate', 'defensive_rate', 'style_switch_rate', *B)]
        cols = [c for c in selected if c in cols]
    if not set(cols) <= set(frame.columns):
        raise ValueError('Missing registered feature columns')
    allowed = set(IDS + ['part'] + reg.column.tolist())
    if not set(frame.columns) <= allowed:
        raise ValueError('Unregistered fields in model feature table')
    return frame[cols].copy()


def targets_only(targets):
    if targets.empty or not targets.part.isin(split.PARTS).all():
        raise ValueError('Only target development rows are permitted')
    if 'assignment' in targets and not targets.assignment.eq('development').all():
        raise ValueError('Holdout/drop/history-only targets forbidden')
    if targets.duplicated(IDS).any():
        raise ValueError('Duplicate targets')


def mean(values):
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    return float(values.mean()) if len(values) else np.nan


def gap(current, previous):
    return (current['start_ms'] - previous['end_ms']) / 1000 if pd.notna(previous['end_ms']) else np.nan


def session_context(game, history):
    """Rebuild all context/gaps on S-prime, including gaps of its first two entries."""
    prior = history[history.player_id.eq(game['player_id']) & history.start_ms.lt(game['start_ms']) &
                    history.end_upper_ms.lt(game['start_ms']) & history.session_id.eq(game['session_id'])]
    entries = prior.sort_values(['start_ms', 'raw_game_id']).to_dict('records')
    for i, row in enumerate(entries):
        row['exact_gap'] = gap(row, entries[i - 1]) if i else np.nan
    current = dict(game, exact_gap=gap(game, entries[-1]) if entries else np.nan)
    reverse = entries[::-1]
    context = rules.context(current, reverse)
    values = dict(L=context['L'], losses5=sum(x['result_score'] == 0 for x in reverse[:5]),
        losses10=sum(x['result_score'] == 0 for x in reverse[:10]), D=context['D'],
        rating_delta=context['rating_delta'], games_before=len(entries),
        session_seconds=(game['start_ms'] - entries[0]['start_ms']) / 1000 if entries else 0.,
        loss_seconds=context['c5_recency_seconds'], gap0=current['exact_gap'],
        gap1=reverse[0]['exact_gap'] if reverse else np.nan,
        gap2=reverse[1]['exact_gap'] if len(reverse) > 1 else np.nan,
        **{c: float(context[c]) for c in ('C1', 'C2', 'C3', 'C4', 'C5', 'n_C', 'prev_lost')},
        context_rank=LEVEL[context['level']], prev_result=reverse[0]['result_score'] if reverse else np.nan)
    return {'ctx_' + k: v for k, v in values.items()}, reverse


def r_pre(pre):
    return pre['ctx_context_rank'] + pre['ctx_D'] / 4


def prefix_stats(game, moves):
    """Input is physical move rows of both colours, with mover POV evaluations."""
    if prefix_status(game, moves) == DROP_INCOMPLETE:
        return None
    m = moves[moves.game_id.eq(game['raw_game_id']) & moves.ply.between(1, 20)].sort_values('ply')
    if m.ply.tolist() != list(range(1, 21)):
        raise ValueError('P-20 must have exactly physical plies 1..20')
    own = m[m.color.eq(game['color'])]
    opp = m[~m.color.eq(game['color'])]
    if len(own) != 10:
        raise ValueError('P-20 requires ten own moves')
    budget = game['initial_seconds'] + 40 * game['increment_seconds']
    thinks = own.think_seconds.dropna().to_numpy(dtype=float)
    cpl = own.cpl.dropna().to_numpy(dtype=float)
    clock = own.iloc[-1].clock_seconds
    row = dict(cpl_mean_w300=mean(np.minimum(cpl, 300)), cpl_max=float(cpl.max()) if len(cpl) else np.nan,
        opponent_cpl=mean(opp.cpl.clip(upper=300)),
        think_frac_median=float(np.median(thinks) / budget) if len(thinks) >= 5 and budget > 0 else np.nan,
        think_cv=float(thinks.std() / thinks.mean()) if len(thinks) >= 5 and thinks.mean() > 0 else np.nan,
        think_max_frac=float(thinks.max() / budget) if len(thinks) and budget > 0 else np.nan,
        clock_used=(game['initial_seconds'] - clock) / game['initial_seconds']
            if game['initial_seconds'] > 0 and pd.notna(clock) else np.nan,
        first_think=own.iloc[0].think_seconds)
    for plural, judgement in [('inaccuracies', 'inaccuracy'), ('mistakes', 'mistake'), ('blunders', 'blunder')]:
        row[plural] = float(own.judgement.eq(judgement).sum())
    for name, source in [('risk', 'risk'), ('attack', 'attack'), ('defensive', 'defensive'),
                         ('style_switch', 'style_switch'), ('sacrifice', 'sacrifice_heuristic')]:
        row[name + '_rate'] = float(own[source].astype(float).fillna(0).astype(bool).mean())
    own = own.copy()
    for c in ('risk', 'attack', 'defensive', 'style_switch'):
        own[c] = own[c].astype(float)
    dyn = dynamics(own).iloc[0]
    row.update({c: dyn[c] for c in B})
    wp = []
    for x in m.to_dict('records'):
        sign = 1 if x['color'] == game['color'] else -1
        wp.append(win_percent(sign * x['eval_after_cp'] if pd.notna(x['eval_after_cp']) else None,
                              sign * x['eval_after_mate'] if pd.notna(x['eval_after_mate']) else None))
    last = m.iloc[-1]
    # material_after is mover POV, just like stored evals.
    row.update(win_percent=wp[-1], win_percent_min=min((x for x in wp if x is not None), default=np.nan),
        material_balance=last.material_after * (1 if last.color == game['color'] else -1),
        legal_moves_mean=own.legal_moves.mean(),
        phase={'opening': 0., 'middlegame': 1., 'endgame': 2.}.get(last.phase, np.nan))
    return row


def pre_features(game, history, prior_labels, excluded=()):
    row, prior = session_context(game, history)
    row.update(initial_seconds=game['initial_seconds'], increment_seconds=game['increment_seconds'],
        rating=game['rating'], opponent_rating_delta=game['opponent_rating'] - game['rating'],
        color_white=float(game['color'] == 'white'))
    row.update({c: game[c] for c in HISTORY if c not in excluded})
    labels = [prior_labels[(x['game_id'], x['color'])] for x in prior]
    prev = labels[0] if labels else {}
    for c in X5:
        row['prev_x_' + c] = prev.get(c, np.nan)
    for c in Z5:
        row['prev_' + c] = prev.get(c, np.nan)
        row['session_mean_' + c] = mean([x[c] for x in labels[:3]])
    for c in rules.EVIDENCE:
        row['prev_' + c] = STATE.get(prev.get(c), np.nan)
    row['prev_n_fired'] = prev.get('n_fired', np.nan)
    row['prev_plies'] = prev.get('plies', np.nan)
    row['prev_status'] = STATUS.get(prev.get('status'), np.nan)
    row['prev_label'] = LABEL.get(prev.get('label'), np.nan)
    row['session_tilts10'] = float(sum(x['label'] == 'TILT' for x in labels[:10])) if labels else np.nan
    row['session_evidence_mean10'] = mean([x['n_fired'] for x in labels[:10]])
    reference = history[history.player_id.eq(game['player_id']) & history.start_ms.lt(game['start_ms']) & history.end_upper_ms.lt(game['start_ms']) &
                        history.speed.eq(game['speed'])].sort_values(['start_ms', 'raw_game_id']).tail(200)
    row['baseline_games'] = float(len(reference))
    for name in rules.FEATURES:
        vals = reference[name].dropna().to_numpy(dtype=float)
        median = float(np.median(vals)) if len(vals) >= 5 else np.nan
        row['baseline_' + name + '_median'] = median
        row['baseline_' + name + '_mad'] = float(np.median(np.abs(vals - median))) if len(vals) >= 5 else np.nan
        if name == 'risk_rate':
            row['baseline_risk_rate_games'] = float(len(vals))
    return row


def prefix_reference(game, history, complete_keys=None):
    prior = history[history.player_id.eq(game['player_id']) & history.start_ms.lt(game['start_ms']) &
                    history.end_upper_ms.lt(game['start_ms']) & history.plies.ge(20)].sort_values(['start_ms', 'raw_game_id'])
    if complete_keys is not None:
        prior = prior.loc[np.asarray([(x.game_id, x.color) in complete_keys for x in prior.itertuples()], dtype=bool)]
    return prior.tail(200)


def p20_features(game, history, prefix_cache):
    current = prefix_cache[(game['game_id'], game['color'])]
    row = {'p20_' + k: v for k, v in current.items()}
    complete = {key for key, value in prefix_cache.items() if value is not None}
    prior = prefix_reference(game, history, complete)
    for name in PZ:
        vals = np.asarray([prefix_cache[(x.game_id, x.color)][name] for x in prior.itertuples()], dtype=float)
        vals = vals[np.isfinite(vals)]
        value = current[name]
        if len(vals) >= 5 and pd.notna(value):
            median = np.median(vals)
            row['p20_z_' + name] = (value - median) / max(1.4826 * np.median(np.abs(vals - median)), FLOORS[name])
        else:
            row['p20_z_' + name] = np.nan
    zs = [row['p20_z_' + x] for x in ('risk_rate', 'attack_rate', 'sacrifice_rate')]
    row['p20_aggression'] = float(np.mean(zs)) if all(pd.notna(x) for x in zs) else np.nan
    return row


def aggregate_player(games, moves):
    # Later holdout headers are needed only to resolve E7's next-game/session
    # boundary. Their moves and whole-game aggregates are never constructed.
    games = games.copy()
    forbidden = set(games.loc[games.assignment.isin(['A_prime', 'B_prime']), 'raw_game_id'])
    moves = moves[~moves.game_id.isin(forbidden)]
    own = moves.merge(games[['raw_game_id', 'color']], left_on=['game_id', 'color'],
                      right_on=['raw_game_id', 'color'], validate='many_to_one').drop(columns='raw_game_id')
    g = rules.aggregates(games, own)
    clocks = own.dropna(subset=['clock_seconds']).sort_values('ply').groupby(['game_id', 'color']).clock_seconds.last()
    g['last_clock_seconds'] = [clocks.get((x.raw_game_id, x.color), np.nan) for x in g.itertuples()]
    # Physical terminal plies, not the last two own moves.
    terminals = {gid: x.sort_values('ply').tail(2).iloc[::-1].to_dict('records')
                 for gid, x in moves.groupby('game_id', sort=False)}
    return g, terminals


def frozen_labels(games, targets, terminals):
    """S3 explicitly authorizes development validation labels; freeze the S1 implementation.

    S1's train-only guard is adapted locally; real membership is restored on return.
    """
    allowed = targets.copy()
    allowed['split'] = 'train'
    result = rules.label_train(games, allowed, terminals)
    return result.drop(columns='split')


def build_player(games, moves, targets, mode='features', excluded=(), audit=None):
    targets_only(targets)
    player = targets.player_id.unique()
    if len(player) != 1:
        raise ValueError('Builder streams exactly one player')
    games = games[games.player_id.eq(player[0])].sort_values(['start_ms', 'game_id']).copy()
    source_targets = games.merge(targets[IDS], on=IDS, validate='one_to_one')
    if len(source_targets) != len(targets) or not source_targets.assignment.eq('development').all():
        raise ValueError('Targets do not match canonical development source rows')
    g, terminals = aggregate_player(games, moves)
    metadata = targets[IDS + ['part']]
    if mode == 'labels':
        labels = frozen_labels(g, targets, terminals).merge(metadata, on=['game_id', 'color', 'player_id'],
                                                           validate='one_to_one')
        one_colour = games.merge(moves.groupby('game_id').color.agg(lambda x: x.iloc[0] if x.nunique() == 1 else None)
            .rename('color_present'), left_on='raw_game_id', right_index=True)
        check_own_colour(one_colour, labels)
        return labels
    # Check all available prior P-20 prefixes before choosing the last 200
    # complete ones. Incomplete games remain in g for every F-pre calculation.
    eligible = g[g.start_ms.le(targets.start_ms.max()) & ~g.assignment.isin(['A_prime', 'B_prime'])]
    statuses = {(x['game_id'], x['color']): prefix_status(x, moves)
                for x in eligible.to_dict('records') if x['plies'] >= 20}
    complete = {key for key, status in statuses.items() if status == 'complete'}
    dropped = {key for key, status in statuses.items() if status == DROP_INCOMPLETE}
    exclusions = []
    for x in source_targets.to_dict('records'):
        if (x['game_id'], x['color']) in dropped:
            present = moves.loc[moves.game_id.eq(x['raw_game_id']) & moves.ply.between(1, 20), 'color'].iloc[0]
            exclusions.append({**{c: x[c] for c in IDS}, 'part': targets.loc[
                targets.game_id.eq(x['game_id']) & targets.color.eq(x['color']), 'part'].iloc[0],
                'plies': x['plies'], 'color_present': present, 'status': DROP_INCOMPLETE})
    affected = {part: 0 for part in split.PARTS}
    affected_remaining = {part: 0 for part in split.PARTS}
    # Only needed same-session histories receive transient rule evaluations. They
    # are never target/output rows. E3.5 explicitly preserves their frozen labels.
    needed = set()
    for game in g.merge(targets[['game_id', 'color']], on=['game_id', 'color']).to_dict('records'):
        _, prior = session_context(game, g)
        needed.update((x['game_id'], x['color']) for x in prior)
    internal = g[[ (x.game_id, x.color) in needed for x in g.itertuples()]]
    lookup = {}
    if len(internal):
        if internal.assignment.isin(['A_prime', 'B_prime']).any():
            raise ValueError('Holdout rule history would be required')
        lookup = {(x['game_id'], x['color']): x for x in frozen_labels(g, internal, terminals).to_dict('records')}
        one_colour = games.merge(moves.groupby('game_id').color.agg(lambda x: x.iloc[0] if x.nunique() == 1 else None)
            .rename('color_present'), left_on='raw_game_id', right_index=True).dropna(subset=['color_present'])
        check_own_colour(one_colour, pd.DataFrame(lookup.values()))
    prefix_cache = {}
    all_target_keys = set(map(tuple, targets[['game_id', 'color']].to_numpy()))
    target_keys = all_target_keys - dropped
    # Evaluate only prefixes used by a target or its prefix reference window.
    prefix_needed = set()
    for game in g[g.apply(lambda x: (x.game_id, x.color) in all_target_keys, axis=1)].to_dict('records'):
        if game['plies'] >= 20:
            key = (game['game_id'], game['color'])
            # Count the original eligible window if it skipped any E4 game;
            # then fill the actual window with the last <=200 complete prefixes.
            original = prefix_reference(game, g)
            if any((x.game_id, x.color) in dropped for x in original.itertuples()):
                part = targets.loc[targets.game_id.eq(game['game_id']) & targets.color.eq(game['color']), 'part'].iloc[0]
                affected[part] += 1
                if key in target_keys:
                    affected_remaining[part] += 1
            if key not in target_keys:
                continue
            prefix_needed.add(key)
            ref = prefix_reference(game, g, complete)
            prefix_needed.update(map(tuple, ref[['game_id', 'color']].to_numpy()))
    for game in g.to_dict('records'):
        key = (game['game_id'], game['color'])
        if key in prefix_needed:
            if game['assignment'] in ('A_prime', 'B_prime'):
                raise ValueError('Holdout prefix history would be required')
            prefix_cache[key] = prefix_stats(game, moves)
    pre, p20 = [], []
    for game in g.to_dict('records'):
        key = (game['game_id'], game['color'])
        if key not in target_keys:
            continue
        meta = metadata[metadata.game_id.eq(game['game_id']) & metadata.color.eq(game['color'])].iloc[0].to_dict()
        pre.append(dict(meta, **pre_features(game, g, lookup, excluded)))
        if game['plies'] >= 20:
            p20.append(dict(meta, **p20_features(game, g, prefix_cache)))
    reg = registry(excluded)
    if audit is not None:
        audit.update(exclusions=exclusions, affected_targets=affected, affected_remaining_targets=affected_remaining)
    def frame(rows, block):
        names = reg.loc[reg.block.eq(block), 'column'].tolist()
        out = pd.DataFrame(rows, columns=IDS + ['part'] + names)
        out[names] = out[names].astype(float)
        return out
    return frame(pre, 'pre'), frame(p20, 'p20')


def content_hashes(root):
    return ''.join(f'{split.sha(p)}  {p.name}\n' for p in sorted((Path(root) / 'features').glob('*.parquet')))


def verify_sources(args):
    if split.sha(args.prereg) != split.PREREG_SHA or Path(args.lock).read_text().split()[0] != split.PREREG_SHA:
        raise ValueError('Pre-registration lock mismatch')
    if split.sha(Path(args.s2) / 'holdout_manifest.parquet') != split.HOLDOUT_SHA:
        raise ValueError('Holdout hash mismatch')
    for name, root in [('old', args.old_root), ('new', args.new_root)]:
        baseline = Path(args.s3) / f'features_content_{name}.sha256'
        if not baseline.exists() or baseline.read_text() != content_hashes(root):
            raise ValueError('Feature content hash mismatch or missing pre-build baseline')
    if (Path(args.s1) / 'design_hash.txt').read_text().strip() != rules.DESIGN.hash:
        raise ValueError('Frozen rules design hash changed')


def load_manifest(args, headers):
    path = Path(args.s3) / 'dev_split_manifest.parquet'
    if split.sha(path) != (Path(args.s3) / 'dev_split_manifest.sha256').read_text().split()[0]:
        raise ValueError('Split hash mismatch')
    manifest = pd.read_parquet(path)
    split.integrity(manifest, headers[headers.assignment.eq('development')])
    # Session hashes are deliberately distinct from the raw in-memory session key.
    expected = headers[headers.assignment.eq('development')][IDS + ['physical_id', 'start_ms', 'session_id', 'split_key']].copy()
    expected.session_id = expected.session_id.map(lambda x: split.digest('label-v3-session:' + str(x)))
    joined = manifest.merge(expected, on=IDS, suffixes=('', '_expected'), validate='one_to_one')
    for c in ('physical_id', 'start_ms', 'session_id', 'split_key'):
        if not joined[c].eq(joined[c + '_expected']).all():
            raise ValueError('Split metadata differs from source')
    return headers.merge(manifest[IDS + ['part']], on=IDS, how='left', validate='one_to_one')


def worker(task):
    root, games, targets, mode, excluded, s1 = task
    readable = games[~games.assignment.isin(['A_prime', 'B_prime'])]
    if not (mode == 'labels' and games.cohort.eq('old').all()):
        readable = readable[readable.start_ms.le(targets.start_ms.max())]
    physical = readable.raw_game_id.unique().tolist()
    moves = pd.read_parquet(Path(root) / 'features/moves.parquet', columns=MOVE_COLS,
                            filters=[('game_id', 'in', physical)], use_threads=False)
    # One physical move can appear once only, including shared cohort games.
    if moves.duplicated(['game_id', 'ply']).any():
        raise ValueError('Duplicate physical plies')
    audit = {}
    result = build_player(games, moves, targets, mode, excluded, audit)
    if mode != 'labels':
        return dict(frames=result, regression={}, erratum4=audit)
    checks = {}
    if games.cohort.eq('old').all():
        expected = {name: pd.read_parquet(Path(s1) / f'labels_{name}_train.parquet',
            columns=['game_id', 'color', 'player_id', 'label'],
            filters=[('player_id', '==', games.player_id.iloc[0])]) for name in ('by_player', 'by_time')}
        keys = pd.concat(list(expected.values()))[['game_id', 'color']].drop_duplicates()
        if len(keys):
            # Item 9 also requires S1 rows that are now S3 drops. They are checked
            # in memory and only aggregate agreement counts leave this worker.
            g, terminals = aggregate_player(games, moves)
            wanted = g.merge(keys, on=['game_id', 'color'], validate='one_to_one')
            actual = frozen_labels(g, wanted, terminals)
            for name, exp in expected.items():
                joined = exp.merge(actual[['game_id', 'color', 'label']], on=['game_id', 'color'],
                                   suffixes=('_s1', '_s3'), validate='one_to_one')
                matches = int(joined.label_s1.eq(joined.label_s3).sum())
                if len(joined) != len(exp) or matches != len(exp):
                    raise ValueError('S1 regression mismatch')
                checks[name] = dict(expected=len(exp), checked=len(joined), matches=matches)
    return dict(frames=(result,), regression=checks)


def write_tables(results, paths, regressions=None, audits=None, before_publish=None):
    """Explicit Arrow types prevent a cold player's all-null column fixing null schema."""
    writers, counts = {}, {str(p): 0 for p in paths}
    try:
        for result in results:
            if isinstance(result, dict):
                if regressions is not None:
                    regressions.append(result['regression'])
                if audits is not None and 'erratum4' in result:
                    audits.append(result['erratum4'])
                result = result['frames']
            frames = result if isinstance(result, tuple) else (result,)
            for path, frame in zip(paths, frames):
                if frame.empty:
                    continue
                frame = frame.reset_index(drop=True)
                table = pa.Table.from_pandas(frame, preserve_index=False)
                # All registered features float64; labels have stable enums/metadata.
                fields = [pa.field(f.name, pa.string() if f.type == pa.null() else f.type) for f in table.schema]
                table = table.cast(pa.schema(fields)).replace_schema_metadata(None)
                if path not in writers:
                    writers[path] = pq.ParquetWriter(str(path) + '.tmp', table.schema, compression='zstd')
                table = table.select(writers[path].schema.names).cast(writers[path].schema)
                writers[path].write_table(table)
                counts[str(path)] += len(frame)
        for path in paths:
            if path not in writers:
                raise ValueError('Output population is empty')
        if before_publish is not None:
            before_publish()
        for path, writer in writers.items():
            writer.close()
            Path(str(path) + '.tmp').replace(path)
        writers.clear()
    finally:
        for writer in writers.values():
            writer.close()
    return list(counts.values())


def build(args, mode):
    headers = load_manifest(args, split.load_headers(args.old_root, args.new_root, args.s2))
    target = headers[headers.part.isin(split.PARTS)]
    players = target[['cohort', 'player_id', 'split_key']].drop_duplicates().sort_values(['cohort', 'split_key'])
    if args.max_players:
        if args.max_players > 5 or Path(args.out).resolve() == Path(args.s3).resolve():
            raise ValueError('Smoke builds require <=5 players and a separate output directory')
        # Alternate roots for representative smoke coverage.
        groups = [g.reset_index(drop=True) for _, g in players.groupby('cohort')]
        order = [g.iloc[i] for i in range(max(map(len, groups))) for g in groups if i < len(g)]
        players = pd.DataFrame(order).head(args.max_players)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    paths = [out / 'labels_dev.parquet'] if mode == 'labels' else [out / 'features_pre.parquet', out / 'features_p20.parquet']
    if any(p.exists() or Path(str(p) + '.tmp').exists() for p in paths):
        raise FileExistsError('Build output already exists')
    full_exclusions = None
    if mode == 'features':
        # E4.3 count and E4.5 own-colour checks finish before feature publication.
        inventory, full_exclusions, _ = audit_incomplete(args, headers)
    excluded = tuple(args.exclude_history or ())
    tasks = []
    for r in players.itertuples():
        own = headers[headers.player_id.eq(r.player_id) & headers.cohort.eq(r.cohort)]
        targets = own[own.part.isin(split.PARTS)]
        tasks.append((args.old_root if r.cohort == 'old' else args.new_root, own, targets, mode, excluded, args.s1))
    start = time.monotonic()
    regressions, audits = [], []
    def publish_audit():
        found = pd.DataFrame([x for a in audits for x in a['exclusions']], columns=EXCLUSION_COLS)
        if not args.max_players:
            check_incomplete_count(found)
        expected = full_exclusions.merge(players[['cohort', 'player_id']], on=['cohort', 'player_id'])
        if found.sort_values(IDS).to_dict('records') != expected[EXCLUSION_COLS].sort_values(IDS).to_dict('records'):
            raise ValueError('Erratum 4 worker exclusions differ from count-only audit')
        found.sort_values(IDS).to_csv(out / 'excluded_incomplete_moves.csv', index=False)
    before_publish = publish_audit if mode == 'features' else None
    if args.processes == 1:
        counts = write_tables(map(worker, tasks), paths, regressions, audits, before_publish)
    else:
        # Bounded batches avoid retaining all players' result tables in executor buffers.
        with ProcessPoolExecutor(max_workers=args.processes, mp_context=multiprocessing.get_context('spawn')) as pool:
            def ordered():
                for i in range(0, len(tasks), args.processes):
                    yield from pool.map(worker, tasks[i:i + args.processes])
            counts = write_tables(ordered(), paths, regressions, audits, before_publish)
    if mode == 'features':
        registry(excluded).to_csv(out / 'feature_registry.csv', index=False)
        paths.append(out / 'excluded_incomplete_moves.csv')
    else:
        totals = {name: {c: sum(r.get(name, {}).get(c, 0) for r in regressions)
                         for c in ('expected', 'checked', 'matches')}
                  for name in ('by_player', 'by_time')}
        complete = not args.max_players
        if complete:
            for name, values in totals.items():
                expected_count = pq.ParquetFile(Path(args.s1) / f'labels_{name}_train.parquet').metadata.num_rows
                if values['checked'] != expected_count:
                    raise ValueError('Incomplete full S1 regression')
        (out / 'label_regression.json').write_text(json.dumps(dict(complete=complete,
            design_hash=rules.DESIGN.hash, checks=totals), indent=2) + '\n')
    record = dict(players=len(players), rows=counts, seconds=time.monotonic() - start,
                  parent_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  children_peak_rss_kib=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
                  processes=args.processes, smoke=bool(args.max_players), excluded_history=list(excluded),
                  design_hash=rules.DESIGN.hash, code_hash=code_hash_text(),
                  output_sha256={p.name: split.sha(p) for p in paths},
                  split_sha=split.sha(Path(args.s3) / 'dev_split_manifest.parquet'))
    if mode == 'features':
        record['erratum4'] = dict(status=DROP_INCOMPLETE,
            excluded_targets=sum(len(a['exclusions']) for a in audits),
            affected_targets={part: sum(a['affected_targets'][part] for a in audits) for part in split.PARTS},
            affected_remaining_targets={part: sum(a['affected_remaining_targets'][part] for a in audits) for part in split.PARTS})
    (out / (mode + '_build.json')).write_text(json.dumps(record, indent=2) + '\n')
    code_hash(out)
    verify_sources(args)
    return record


def code_hash(out):
    (Path(out) / 'code_hash.txt').write_text(code_hash_text())


def code_hash_text():
    paths = [Path(split.__file__), Path(__file__), Path(rules.__file__)]
    return ''.join(f'{split.sha(p)}  {p.name}\n' for p in paths)


def regression(labels, s1, complete=True):
    """Every S1 row, including S3 drops, is checked by the dedicated recomputation path."""
    checks = {}
    for name in ('by_player', 'by_time'):
        expected = pd.read_parquet(Path(s1) / f'labels_{name}_train.parquet', columns=['game_id', 'color', 'label'])
        actual = labels[labels.cohort.eq('old')][['game_id', 'color', 'label']]
        joined = expected.merge(actual, on=['game_id', 'color'], suffixes=('_s1', '_s3'), validate='one_to_one')
        checks[name] = dict(expected=len(expected), checked=len(joined), matches=int(joined.label_s1.eq(joined.label_s3).sum()))
        if complete and len(joined) != len(expected):
            raise ValueError('Incomplete S1 regression')
        if not joined.label_s1.eq(joined.label_s3).all():
            raise ValueError('S1 label regression mismatch')
    return checks


def length_probe(pre, p20, lengths):
    """No labels are accepted; every statistic/fold uses train only."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import GroupKFold
    result = dict(single=[], multi=[], stop=False)
    for block, features, cuts in [('pre', pre, (20, 40)), ('p20', p20, (40,))]:
        frame = features[features.part.eq('train')].merge(lengths[IDS + ['plies']], on=IDS, validate='one_to_one')
        cols = registry().loc[lambda x: x.block.eq(block), 'column']
        cols = [c for c in cols if c in frame]
        for cut in cuts:
            y = frame.plies.lt(cut)
            for col in cols:
                valid = frame[col].notna()
                auc = float(roc_auc_score(y[valid], frame.loc[valid, col])) if y[valid].nunique() == 2 else None
                auc = max(auc, 1 - auc) if auc is not None else None
                diff = None
                if block == 'p20' and y.any() and (~y).any():
                    diff = abs(float(frame.loc[y, col].isna().mean() - frame.loc[~y, col].isna().mean()))
                stop = (auc is not None and auc >= .70) or (diff is not None and diff > .02)
                result['single'].append(dict(block=block, column=col, threshold=cut, auc=auc,
                    null_rate_difference=diff, stop=stop, rows=len(frame)))
                result['stop'] |= stop
            folds = []
            if frame.player_id.nunique() >= 3:
                for train, test in GroupKFold(3).split(frame, y, frame.player_id):
                    if y.iloc[train].nunique() < 2 or y.iloc[test].nunique() < 2:
                        folds.append(None)
                        continue
                    model = HistGradientBoostingClassifier(max_iter=100, random_state=0)
                    model.fit(frame[cols].iloc[train], y.iloc[train])
                    folds.append(float(roc_auc_score(y.iloc[test], model.predict_proba(frame[cols].iloc[test])[:, 1])))
            result['multi'].append(dict(block=block, threshold=cut, grouped_folds=folds, report_only=True))
    return result


def describe(pre, p20, labels):
    labels = labels[labels.part.eq('train')].copy()
    labels = labels.merge(pre[IDS], on=IDS, validate='one_to_one')
    output = dict(labels=[], features=[], gates_description={}, context_rank_differences=0)
    join = labels.merge(pre[IDS + ['ctx_context_rank']], on=IDS, validate='one_to_one')
    output['context_rank_differences'] = int(join.level.map(LEVEL).ne(join.ctx_context_rank).sum())
    for (cohort, population), frame in labels.assign(population=labels.plies.ge(20)).groupby(['cohort', 'population']):
        n = int(frame.label.ne('ABSTAIN').sum())
        output['labels'].append(dict(cohort=cohort, p20=bool(population), rows=len(frame),
            counts=frame.label.value_counts().to_dict(), coverage=n / len(frame),
            prevalence=float(frame.label.eq('TILT').sum() / n) if n else None))
    for cohort, frame in [('all', labels), *list(labels.groupby('cohort'))]:
        labelled = frame.label.ne('ABSTAIN')
        output['labels'].append(dict(cohort=cohort, population='P-all', rows=len(frame),
            counts=frame.label.value_counts().to_dict(), coverage=float(labelled.mean()) if len(frame) else None,
            prevalence=float(frame.loc[labelled, 'label'].eq('TILT').mean()) if labelled.any() else None))
        frame = frame.assign(split='train')
        # G1 length AUC is the sole expressly requested label association; no
        # prediction score, R-pre, B-streak or result-score AUC is computed.
        output['gates_description'][cohort] = rules.gates(frame)
        for value in output['gates_description'][cohort].values():
            value.pop('passed', None)
    for block, frame in [('pre', pre), ('p20', p20)]:
        frame = frame[frame.part.eq('train')]
        for cohort, group in frame.groupby('cohort'):
            for c in registry().loc[lambda x: x.block.eq(block), 'column']:
                if c in group:
                    output['features'].append(dict(block=block, cohort=cohort, column=c,
                        null_rate=float(group[c].isna().mean()), median=group[c].median()))
    return output


def gate(args, headers):
    out = Path(args.out)
    m = pd.read_parquet(Path(args.s3) / 'dev_split_manifest.parquet')
    if split.sha(Path(args.s3) / 'dev_split_manifest.parquet') != (Path(args.s3) / 'dev_split_manifest.sha256').read_text().split()[0]:
        raise ValueError('Split hash mismatch')
    split.integrity(m, headers[headers.assignment.eq('development')])
    labels, pre, p20 = (pd.read_parquet(out / p) for p in ['labels_dev.parquet', 'features_pre.parquet', 'features_p20.parquet'])
    expected = headers.drop(columns='part', errors='ignore').merge(m[IDS + ['part']], on=IDS, validate='one_to_one')
    expected = expected[expected.part.isin(split.PARTS)]
    checks = {}
    exclusion_path = out / 'excluded_incomplete_moves.csv'
    exclusions = pd.read_csv(exclusion_path)
    audit_headers = headers.drop(columns='part', errors='ignore').merge(m[IDS + ['part']], on=IDS, how='left', validate='one_to_one')
    inventory, wanted_exclusions, _ = audit_incomplete(args, audit_headers)
    check_incomplete_count(exclusions)
    checks['incomplete_exclusions'] = exclusions.to_dict('records') == wanted_exclusions.sort_values(IDS).to_dict('records')
    kept = expected.merge(exclusions[IDS], on=IDS, how='left', indicator=True)
    kept = kept[kept._merge.eq('left_only')].drop(columns='_merge')
    for name, actual, wanted in [('labels', labels, expected), ('pre', pre, kept),
                                  ('p20', p20, kept[kept.plies.ge(20)])]:
        checks[name] = not actual.duplicated(IDS).any() and set(map(tuple, actual[IDS].to_numpy())) == set(map(tuple, wanted[IDS].to_numpy()))
        if checks[name]:
            joined = actual[IDS + ['part']].merge(wanted[IDS + ['part']], on=IDS)
            checks[name] = bool(joined.part_x.eq(joined.part_y).all())
    probe = json.loads((out / 'length_probe.json').read_text())
    tests = json.loads(Path(args.test_evidence).read_text()) if args.test_evidence else {}
    reg = json.loads((out / 'label_regression.json').read_text()) if (out / 'label_regression.json').exists() else {}
    checks['tests'] = tests.get('passed') is True and tests.get('code_hash') == (out / 'code_hash.txt').read_text()
    checks['tests'] &= (out / 'code_hash.txt').read_text() == code_hash_text()
    checks['real_sample_tests'] = all(
        (Path(args.s3) / f'real_tests_{cohort}.json').exists() and
        json.loads((Path(args.s3) / f'real_tests_{cohort}.json').read_text()).get('passed') is True and
        json.loads((Path(args.s3) / f'real_tests_{cohort}.json').read_text()).get('code_hash') == code_hash_text()
        for cohort in ('old', 'new'))
    checks['build_provenance'] = True
    for name in ('labels', 'features'):
        record = json.loads((out / (name + '_build.json')).read_text())
        checks['build_provenance'] &= (not record['smoke'] and record['code_hash'] == code_hash_text()
            and record['design_hash'] == rules.DESIGN.hash and record['split_sha'] == split.sha(Path(args.s3) / 'dev_split_manifest.parquet'))
        checks['build_provenance'] &= all(split.sha(out / filename) == digest for filename, digest in record['output_sha256'].items())
    feature_record = json.loads((out / 'features_build.json').read_text())
    checks['exclusion_hash'] = feature_record['output_sha256'].get('excluded_incomplete_moves.csv') == split.sha(exclusion_path)
    excluded = feature_record['excluded_history']
    model_matrix(pre, 'pre', excluded=excluded)
    model_matrix(pre.merge(p20, on=IDS + ['part'], validate='one_to_one'), 'p20', excluded=excluded)
    checks['registry'] = pd.read_csv(out / 'feature_registry.csv').equals(registry(excluded))
    checks['regression'] = bool(reg) and reg.get('complete') is True and reg.get('design_hash') == rules.DESIGN.hash and all(
        x['expected'] == x['checked'] == x['matches'] for x in reg.get('checks', {}).values())
    if checks['regression']:
        checks['regression'] &= set(reg['checks']) == {'by_player', 'by_time'} and all(
            reg['checks'][name]['checked'] == pq.ParquetFile(Path(args.s1) / f'labels_{name}_train.parquet').metadata.num_rows
            for name in ('by_player', 'by_time'))
    # Stops require an explicit, hashed decision, never silent feature removal.
    decision = json.loads(Path(args.decisions).read_text()) if args.decisions else {}
    stops = {(x['block'], x['column'], x['threshold']) for x in probe['single'] if x['stop']}
    decided = {tuple(x) for x in decision.get('accepted_stops', [])}
    checks['probe'] = not stops or (stops <= decided and decision.get('probe_sha') == split.sha(out / 'length_probe.json'))
    checks['split'] = True
    verify_sources(args)
    checks['content_hashes'] = True
    verdict = dict(checks=checks, passed=all(checks.values()),
        excluded_incomplete_moves_sha256=split.sha(exclusion_path),
        erratum4=json.loads((out / 'features_build.json').read_text()).get('erratum4'),
        decision_sha=split.sha(args.decisions) if args.decisions else None)
    (out / 's3_gate.json').write_text(json.dumps(verdict, indent=2) + '\n')
    return verdict


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('step', choices=['split', 'labels', 'features', 'probe', 'gate', 'describe', 'audit-incomplete'])
    for name in ('old-root', 'new-root', 's1', 's2', 's3', 'out', 'prereg', 'lock'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--processes', type=int, default=1)
    parser.add_argument('--max-players', type=int)
    parser.add_argument('--exclude-history', nargs='*', choices=HISTORY)
    parser.add_argument('--test-evidence', type=Path)
    parser.add_argument('--decisions', type=Path)
    args = parser.parse_args(argv)
    if args.processes < 1:
        parser.error('--processes must be positive')
    if args.max_players is not None and not 1 <= args.max_players <= 5:
        parser.error('--max-players must be between 1 and 5')
    for destination in (args.out, args.s3):
        if any(destination.resolve().is_relative_to(root.resolve()) for root in (args.old_root, args.new_root)):
            parser.error('Output directories must be outside both read-only roots')
    verify_sources(args)
    if args.step == 'split':
        headers = split.load_headers(args.old_root, args.new_root, args.s2)
        pool = headers[headers.assignment.eq('development')]
        saved = split.write_once(split.assign(pool), args.s3, args.s2 / 'holdout_manifest.parquet')
        result = dict(rows=len(saved), players=saved.player_id.nunique())
        code_hash(args.s3)
    elif args.step in ('labels', 'features'):
        result = build(args, args.step)
    else:
        headers = split.load_headers(args.old_root, args.new_root, args.s2)
        manifest_headers = load_manifest(args, headers)
        if args.step == 'audit-incomplete':
            args.out.mkdir(parents=True, exist_ok=True)
            _, _, result = audit_incomplete(args, manifest_headers)
        elif args.step == 'gate':
            result = gate(args, headers)
        else:
            pre, p20 = (pd.read_parquet(args.out / f'features_{block}.parquet') for block in ('pre', 'p20'))
            if args.step == 'probe':
                result = length_probe(pre, p20, manifest_headers[IDS + ['plies']])
                (args.out / 'length_probe.json').write_text(json.dumps(result, indent=2) + '\n')
            else:
                labels = pd.read_parquet(args.out / 'labels_dev.parquet')
                result = describe(pre, p20, labels)
                (args.out / 'description_train.json').write_text(json.dumps(result, indent=2, default=lambda x: None) + '\n')
    verify_sources(args)
    # Privacy: only execution counts/timing, never identifiers or frame reprs.
    print(json.dumps(result if args.step in ('split', 'labels', 'features', 'gate', 'audit-incomplete') else
                     dict(step=args.step, written=True, stop=result.get('stop')), sort_keys=True))
    if args.step == 'probe' and result['stop']:
        return 2
    if args.step == 'gate' and not result['passed']:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
