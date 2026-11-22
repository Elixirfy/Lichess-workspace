"""Locked S1 rule labels; only explicit train targets may be labelled/scored.

Run with ``python -m tilt.labels.tilt_rules --help``. No model fitting, engine,
salt, or historical weak-label implementation is used here. Non-train games
are feature history only; their evidence and labels are never constructed.
"""
from dataclasses import asdict, dataclass
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import time

import numpy as np
import pandas as pd
from sklearn.metrics import cohen_kappa_score, roc_auc_score

from ..common.formulas import win_percent
from ..features.features import GAME_BASELINES


@dataclass(frozen=True)
class Design:
    history_cap: int = 200
    bucket_min: int = 20
    pooled_min: int = 5
    fallback_min: int = 20
    feature_min: int = 5
    own_min: int = 5
    eval_min: int = 5
    think_min: int = 5
    short_plies: int = 40
    long_plies: int = 80
    mad_scale: float = 1.4826
    floors: tuple = (('cpl_mean_w300', 5.0), ('blunders_per20', .2),
                     ('think_frac_median', .002), ('think_cv', .10),
                     ('risk_rate', .05), ('attack_rate', .05), ('sacrifice_rate', .02))
    cpl_cap: float = 300.0
    blunder_scale: int = 20
    clock_increment_moves: int = 40
    c1_run: int = 2
    c2_windows: tuple = ((5, 3), (10, 5))
    decay_cap: int = 10
    decay_base: float = .5
    decay_half_games: float = 2.0
    c3_load: float = 2.0
    c4_rating: float = -30.0
    c5_seconds: float = 120.0
    c5_gaps: int = 3
    recent_games: int = 5
    strong_votes: int = 2
    z_threshold: float = 1.0
    resign_win_percent: float = 20.0
    timeout_clock_fraction: float = .20
    gap_quantile: float = .20
    gap_min: int = 10
    requeue_seconds: float = 60.0
    low_quantile: float = .20
    high_quantile: float = .80
    aggression_votes: int = 2
    strong_evidence: int = 2
    weak_evidence: int = 3
    won_evidence: int = 3
    not_max: int = 1
    monotone_evidence: int = 2
    run_last_bin: int = 3
    length_auc_max: float = .60
    length_gap_max: float = .15
    length_bucket_min: int = 100
    coverage_min: float = .50
    prevalence_min: float = .10
    prevalence_max: float = .35
    won_max: float = .10
    dominance_max: float = .70
    monotone_rise_min: float = .03
    monotone_slack: float = .01
    rating_match_min: float = .95
    expected_train: tuple = (('by_player', 22316), ('by_time', 25403))
    runtime_limit_seconds: int = 1200

    @property
    def hash(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True,
                                         separators=(',', ':')).encode()).hexdigest()


DESIGN = Design()
FEATURES = tuple(dict(DESIGN.floors))
EVIDENCE = tuple(f'E{i}' for i in range(1, 8))
KEYS = ['game_id', 'color']
# Existing exports HMAC the game ID. This exact, verified one-to-one bridge
# reuses their IDs, without needing the salt or computing any pseudonym.
BRIDGE = ['start_ms', 'color', 'rating', 'opponent_rating', 'result_score', 'end_upper_ms']


class PreflightError(ValueError):
    """A §8 stop, before any evidence, label statistic, or gate is computed."""


def require(condition, message):
    if not condition:
        raise PreflightError(message)


def train_only(frame):
    """Fail closed, including empty/missing/unknown partition declarations."""
    if 'split' not in frame or not frame['split'].eq('train').all():
        raise ValueError('Only explicitly declared train rows may be labelled or scored')


def read_raw_games(data):
    """Same committed shards as storage.read, using a read-only SQLite handle.

    storage.read calls connect(), which executes DDL/commit. Inputs here must
    remain read-only, so reproduce only its committed-batch selection.
    """
    data = Path(data).resolve()
    with sqlite3.connect(f'file:{data}/processed/index.sqlite?mode=ro', uri=True) as db:
        batches = {r[0] for r in db.execute('SELECT batch FROM batches')}
    files = [p for p in sorted((data / 'processed/normalized/games').glob('*.parquet'))
             if p.stem in batches]
    require(bool(files), 'No committed normalized games')
    return pd.read_parquet(files, columns=['game_id', 'status', 'plies', 'rated',
                                          'white_rating', 'black_rating'])


