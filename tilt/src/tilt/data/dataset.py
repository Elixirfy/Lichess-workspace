"""Human-label joins, privacy transform, leakage audits and deterministic splits."""
from collections import Counter
import hashlib
import json
from pathlib import Path

import pandas as pd

from . import storage
from ..features.features import aggregate, compute, mean, std, robust, MOVE_BASELINES
from ..labels.labels import database, pseudonym, private_id


def _read_features(data, name):
    return pd.read_parquet(Path(data) / 'processed' / 'features' / f'{name}.parquet')


def _safe_export(row):
    result = dict(row)
    player = result.pop('player', None)
    if player is not None:
        result['player_id'] = pseudonym(player)
    # OAuth annotators are already pseudonymous; a second export HMAC also
    # protects legacy or externally imported human annotator identifiers.
    if result.get('annotator_id') is not None:
        result['annotator_id'] = pseudonym(result['annotator_id'])
    for key, namespace in (('game_id', 'game:'), ('session_id', 'session:')):
        if result.get(key) is not None:
            result[key] = private_id(namespace + result[key])
    for key in ('opponent', 'opponent_id', 'previous_game_id', 'game_ids'):
        result.pop(key, None)
    return result


def _split_player(pid, validation_fraction=.1):
    value = int(hashlib.sha256(('player-split-v1:' + pid).encode()).hexdigest()[:8], 16) / 2**32
    return 'test' if value < .2 else 'validation' if value < .2 + validation_fraction else 'train'


def _card(frame, unmatched, splits, data):
    lines = ['# Tilt dataset data card', '',
        'Section 2.3 only. No model has been trained. All target values are human reports.', '',
        f'Labelled examples: {len(frame)}. Unmatched/invalid-scope labels: {unmatched}.',
        'One row per annotation; repeated annotations remain separate (no silent averaging).',
        'Do not use identifiers, report metadata, questionnaire answers, scope or split as predictors.',
        'Moment features use only target-player moves inside the reported range; no whole-game outcome or post-event window is joined.',
        'Game features are retrospective and available only after the game. Session features are retrospective after the entire session.',
        'Raw data and answers are personal data. Exported game/session ids use domain-separated salted HMAC-SHA256; no raw ids, opponent usernames or previous-game ids are exported. Timing and behaviour can still reidentify participants; pseudonymisation is not anonymity.',
        'Draft questionnaire, selection bias, inconsistent engine budgets in source evals, and unvalidated style heuristics limit interpretation.',
        'Missing baselines mean insufficient strictly prior context; unknown dump end times exclude those games from history.', '',
        '## Counts', '']
    config = json.loads((Path(data) / 'processed' / 'features' / 'manifest.json').read_text())
    lines.extend([f"Maximum baseline history: {config['max_history_games']} most recent eligible prior games per player/speed (ordered by end time), including normal CPL and session baselines.", ''])
    imported = storage.read(data, 'games')
    feature_games = _read_features(data, 'games')
    lines.extend([f'Imported games: {len(imported)}; player-game feature rows: {len(feature_games)}.', ''])
    for name, values in (
        ('Imported games by speed', imported.speed.fillna('missing').astype(str)),
        ('Imported player-games by rating band', feature_games.rating.map(
            lambda r: f'{int(r // 200) * 200}–{int(r // 200) * 200 + 199}' if pd.notna(r) else 'missing')
            if 'rating' in feature_games else pd.Series(dtype='str'))):
        lines.extend([f'### {name}', '', '| Value | Count |', '|---|---:|'])
        lines.extend(f'| {value} | {count} |' for value, count in sorted(Counter(values).items()))
        lines.append('')
    for column in ('speed', 'rating_band', 'label_source', 'scope'):
        lines.extend([f'### {column}', '', '| Value | Count |', '|---|---:|'])
        counts = Counter(frame[column].fillna('missing').astype(str)) if column in frame else Counter()
        if column == 'label_source':
            for source in ('self_report', 'expert', 'participant_verified'):
                counts.setdefault(source, 0)
        for value, count in sorted(counts.items()):
            lines.append(f'| {value} | {count} |')
        lines.append('')
    for name, split in splits.items():
        lines.extend([f'### Split: {name}', '', '| Partition | Count |', '|---|---:|'])
        counts = Counter(split['split'])
        for partition in ('train', 'validation', 'test'):
            counts.setdefault(partition, 0)
        for partition, count in sorted(counts.items()):
            lines.append(f'| {partition} | {count} |')
        lines.append('')
    lines.extend(['## Missingness', '', '| Column | Missing | Fraction |', '|---|---:|---:|'])
    for col in sorted(frame):
        count = int(frame[col].isna().sum())
        lines.append(f'| {col} | {count} | {count / len(frame) if len(frame) else 0:.4f} |')
    lines.extend(['', '## Source player-game feature missingness', '', '| Column | Missing | Fraction |', '|---|---:|---:|'])
    for col in sorted(feature_games):
        count = int(feature_games[col].isna().sum())
        lines.append(f'| {col} | {count} | {count / len(feature_games) if len(feature_games) else 0:.4f} |')
    lines.extend(['', '## Leakage and splits', '',
        'History eligibility: same player and end_upper_ms < game start_ms. Move baselines also match speed, clock pressure and advantage.',
        'Player split: stable hash buckets 70% train / 10% validation / 20% test; target players are disjoint. Shared games across buckets are purged from train/validation.',
        'Time split: explicit cutoffs or 80th/90th percentiles of unique scope start times. Scopes crossing a cutoff are purged. Unknown end bounds are excluded.',
        'Chronologically available unlabelled personal history is permitted for held-out players and later test games. Label values never enter a baseline.',
        'Fractions are approximate, especially for small cohorts. Splits with zero examples are possible.',
        'See manifest.json for configuration, predictor allowlists, engine budget and exact time cutoffs.'])
    (Path(data) / 'processed' / 'out' / 'DATACARD.md').write_text('\n'.join(lines) + '\n')


