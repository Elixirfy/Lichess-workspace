"""Local-only game scores and causal, exploratory prefix timelines."""
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from ..data import storage
from ..data.dataset import _safe_export
from ..evaluation.evaluate import contributions
from ..features.features import aggregate, robust, GAME_BASELINES
from ..labels.labels import private_id
from ..features.model_features import prepare, assert_no_lf_inputs, passes_audits
from ..features.behavior import DYNAMICS, FLAGS, game_dynamics
from ..labels.weak_labels import WEAK_VERSION
from . import deployment
from ..training.train import predict_bundle


def dynamics(moves):
    """Phase 2 within-game dynamics (attack_trend_3w, ...) from the player's own moves, one row per game."""
    return game_dynamics(moves[['player', 'game_id', 'ply', *FLAGS]]).drop(columns='player')


def band(score):
    value = int(np.clip(np.floor(score + .5), 0, 100))
    return '0–25' if value <= 25 else '26–50' if value <= 50 else '51–75' if value <= 75 else '76–100'


def prefix_snapshot(game, moves, prior, config):
    """Never copy a current whole-game aggregate into an earlier prediction."""
    context = ('player', 'opponent', 'game_id', 'session_id', 'start_ms', 'end_upper_ms', 'speed',
               'rating', 'opponent_rating', 'rating_difference', 'initial_seconds', 'increment_seconds',
               'games_in_session_before', 'losing_streak_before', 'rest_gap_seconds', 'immediate_after_loss',
               'rematch', 'rematch_streak_before', 'recent_form', 'history_games', 'baseline_speed_games')
    row = {c: game.get(c) for c in context}
    own = storage.records(moves.sort_values('ply'))
    row.update(aggregate(own))
    for phase in ('opening', 'middlegame', 'endgame'):
        values = moves[moves.phase == phase].think_seconds.dropna()
        row[phase + '_think'] = float(values.mean()) if len(values) else np.nan
        row['phase_' + phase + '_fraction'] = float((moves.phase == phase).mean())
    row['phase_speed_change'] = row['endgame_think'] - row['opening_think']
    same_session = prior[prior.session_id == game['session_id']]
    row['style_drift_in_session'] = row['risk_rate'] - same_session.risk_rate.mean() if len(same_session) else np.nan
    history = prior[prior.speed == game['speed']].sort_values(['end_upper_ms', 'game_id']).tail(config['max_history_games'])
    row.update(robust(row, storage.records(history), GAME_BASELINES, config['min_prior_games']))
    prefix = dynamics(moves)
    row.update({c: prefix[c].iloc[0] if len(prefix) else np.nan for c in DYNAMICS})
    return prepare(pd.DataFrame([row]))