def rating_check(games, aligned, d=DESIGN):
    """No label inputs: consecutive rated games, anchored on each train set.

    Also check pairs whose two endpoints are train; report both denominators.
    Zero changes are mismatches; draws and missing ratings are excluded.
    """
    ordered = games[games.rated.eq(True)].sort_values(['player_id', 'start_ms', 'game_id'])
    ordered = ordered.copy()
    for name in ('rating', 'game_id', 'color'):
        ordered['next_' + name] = ordered.groupby('player_id')[name].shift(-1)
    checks = {}
    for split, membership in aligned.items():
        train = membership[membership.split.eq('train')][KEYS]
        pairs = ordered.merge(train, on=KEYS, validate='one_to_one')
        pairs = pairs[pairs.result_score.isin([0, 1]) & pairs.rating.notna() & pairs.next_rating.notna()]
        match = ((pairs.next_rating - pairs.rating) * (2 * pairs.result_score - 1)).gt(0)
        both = pd.MultiIndex.from_frame(pairs[['next_game_id', 'next_color']]).isin(
            pd.MultiIndex.from_frame(train))
        checks[split] = dict(pairs=len(pairs), matches=int(match.sum()),
                             share=float(match.mean()), both_train_pairs=int(both.sum()),
                             both_train_matches=int(match.to_numpy()[both].sum()),
                             both_train_share=float(match.to_numpy()[both].mean()))
        require(len(pairs) > 0 and match.mean() >= d.rating_match_min and both.any()
                and match.to_numpy()[both].mean() >= d.rating_match_min,
                f'E1.5 rating sign check failed: {split}: {checks[split]}')
    return checks


def load_inputs(data, aligned_dir, d=DESIGN):
    """All mandatory data checks finish before aggregate/evidence construction."""
    data, aligned_dir = Path(data), Path(aligned_dir)
    cols = KEYS + ['player_id', 'split', 'initial_seconds', 'increment_seconds'] + [
        c for c in BRIDGE if c not in KEYS]
    aligned = {s: pd.read_parquet(aligned_dir / f'aligned_{s}.parquet', columns=cols)
               for s, _ in d.expected_train}
    for s, expected in d.expected_train:
        a = aligned[s]
        require(not a.duplicated(KEYS).any() and a.player_id.notna().all(), 'Invalid aligned keys')
        require(int(a.split.eq('train').sum()) == expected, f'Unexpected {s} train count')
    left, right = (aligned[s].drop(columns='split').sort_values(KEYS).reset_index(drop=True)
                   for s, _ in d.expected_train)
    require(left.equals(right), 'Aligned sources differ outside split membership')
    gcols = ['game_id', 'player', 'session_id', 'speed', 'end_ms'] + BRIDGE
    features = pd.read_parquet(data / 'processed/features/games.parquet', columns=gcols)
    require(not features.duplicated(BRIDGE).any() and not left.duplicated(BRIDGE).any(),
            'Metadata bridge is not one-to-one')
    bridge = left.rename(columns={'game_id': 'export_game_id'}).merge(
        features, on=BRIDGE, how='left', validate='one_to_one', indicator=True)
    require(bridge['_merge'].eq('both').all(), 'Metadata bridge has unmatched cohort rows')
    require(bridge.groupby('player').player_id.nunique().eq(1).all()
            and bridge.groupby('player_id').player.nunique().eq(1).all(), 'Player bridge is inconsistent')
    require(int(features.player.isin(bridge.player).sum()) == len(bridge),
            'Additional feature games of cohort players lack aligned time controls')
    raw = read_raw_games(data)
    g = bridge.drop(columns='_merge').merge(raw, on='game_id', validate='many_to_one')
    require(g.rating.eq(g.white_rating.where(g.color.eq('white'), g.black_rating)).all(),
            'Feature rating differs from normalized pre-game rating')
    require(g.start_ms.notna().all() and g.session_id.notna().all(), 'Missing start/session')
    require(GAME_BASELINES.get('risk_rate') == dict(d.floors)['risk_rate']
            and GAME_BASELINES.get('attack_rate') == dict(d.floors)['attack_rate']
            and GAME_BASELINES.get('sacrifice_rate', .02) == dict(d.floors)['sacrifice_rate'],
            'Existing unit floors differ from Erratum 1')
    # Raw IDs remain internal. All public target/output IDs are the aligned IDs.
    g = g.rename(columns={'game_id': 'raw_game_id', 'export_game_id': 'game_id'})
    checks = rating_check(g, aligned, d)
    # Column checks precede loading/aggregating any per-move label quantities.
    import pyarrow.parquet as pq
    move_columns = ['game_id', 'color', 'ply', 'cpl', 'judgement', 'think_seconds',
                    'risk', 'attack', 'sacrifice_heuristic', 'eval_after_cp',
                    'eval_after_mate', 'clock_seconds']
    require(set(move_columns) <= set(pq.read_schema(data / 'processed/features/moves.parquet').names),
            'Required move columns are absent')
    return g, aligned, checks