def build_dataset(data, time_validation_ms=None, time_test_ms=None):
    data = Path(data)
    manifest_path = data / 'processed' / 'features' / 'manifest.json'
    config = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    # Rebuild from normalized inputs instead of trusting potentially stale baselines.
    compute(data, config.get('window_plies', 12), config.get('min_prior_games', 5), config.get('session_gap_minutes', 30), config.get('max_history_games', 200))
    games, moves, sessions = (_read_features(data, n) for n in ('games', 'moves', 'sessions'))
    for frame in (games, moves):
        if not frame.empty and 'baseline_latest_end_ms' in frame:
            invalid = frame.baseline_latest_end_ms.notna() & (frame.baseline_latest_end_ms >= frame.start_ms)
            if invalid.any():
                raise ValueError('Leakage audit failed: baseline includes a non-prior game')
    with database(data) as conn:
        labels = [dict(row) for row in conn.execute('SELECT * FROM labels ORDER BY label_id')]
    game_rows = storage.records(games)
    source_games = {g['game_id']: g for g in storage.records(storage.read(data, 'games'))}
    game_lookup = {(pseudonym(g['player']), g['game_id']): g for g in game_rows}
    session_lookup = {(pseudonym(s['player']), s['session_id']): s for s in storage.records(sessions)}
    examples, membership, unmatched = [], [], 0
    for label in labels:
        pid = label['player_id']
        base = None
        scope = label['scope']
        if scope in ('game', 'moment'):
            game = game_lookup.get((pid, label['game_id']))
            if game:
                if scope == 'game':
                    base = dict(game)
                    # Current result is not a behavioural input. Past results remain cross-game features.
                    base.pop('result_score', None)
                else:
                    subset = moves[(moves.player == game['player']) & (moves.game_id == game['game_id']) &
                        (moves.ply >= label['ply_start']) & (moves.ply <= label['ply_end'])]
                    if not subset.empty and label['ply_start'] >= 1:
                        nplies = source_games[game['game_id']]['plies']
                        if label['ply_end'] <= nplies:
                            own = storage.records(subset)
                            base = dict(player=game['player'], opponent=game['opponent'], game_id=game['game_id'],
                                session_id=game['session_id'], start_ms=game['start_ms'], end_upper_ms=game['end_upper_ms'],
                                speed=game['speed'], rating=game['rating'], rating_difference=game['rating_difference'],
                                **aggregate(own))
                            for feature in MOVE_BASELINES:
                                base[f'deviation_{feature}_z'] = mean([r[f'deviation_{feature}_z'] for r in own])
                            base['behavioral_deviation_score'] = mean([r['behavioral_deviation_score'] for r in own])
                ids = {label['game_id']}
        else:
            session = session_lookup.get((pid, label['session_id']))
            if session:
                session_ids = set(json.loads(session['game_ids']))
                gs = [g for g in game_rows if g['player'] == session['player'] and g['game_id'] in session_ids]
                # A later game can extend an inactivity-defined session after its rating.
                # Freeze the labelled scope at report time instead of joining future play.
                gs = [g for g in gs if g['start_ms'] is not None and g['start_ms'] <= label['report_ms']
                    and (g['end_upper_ms'] if g['end_upper_ms'] is not None else source_games[g['game_id']]['observed_ms']) <= label['report_ms']]
                if not gs:
                    unmatched += 1
                    continue
                ids = {g['game_id'] for g in gs}
                base = dict(player=session['player'], session_id=session['session_id'],
                    start_ms=min(g['start_ms'] for g in gs),
                    end_upper_ms=max(g['end_upper_ms'] for g in gs) if all(g['end_upper_ms'] is not None for g in gs) else None,
                    game_count=len(gs), mean_cpl=mean([g['mean_cpl'] for g in gs]),
                    mean_think=mean([g['mean_think'] for g in gs]), mean_accuracy=mean([g['mean_accuracy'] for g in gs]),
                    risk_rate=mean([g['risk_rate'] for g in gs]),
                    cpl_volatility=std([g['mean_cpl'] for g in gs]))
                base['speed'] = gs[0]['speed'] if len({g['speed'] for g in gs}) == 1 else 'mixed'
                base['rating'] = mean([g['rating'] for g in gs])
                # Session deviation uses only history before the session began, not later games in it.
                prior = [g for g in game_rows if g['player'] == session['player'] and
                    g['end_upper_ms'] is not None and base['start_ms'] is not None and
                    g['end_upper_ms'] < base['start_ms'] and g['speed'] == base['speed']]
                prior = sorted(prior, key=lambda g: (g['end_upper_ms'], g['game_id']))[-config.get('max_history_games', 200):]
                from ..features.features import GAME_BASELINES
                base.update(robust(base, prior, {k: v for k, v in GAME_BASELINES.items() if k in base}, config.get('min_prior_games', 5)))
        if base is None:
            unmatched += 1
            continue
        rating = base.get('rating')
        base.update(scope=scope, ply_start=label['ply_start'], ply_end=label['ply_end'],
            label_id=label['label_id'], target_tilt=label['tilt_score'], label_source=label['source'],
            annotator_id=label['annotator_id'], report_timestamp=label['report_timestamp'],
            report_delay_seconds=label['delay_seconds'], consent_version=label['consent_version'])
        base['rating_band'] = f'{int(rating // 200) * 200}–{int(rating // 200) * 200 + 199}' if rating is not None else 'missing'
        exported = _safe_export(base)
        # Keep the target player pseudonym used by the consent/label store.
        exported['player_id'] = pid
        examples.append(exported)
        membership.append(ids)
    frame = pd.DataFrame(examples) if examples else pd.DataFrame(columns=['player_id', 'scope', 'speed', 'rating_band', 'label_source', 'start_ms', 'end_upper_ms', 'label_id', 'target_tilt'])
    by_player = frame.copy()
    by_player['split'] = by_player.player_id.map(_split_player)
    test_ids = set().union(*(ids for ids, partition in zip(membership, by_player.split) if partition == 'test'))
    validation_ids = set().union(*(ids for ids, partition in zip(membership, by_player.split) if partition == 'validation'))
    for index, (ids, partition) in enumerate(zip(membership, by_player.split)):
        if (partition == 'train' and ids & (test_ids | validation_ids)) or (partition == 'validation' and ids & test_ids):
            by_player.loc[index, 'split'] = 'purged_shared_game'
    starts = sorted(set(int(x) for x in frame.start_ms.dropna()))
    validation = time_validation_ms if time_validation_ms is not None else starts[min(len(starts) - 1, int(.8 * len(starts)))] if starts else None
    test = time_test_ms if time_test_ms is not None else starts[min(len(starts) - 1, int(.9 * len(starts)))] if starts else None
    if validation is not None and test is not None and validation > test:
        raise ValueError('Validation cutoff must not be after test cutoff')
    def time_split(row):
        if pd.isna(row.start_ms) or pd.isna(row.end_upper_ms) or validation is None:
            return 'excluded_unknown_end'
        if row.end_upper_ms < validation:
            return 'train'
        if row.start_ms >= test:
            return 'test'
        if row.start_ms >= validation and row.end_upper_ms < test:
            return 'validation'
        return 'purged_crossing_cutoff'
    by_time = frame.copy()
    by_time['split'] = by_time.apply(time_split, axis=1) if not by_time.empty else pd.Series(dtype='str')
    output = data / 'processed' / 'out'
    storage.write_frame(output / 'labelled.parquet', frame)
    storage.write_frame(output / 'by_player.parquet', by_player)
    storage.write_frame(output / 'by_time.parquet', by_time)
    metadata = {'label_id', 'player_id', 'opponent_id', 'game_id', 'session_id', 'scope', 'ply_start', 'ply_end',
        'start_ms', 'end_ms', 'end_upper_ms', 'baseline_latest_end_ms', 'target_tilt', 'label_source', 'annotator_id',
        'report_timestamp', 'report_delay_seconds', 'consent_version', 'end_kind', 'color', 'speed', 'rating_band'}
    predictors = [c for c in frame.select_dtypes(include=['number', 'bool']).columns if c not in metadata]
    (output / 'manifest.json').write_text(json.dumps(dict(version=1,
        target='target_tilt', predictor_columns=predictors, categorical_predictors=['speed', 'rating_band'],
        time_validation_ms=validation, time_test_ms=test, unmatched_labels=unmatched,
        features=json.loads((data / 'processed' / 'features' / 'manifest.json').read_text())), indent=2))
    _card(frame, unmatched, {'by_player': by_player, 'by_time': by_time}, data)
    return {'examples': len(frame), 'unmatched_labels': unmatched, 'output': str(output)}