def run(data, player, game_id=None, every=12, models=None):
    """models: data root holding models/ and out/ (default: data)."""
    if every < 1:
        raise ValueError('--every-plies must be positive')
    data = Path(data)
    models = Path(models) if models else data
    deployed = deployment.load(models)
    selection = json.loads((models / 'processed/models/selection.json').read_text())
    model_manifest = json.loads((models / 'processed/models/manifest.json').read_text())
    if model_manifest.get('status') != 'complete' or selection.get('training_run_id') != model_manifest.get('training_run_id'):
        raise ValueError('Finish train and rerun evaluate before score')
    selected = deployed[0] if deployed else selection['selected'].get('by_player')
    if not selected:
        raise ValueError('No validation-selected unseen-player model; run evaluate on an adequate cohort')
    weak = json.loads((models / 'processed/out/weak_manifest.json').read_text())
    if weak != model_manifest['weak_manifest']:
        raise ValueError('Weak labels changed since training; rerun train and evaluate')
    if weak.get('version') != WEAK_VERSION:
        raise ValueError('Rebuild features, weak labels, train and evaluate on the compute machine')
    if weak['salt_fingerprint'] != private_id('tilt-weak-model-salt-v1'):
        raise ValueError('TILT_SALT differs from model export salt')
    if deployed:
        # Checked against the Phase 5 registries and banned list in deployment.load.
        bundle = deployed[1]
    else:
        bundle = joblib.load(models / 'processed' / 'models' / f'{selected}.joblib')
        assert_no_lf_inputs(bundle['features'], bundle['variant'].startswith('lf_ablated'))
        if not passes_audits(bundle['features'], model_manifest.get('outcome_proxy_audits', {}).get('by_player', []),
                             model_manifest.get('lf_proxy_audits', {}).get('by_player', [])):
            raise ValueError('Selected model did not pass both proxy audits; rerun train and evaluate')
    if 'threshold' not in bundle or 'threshold_source' not in bundle:
        raise ValueError('Model lacks a stored decision threshold; rerun train and evaluate on the compute machine')
    config = json.loads((data / 'processed/features/manifest.json').read_text())
    config.setdefault('max_history_games', 200)
    config.setdefault('min_prior_games', 5)
    all_games = pd.read_parquet(data / 'processed/features/games.parquet')
    own_games = all_games[all_games.player.str.lower() == player.lower()].sort_values(['start_ms', 'game_id'])
    if own_games.empty:
        raise ValueError('No local feature rows for this player')
    if game_id:
        chosen = own_games[own_games.game_id == game_id]
        if chosen.empty:
            raise ValueError('No matching local game for this player')
    else:
        chosen = own_games
    from ..features.model_features import enrich
    enriched = enrich(data, own_games)
    moves = pd.read_parquet(data / 'processed/features/moves.parquet')
    moves = moves[moves.player.str.lower() == player.lower()]
    enriched = enriched.merge(dynamics(moves), on='game_id', how='left', validate='one_to_one')
    results = []
    for game in storage.records(chosen):
        snapshot = enriched[enriched.game_id == game['game_id']]
        game_context = storage.records(snapshot)[0]
        safe = pd.DataFrame([_safe_export(game_context)])
        probability = float(predict_bundle(bundle, safe)[0][0])
        score = 100 * probability
        own = moves[moves.game_id == game['game_id']].sort_values('ply')
        prior = own_games[own_games.end_upper_ms < game['start_ms']]
        endpoints = {int(own[own.ply <= p].ply.max()) for p in range(every, int(own.ply.max()) + 1, every)
                     if (own.ply <= p).any()}
        endpoints.update(own.groupby('phase').ply.max().astype(int))
        endpoints.add(int(own.ply.max()))
        timeline = []
        for ply in sorted(endpoints):
            prefix = own[own.ply <= ply]
            point = prefix_snapshot(game_context, prefix, prior, config)
            prefix_probability = float(predict_bundle(bundle, point)[0][0])
            value = 100 * prefix_probability
            timeline.append(dict(available_after_ply=ply, phase=str(prefix.iloc[-1].phase),
                                 weak_model_tilt_score=value, band=band(value),
                                 weak_model_tilt_flag=bool(prefix_probability >= bundle['threshold']),
                                 behavioral_deviation_score=clean(point.behavioral_deviation_score.iloc[0]),
                                 top_factors=contributions(bundle, point)[0]))
        results.append(dict(game_id=game['game_id'], weak_model_tilt_score=score, band=band(score),
                            weak_model_tilt_flag=bool(probability >= bundle['threshold']),
                            behavioral_deviation_score=clean(game['behavioral_deviation_score']),
                            top_factors=contributions(bundle, safe)[0], timeline=timeline))
    return dict(player=player, model=selected,
                notice='Behavioural proxies, not measured emotions. Score = calibrated weak-label probability × 100. Prefix timelines are exploratory and have no window-level calibration.',
                calibration=bundle['calibration']['status'], threshold=bundle['threshold'],
                threshold_source=bundle['threshold_source'], games=results)


def clean(value):
    return float(value) if pd.notna(value) else None