def aggregates(games, moves, d=DESIGN):
    """Vectorised per-side features for train targets and allowed prior inputs."""
    m = moves.merge(games[['raw_game_id', 'color', 'game_id', 'initial_seconds', 'increment_seconds']],
                    left_on=['game_id', 'color'], right_on=['raw_game_id', 'color'],
                    suffixes=('_raw', ''), validate='many_to_one')
    m['cpl_mean_w300'] = m.cpl.clip(upper=d.cpl_cap)
    m['blunder'] = m.judgement.eq('blunder').astype(int)
    for flag in ('risk', 'attack', 'sacrifice_heuristic'):
        m[flag + '_flag'] = m[flag].fillna(False).astype(bool).astype(int)
    groups = m.groupby(KEYS, sort=False)
    a = groups.agg(own_moves=('ply', 'size'), eval_moves=('cpl', 'count'),
                   cpl_mean_w300=('cpl_mean_w300', 'mean'), blunders=('blunder', 'sum'),
                   think_count=('think_seconds', 'count'), think_mean=('think_seconds', 'mean'),
                   think_median=('think_seconds', 'median'),
                   risk_rate=('risk_flag', 'mean'), attack_rate=('attack_flag', 'mean'),
                   sacrifice_rate=('sacrifice_heuristic_flag', 'mean'))
    a['think_std'] = groups.think_seconds.std(ddof=0)
    a['blunders_per20'] = d.blunder_scale * a.blunders / a.eval_moves.replace(0, np.nan)
    a.loc[a.eval_moves < d.eval_min, ['cpl_mean_w300', 'blunders_per20']] = np.nan
    a['think_cv'] = a.think_std / a.think_mean.where(a.think_mean.gt(0))
    a.loc[a.think_count < d.think_min, 'think_cv'] = np.nan
    g = games.merge(a.reset_index(), on=KEYS, how='left', validate='one_to_one')
    denominator = g.initial_seconds + d.clock_increment_moves * g.increment_seconds
    g['think_frac_median'] = g.think_median / denominator.where(denominator.gt(0))
    g.loc[g.think_count.lt(d.think_min), 'think_frac_median'] = np.nan
    return g


def context(row, prior, d=DESIGN):
    """prior is S(g), in reverse chronological order; no evidence is read."""
    results = [p['result_score'] for p in prior]
    run = 0
    for result in results:
        if result == 1:
            break
        if result == 0:
            run += 1
    load = sum((r == 0) * d.decay_base ** (k / d.decay_half_games)
               for k, r in enumerate(results[:d.decay_cap]))
    delta = row['rating'] - (prior[-1]['rating'] if prior else row['rating'])
    c1 = run >= d.c1_run
    c2 = any(sum(r == 0 for r in results[:w]) >= n for w, n in d.c2_windows)
    c3, c4 = load >= d.c3_load, bool(pd.notna(delta) and delta <= d.c4_rating)
    last_loss = next((p for p in prior if p['result_score'] == 0), None)
    recency = ((row['start_ms'] - last_loss['end_ms']) / 1000
               if last_loss is not None and pd.notna(last_loss['end_ms']) else np.nan)
    gaps = [row.get('exact_gap', np.nan)] + [p.get('exact_gap', np.nan) for p in prior[:d.c5_gaps - 1]]
    c5 = (len(prior) >= d.c5_gaps and pd.notna(recency) and recency <= d.c5_seconds
          and len(gaps) == d.c5_gaps and all(pd.notna(x) for x in gaps)
          and all(a <= b for a, b in zip(gaps, gaps[1:])) and gaps[0] < gaps[-1])
    votes = [c1, c2, c3, c4, bool(c5)]
    n = sum(votes)
    prev_lost = bool(results and results[0] == 0)
    recent_loss = any(r == 0 for r in results[:d.recent_games])
    level = ('strong' if n >= d.strong_votes else 'weak' if n == 1 or prev_lost
             else 'none' if not recent_loss else 'stale')
    return dict(L=run, D=load, rating_delta=delta, c5_recency_seconds=recency,
                **{f'C{i}': bool(v) for i, v in enumerate(votes, 1)}, n_C=n,
                prev_lost=prev_lost, recent_loss=recent_loss, level=level)


def reference_indices(group, row, variant='v3', d=DESIGN):
    """Last games by start time, strictly completed before the target start."""
    candidates = group[(group.end_upper_ms < row['start_ms']) & group.speed.eq(row['speed'])]
    bucket = candidates[candidates.plies.lt(d.short_plies).eq(row['plies'] < d.short_plies)]
    if len(bucket) >= d.bucket_min:
        return bucket.tail(d.history_cap).index, 'bucketed'
    minimum = d.pooled_min if variant == 'v3' else d.fallback_min
    if len(candidates) >= minimum:
        return candidates.tail(d.history_cap).index, 'pooled'
    return group.index[:0], 'none'


def baseline(row, reference, kind, variant='v3', d=DESIGN):
    """The robust/score_baseline formula, vectorised over seven feature columns."""
    out = dict(baseline_kind=kind, baseline_games=len(reference),
               baseline_latest_end_ms=reference.end_upper_ms.max() if len(reference) else np.nan)
    matrix = reference[list(FEATURES)].to_numpy(dtype=float)
    # Small matrices (<=200 x 7); no fitting and no temporal imputation.
    for j, (name, floor) in enumerate(d.floors):
        values = matrix[:, j]
        values = values[np.isfinite(values)]
        count = len(values)
        median = float(np.median(values)) if count >= d.feature_min else np.nan
        mad = float(np.median(np.abs(values - median))) if pd.notna(median) else np.nan
        value = row[name]
        z = ((value - median) / max(d.mad_scale * mad, floor)
             if pd.notna(value) and pd.notna(median) else np.nan)
        out.update({f'baseline_{name}_count': count, f'baseline_{name}_median': median,
                    f'baseline_{name}_mad': mad, f'z_{name}': z})
        if variant == 'v3b':
            for suffix, q in (('p20', d.low_quantile), ('p80', d.high_quantile)):
                out[f'{name}_{suffix}'] = (float(np.quantile(values, q, method='linear'))
                                          if count >= d.feature_min else np.nan)
    out['z_cpl'] = out['z_cpl_mean_w300']
    out['cpl_above_reference'] = (row['cpl_mean_w300'] - out['baseline_cpl_mean_w300_median'])
    return out


def e6(row, terminal, d=DESIGN):
    """terminal: last ply, then penultimate; evaluations are mover POV."""
    if row['result_score'] != 0:
        return 'not_fired', np.nan
    clock = row.get('last_clock_seconds', np.nan)
    tc_known = pd.notna(row['initial_seconds']) and pd.notna(row['increment_seconds'])
    b = (row['status'] == 'timeout' or
         (row['status'] == 'outoftime' and tc_known and pd.notna(clock)
          and clock >= d.timeout_clock_fraction * row['initial_seconds']))
    chance = np.nan
    if row['status'] == 'resign':
        for position in terminal:
            cp, mate = position['eval_after_cp'], position['eval_after_mate']
            if pd.notna(cp) or pd.notna(mate):
                sign = 1 if position['color'] == row['color'] else -1
                chance = win_percent(sign * cp if pd.notna(cp) else None,
                                     sign * mate if pd.notna(mate) else None)
                break
    if b or (pd.notna(chance) and chance >= d.resign_win_percent):
        return 'fired', chance
    return ('missing' if row['status'] == 'resign' and pd.isna(chance) else 'not_fired'), chance


def e7(row, nxt, prior_gaps, d=DESIGN):
    q20 = (float(np.quantile(prior_gaps[-d.history_cap:], d.gap_quantile, method='linear'))
           if len(prior_gaps) >= d.gap_min else np.nan)
    gap = ((nxt['start_ms'] - row['end_ms']) / 1000
           if nxt is not None and pd.notna(row['end_ms']) else np.nan)
    if row['result_score'] != 0:
        return 'not_fired', q20, gap
    # Explicit missing clauses take precedence, including the collection edge.
    if nxt is None or pd.isna(row['end_ms']) or pd.isna(q20):
        return 'missing', q20, gap
    if nxt['session_id'] != row['session_id']:
        return 'not_fired', q20, gap
    return ('fired' if gap <= min(q20, d.requeue_seconds) else 'not_fired'), q20, gap


def evidence(row, variant='v3', d=DESIGN):
    out = {}
    names = FEATURES[:4]
    for i, name in enumerate(names, 1):
        if variant == 'v3':
            value = row['z_' + name]
            fired = value <= -d.z_threshold if i == 3 else value >= d.z_threshold
            known = pd.notna(value)
        else:
            value = row[name]
            threshold = row[name + ('_p20' if i == 3 else '_p80')]
            known = pd.notna(value) and pd.notna(threshold)
            fired = value <= threshold if i == 3 else value >= threshold
        out[f'E{i}'] = 'missing' if not known else 'fired' if fired else 'not_fired'
    zs = [row['z_' + name] for name in FEATURES[4:]]
    score = float(np.mean(zs)) if all(pd.notna(x) for x in zs) else np.nan
    out['aggression_score'] = score
    if variant == 'v3':
        known, fired = pd.notna(score), score >= d.z_threshold
    else:
        known = all(pd.notna(row[name]) and pd.notna(row[name + '_p80']) for name in FEATURES[4:])
        fired = sum(row[name] >= row[name + '_p80'] for name in FEATURES[4:]) >= d.aggression_votes
    out['E5'] = 'missing' if not known else 'fired' if fired else 'not_fired'
    return out


def combine(row, variant='v3', d=DESIGN):
    reason = ('short_game' if row['own_moves'] < d.own_min else
              'no_eval' if row['eval_moves'] < d.eval_min else
              'no_baseline' if pd.isna(row['z_cpl']) else '')
    if reason:
        return dict(eligible=False, label='ABSTAIN', abstain_reason=reason)
    positive = row['z_cpl'] > 0 if variant == 'v3' else row['cpl_above_reference'] > 0
    tilt = (positive and ((row['level'] == 'strong' and row['n_fired'] >= d.strong_evidence)
                         or (row['level'] == 'weak' and row['n_fired'] >= d.weak_evidence)))
    if row['result_score'] == 1:
        tilt = (tilt and row['level'] == 'strong' and row['n_fired'] >= d.won_evidence
                and (row['E1'] == 'fired' or row['E2'] == 'fired'))
    negative = (row['n_fired'] + row['n_missing'] <= d.not_max
                and (row['level'] == 'none' or not positive))
    assert not (tilt and negative)
    label = 'TILT' if tilt else 'NOT' if negative else 'ABSTAIN'
    return dict(eligible=True, label=label, abstain_reason='combination' if label == 'ABSTAIN' else '')


def label_train(games, targets, terminals, variant='v3', d=DESIGN):
    """Never evaluate an E, combination, or reference for a non-train target."""
    train_only(targets)
    target_keys = set(map(tuple, targets[KEYS].to_numpy()))
    rows = []
    for _, group in games.groupby('player_id', sort=False):
        group = group.sort_values(['start_ms', 'game_id']).copy()
        # Gaps are exact only within an existing session, using true end_ms.
        previous_end = group.end_ms.shift(1)
        same_session = group.session_id.eq(group.session_id.shift(1))
        group['exact_gap'] = ((group.start_ms - previous_end) / 1000).where(same_session)
        entries = group.to_dict('records')
        session_history, previous_gaps = {}, []
        for i, source in enumerate(entries):
            prior = [p for p in session_history.get(source['session_id'], [])
                     if p['start_ms'] < source['start_ms']]
            if (source['game_id'], source['color']) in target_keys:
                ref_index, kind = reference_indices(group, source, variant, d)
                # Do not export internal username, raw IDs, session identifiers.
                keep = KEYS + ['player_id', 'plies', 'rating', 'result_score', 'status',
                               'initial_seconds', 'increment_seconds', 'own_moves', 'eval_moves',
                               'think_count', 'last_clock_seconds', 'exact_gap'] + list(FEATURES)
                row = {k: source.get(k, np.nan) for k in keep}
                row['split'] = 'train'
                row.update(context(source, list(reversed(prior)), d))
                row.update(baseline(source, group.loc[ref_index], kind, variant, d))
                row.update(evidence(row, variant, d))
                row['E6'], row['final_win_percent'] = e6(source, terminals.get(source['raw_game_id'], []), d)
                row['E7'], row['gap_q20_seconds'], row['next_gap_seconds'] = e7(
                    source, entries[i + 1] if i + 1 < len(entries) else None, previous_gaps, d)
                row['n_fired'] = sum(row[e] == 'fired' for e in EVIDENCE)
                row['n_missing'] = sum(row[e] == 'missing' for e in EVIDENCE)
                row.update(combine(row, variant, d))
                rows.append(row)
            session_history.setdefault(source['session_id'], []).append(source)
            if pd.notna(source['exact_gap']):
                previous_gaps.append(source['exact_gap'])
    result = targets[KEYS].merge(pd.DataFrame(rows), on=KEYS, validate='one_to_one')
    assert len(result) == len(targets)
    train_only(result)
    return result


def auc(y, values):
    mask = y.notna() & values.notna()
    return float(roc_auc_score(y[mask], values[mask])) if y[mask].nunique() == 2 else None


def length_buckets(frame, d=DESIGN):
    """Merge a sparse bucket with its lower neighbour (first: upper)."""
    groups = [dict(name='short', frame=frame[frame.plies < d.short_plies]),
              dict(name='40–79', frame=frame[(frame.plies >= d.short_plies) & (frame.plies < d.long_plies)]),
              dict(name='80+', frame=frame[frame.plies >= d.long_plies])]
    merges = []
    while len(groups) > 1:
        i = next((i for i, g in enumerate(groups) if len(g['frame']) < d.length_bucket_min), None)
        if i is None:
            break
        j = i - 1 if i else 1
        lo, hi = sorted([i, j])
        name = groups[lo]['name'] + '+' + groups[hi]['name']
        merges.append(f"{groups[i]['name']} ({len(groups[i]['frame'])}) into {groups[j]['name']}")
        groups[lo:hi + 1] = [dict(name=name, frame=pd.concat([groups[lo]['frame'], groups[hi]['frame']]))]
    buckets = {g['name']: dict(labelled=len(g['frame']),
                              tilt_share=float(g['frame'].label.eq('TILT').mean()) if len(g['frame']) else None)
               for g in groups}
    shares = [g['tilt_share'] for g in buckets.values() if g['tilt_share'] is not None]
    return dict(buckets=buckets, merges=merges, gap=max(shares) - min(shares) if shares else None)


def gates(frame, d=DESIGN):
    train_only(frame)
    labelled = frame[frame.label.ne('ABSTAIN')]
    tilt = frame[frame.label.eq('TILT')]
    length_auc = auc(labelled.label.eq('TILT'), labelled.plies)
    symmetric_auc = max(length_auc, 1 - length_auc) if length_auc is not None else None
    lengths = length_buckets(labelled, d)
    dominance = {e: float(tilt[e].eq('fired').mean()) if len(tilt) else None for e in EVIDENCE}
    eligible = frame[frame.eligible]
    run_bucket = eligible.L.clip(upper=d.run_last_bin)
    strata = {str(i): dict(rows=int(run_bucket.eq(i).sum()),
                          share=float(eligible.loc[run_bucket.eq(i), 'n_fired'].ge(d.monotone_evidence).mean())
                          if run_bucket.eq(i).any() else None) for i in range(d.run_last_bin + 1)}
    shares = [s['share'] for s in strata.values()]
    monotone = (all(x is not None for x in shares)
                and shares[-1] - shares[0] >= d.monotone_rise_min
                and all(b >= a - d.monotone_slack for a, b in zip(shares, shares[1:])))
    coverage = float(frame.label.ne('ABSTAIN').mean()) if len(frame) else None
    post = frame[frame.prev_lost]
    post_coverage = float(post.label.ne('ABSTAIN').mean()) if len(post) else None
    prevalence = float(labelled.label.eq('TILT').mean()) if len(labelled) else None
    won = float(tilt.result_score.eq(1).mean()) if len(tilt) else None
    def maximum(value, limit):
        return value is not None and value <= limit
    def minimum(value, limit):
        return value is not None and value >= limit
    result = dict(
        G1=dict(value=symmetric_auc, raw_auc=length_auc, passed=maximum(symmetric_auc, d.length_auc_max)),
        G2=dict(value=lengths['gap'], **{k: v for k, v in lengths.items() if k != 'gap'},
                passed=maximum(lengths['gap'], d.length_gap_max)),
        G3a=dict(value=coverage, rows=len(frame), labelled=len(labelled), passed=minimum(coverage, d.coverage_min)),
        G3b=dict(value=post_coverage, rows=len(post), labelled=int(post.label.ne('ABSTAIN').sum()),
                 passed=minimum(post_coverage, d.coverage_min)),
        G4=dict(value=prevalence, passed=minimum(prevalence, d.prevalence_min) and maximum(prevalence, d.prevalence_max)),
        G5=dict(value=won, tilt=len(tilt), won_tilt=int(tilt.result_score.eq(1).sum()), passed=maximum(won, d.won_max)),
        G6=dict(value=max(dominance.values()) if all(x is not None for x in dominance.values()) else None,
                by_evidence=dominance, passed=all(maximum(x, d.dominance_max) for x in dominance.values())),
        G7=dict(value=shares[-1] - shares[0] if all(x is not None for x in shares) else None,
                strata=strata, passed=bool(monotone)))
    return result


def counts(values):
    return {str(k): int(v) for k, v in values.value_counts(dropna=False).sort_index().items()}


def report_stats(frame, v1):
    train_only(frame)
    labelled = frame[frame.label.ne('ABSTAIN')]
    rating_edges = np.quantile(frame.rating.dropna(), [1 / 3, 2 / 3], method='linear')
    tercile = pd.Series(np.select([frame.rating <= rating_edges[0], frame.rating <= rating_edges[1]],
                                 ['low', 'middle'], default='high'), index=frame.index)
    tercile[frame.rating.isna()] = 'missing'
    tc = frame.initial_seconds.map(lambda v: f'{v:g}' if pd.notna(v) else '?') + '+' + frame.increment_seconds.map(
        lambda v: f'{v:g}' if pd.notna(v) else '?')
    def breakdown(groups):
        return {str(k): counts(g.label) for k, g in frame.groupby(groups, sort=True)}
    abstain = frame[frame.label.eq('ABSTAIN')]
    reasons = {k: dict(rows=v, share_of_abstain=v / len(abstain), share_of_all=v / len(frame))
               for k, v in counts(abstain.abstain_reason).items()}
    baseline_kinds = {k: {b: dict(rows=int(g.baseline_kind.eq(b).sum()), share=float(g.baseline_kind.eq(b).mean()))
                           for b in ('bucketed', 'pooled', 'none')} for k, g in frame.groupby('label')}
    # v1 was read with a train predicate; the current frame is also train only.
    joint = labelled.merge(v1[KEYS + ['weak_tilt_label']], on=KEYS, validate='one_to_one')
    joint = joint[joint.weak_tilt_label.notna()]
    y = joint.label.eq('TILT').astype(int)
    agreement = dict(joint_labelled=len(joint), source='v1 by_player train intersect this split train',
                     agreement=float(y.eq(joint.weak_tilt_label).mean()) if len(joint) else None,
                     kappa=float(cohen_kappa_score(y, joint.weak_tilt_label)) if len(joint) else None,
                     confusion={f'v3_{a}_v1_{b}': int((y.eq(a) & joint.weak_tilt_label.eq(b)).sum())
                                for a in (0, 1) for b in (0, 1)})
    return dict(rows=len(frame), labels=counts(frame.label),
                votes={c: counts(frame[c]) for c in [f'C{i}' for i in range(1, 6)] + list(EVIDENCE)},
                n_fired=counts(frame.n_fired), n_missing=counts(frame.n_missing), context=counts(frame.level),
                rating_edges=rating_edges.tolist(), by_rating=breakdown(tercile), by_time_control=breakdown(tc),
                result_auc=auc(labelled.label.eq('TILT'), labelled.result_score), agreement_v1=agreement,
                abstain_reasons=reasons, baseline_kind_by_label=baseline_kinds)


def select_variant(all_gates):
    def failures(variant, split):
        return sum(not g['passed'] for g in all_gates[variant][split].values())
    return min(all_gates, key=lambda v: (failures(v, 'by_player'), failures(v, 'by_time'), v != 'v3'))


def json_write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def run(data, aligned_dir, out, prereg, lock, d=DESIGN):
    started = time.monotonic()
    prereg, lock, out = Path(prereg), Path(lock), Path(out)
    before = hashlib.sha256(prereg.read_bytes()).hexdigest()
    require(before == lock.read_text().split()[0], 'Pre-registration lock mismatch')
    games, aligned, checks = load_inputs(data, aligned_dir, d)
    # Subset targets before any evidence computation; every target is train in
    # at least one split, and each split is later scored on its own train only.
    targets = pd.concat([a[a.split.eq('train')][KEYS + ['split']] for a in aligned.values()]).drop_duplicates(KEYS)
    train_only(targets)
    print('Preflight passed; loading selected move columns.', flush=True)
    move_cols = ['game_id', 'color', 'ply', 'cpl', 'judgement', 'think_seconds', 'risk', 'attack',
                 'sacrifice_heuristic', 'eval_after_cp', 'eval_after_mate', 'clock_seconds']
    moves = pd.read_parquet(Path(data) / 'processed/features/moves.parquet', columns=move_cols)
    moves = moves[moves.game_id.isin(games.raw_game_id.unique())]
    # Use the actual final/penultimate game ply, never an arbitrarily earlier eval.
    terminal_moves = moves.merge(games[['raw_game_id', 'plies']].drop_duplicates(),
                                 left_on='game_id', right_on='raw_game_id', validate='many_to_one')
    terminal_moves = terminal_moves[(terminal_moves.ply == terminal_moves.plies)
                                    | (terminal_moves.ply == terminal_moves.plies - 1)]
    terminals = {gid: group.sort_values('ply', ascending=False)[
        ['color', 'eval_after_cp', 'eval_after_mate']].to_dict('records')
                 for gid, group in terminal_moves.groupby('game_id', sort=False)}
    del terminal_moves
    clock = moves[moves.clock_seconds.notna()].sort_values('ply').groupby(['game_id', 'color'], sort=False).tail(1)
    games = games.merge(clock[['game_id', 'color', 'clock_seconds']].rename(
        columns={'game_id': 'raw_game_id', 'clock_seconds': 'last_clock_seconds'}),
                        on=['raw_game_id', 'color'], how='left', validate='one_to_one')
    del clock
    games = aggregates(games, moves, d)
    del moves
    # Read only the expressly permitted v1 train values, with column projection.
    v1 = pd.read_parquet(Path(data) / 'processed/out/weak_by_player.parquet',
                         columns=KEYS + ['weak_tilt_label', 'split'], filters=[('split', '==', 'train')])
    train_only(v1)
    elapsed = time.monotonic() - started
    require(elapsed < d.runtime_limit_seconds / 2, 'Preparation suggests a run exceeding 20 minutes')
    all_gates, all_stats = {}, {}
    out.mkdir(parents=True, exist_ok=True)
    for variant in ('v3', 'v3b'):
        print(f'Computing {variant} on the union of train targets only.', flush=True)
        labels = label_train(games, targets, terminals, variant, d)
        all_gates[variant], all_stats[variant] = {}, {}
        suffix = '' if variant == 'v3' else '_v3b'
        lf_rows = []
        for split, a in aligned.items():
            train = a[a.split.eq('train')][KEYS]
            frame = train.merge(labels, on=KEYS, validate='one_to_one')
            assert len(frame) == len(train)
            all_gates[variant][split] = gates(frame, d)
            all_stats[variant][split] = report_stats(frame, v1)
            frame.to_parquet(out / f'labels_{split}_train{suffix}.parquet', index=False, compression='zstd')
            for lf, votes in all_stats[variant][split]['votes'].items():
                for state, count in votes.items():
                    lf_rows.append(dict(split=split, lf=lf, state=state, rows=count, share=count / len(frame)))
        json_write(out / f'gates{suffix}.json', dict(variant=variant, design_hash=d.hash,
                   gates=all_gates[variant], report_only=all_stats[variant], rating_check=checks))
        pd.DataFrame(lf_rows).to_csv(out / f'lf_stats{suffix}.csv', index=False)
        (out / f'design_hash{suffix}.txt').write_text(d.hash + '\n')
        if variant == 'v3' and all(g['passed'] for s in all_gates[variant].values() for g in s.values()):
            break
        print(f'{variant} finished in {time.monotonic() - started:.1f}s total.', flush=True)
    selected = select_variant(all_gates)
    after = hashlib.sha256(prereg.read_bytes()).hexdigest()
    require(after == before, 'Pre-registration changed during run')
    summary = dict(selected=selected, gates=all_gates, report_only=all_stats,
                   rating_check=checks, prereg_before=before, prereg_after=after,
                   design_hash=d.hash, runtime_seconds=time.monotonic() - started,
                   train_union_rows=len(targets))
    json_write(out / 'run_summary.json', summary)
    print(json.dumps(dict(selected=selected, runtime_seconds=summary['runtime_seconds'],
                         failed_gates={v: {s: [k for k, g in gs.items() if not g['passed']]
                                           for s, gs in splits.items()} for v, splits in all_gates.items()})), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=Path('data'))
    parser.add_argument('--aligned', type=Path, default=Path.home() / 'tilt-phase1/aligned')
    parser.add_argument('--out', type=Path, default=Path.home() / 'tilt-labels-v3/S1')
    parser.add_argument('--prereg', type=Path, default=Path('reports/label_v3_preregistration.md'))
    parser.add_argument('--lock', type=Path, default=Path.home() / 'tilt-labels-v3/prereg.sha256')
    args = parser.parse_args()
    run(args.data, args.aligned, args.out, args.prereg, args.lock)


if __name__ == '__main__':
    main()
