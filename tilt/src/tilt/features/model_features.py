"""Explicit causal predictors and conservative LF provenance closure."""
import numpy as np
import pandas as pd
from scipy.stats import rankdata
from sklearn.metrics import roc_auc_score

from ..labels.weak_labels import LFS, LF_INPUT_PREFIX

# Accuracy, CPL, judgements, adverse events and their baselines share engine
# evaluations with current-game LFs. Remove the whole family, including mixed BDS.
QUALITY = ('cpl', 'accuracy', 'wc_loss', 'error', 'mistake', 'blunder', 'adverse',
           'eval', 'advantage', 'recovery', 'unsound', 'realized_sacrifice', 'post_event',
           'material', 'best_second', 'differs_from_best')
HISTORY = ('baseline_', 'deviation_', 'historical_', 'behavioral_deviation_score')
CURRENT_BLOCKED = {c for lf in LFS for c in lf.current}
ALL_LF_COLUMNS = {c for lf in LFS for c in lf.inputs}
RAW_FEATURES = [
    'rating', 'opponent_rating', 'rating_difference', 'initial_seconds', 'increment_seconds',
    'speed_blitz', 'speed_bullet', 'speed_rapid', 'speed_classical', 'speed_correspondence',
    'mean_think', 'think_std', 'tense_think_std', 'mean_think_per_legal_move',
    'risk_rate', 'attack_rate', 'defensive_rate', 'sacrifice_rate', 'style_switch_rate',
    'style_drift_in_session', 'opening_think', 'middlegame_think', 'endgame_think', 'phase_speed_change',
    'clock_missing_fraction', 'rest_gap_seconds', 'rematch', 'rematch_streak_before',
    'games_in_session_before', 'history_games', 'baseline_speed_games',
    'phase_opening_fraction', 'phase_middlegame_fraction', 'phase_endgame_fraction',
]
# Session run reads previous outcomes and rest gaps at this point. These outcome
# relatives are excluded even though they are causal. Kept only in the diagnostic
# losing-streak baseline requested by the research protocol.
CURRENT_RELATIVES = {'losing_streak_before', 'recent_form', 'immediate_after_loss',
                     'cpl_change_after_loss', 'cpl_volatility_after_losses', 'rest_gap_seconds'}


def is_history(column):
    return column.startswith(HISTORY) or column in ('history_games', 'baseline_speed_games')


def forbidden(column, strict=False):
    if column.endswith('_ms') or column == 'deviation_feature_count':
        return True
    if 'clock_fraction' in column or 'think' in column or 'rating' in column:
        return True  # End-clock outcome proxy; timing/rating raw families now read by LFs.
    if column == 'phase_speed_change':
        return True  # Phase means alias the LF's mean-think quantity.
    if column == 'sacrifice_rate':
        return True  # Equal-eval filter / CPL-dependent sacrifice flag.
    if column in ALL_LF_COLUMNS or column in CURRENT_RELATIVES or any(t in column for t in QUALITY):
        return True
    if any(t in column for t in ('rest_gap', 'immediate_after_loss')) or column == 'rating_difference':
        return True
    if column == 'behavioral_deviation_score':
        return True  # Mixed original score contains engine-quality deviations.
    if strict and ('rating' in column or column in ('history_games', 'baseline_speed_games', 'games_in_session_before')):
        return True
    return False


def prepare(frame):
    frame = frame.copy()
    for speed in ('blitz', 'bullet', 'rapid', 'classical', 'correspondence'):
        frame['speed_' + speed] = (frame.speed == speed).astype(float)
    # A separate, declared safe BDS only uses timing and style deviations. Missing
    # personal history remains missing, never a cohort baseline.
    safe = [c for c in frame if c.startswith('deviation_') and c.endswith('_z') and not forbidden(c)]
    frame['behavioral_deviation_score_safe'] = frame[safe].apply(pd.to_numeric, errors='coerce').abs().clip(upper=10).mean(axis=1) * 10 if safe else np.nan
    return frame


def feature_candidates(frame, variant='full'):
    strict = variant.startswith('lf_ablated')
    candidates = RAW_FEATURES + [c for c in frame if c.startswith(('baseline_', 'deviation_', 'historical_'))] + ['behavioral_deviation_score_safe']
    columns = sorted({c for c in candidates if c in frame and not forbidden(c, strict)
                      and not (variant.endswith('no_history') and is_history(c))})
    return columns


def feature_list(frame, variant='full', outcome_audit=None, lf_audit=None):
    columns = feature_candidates(frame, variant)
    outcome_audit = audit_outcome_proxies(frame) if outcome_audit is None else outcome_audit
    lf_audit = audit_lf_proxies(frame) if lf_audit is None else lf_audit
    # Both audits apply to every variant. Unassessed inputs fail closed.
    for audit, flag in ((outcome_audit, 'exclude_strict'), (lf_audit, 'exclude')):
        assessed = {r['feature'] for r in audit if not r[flag]}
        columns = [c for c in columns if c in assessed]
    assert_no_lf_inputs(columns, variant.startswith('lf_ablated'))
    if not columns:
        raise ValueError('No admissible model features')
    return columns


def assert_no_lf_inputs(columns, strict=False):
    touched = ALL_LF_COLUMNS
    bad = set(columns) & touched | {c for c in columns if forbidden(c, strict)}
    if bad:
        raise ValueError('LF provenance leakage into model inputs: ' + ', '.join(sorted(bad)))


def audit_outcome_proxies(frame):
    """Every admissible input, train rows only (including unlabelled history).

    Scores use train-median imputation, as model inputs do. Missing indicators
    are audited too because the model imputer exposes them. Undefined targets
    fail closed for every variant; constants with both target classes get .5.
    """
    train = frame.loc[frame.split == 'train']
    targets = {'lost': train.result_score.eq(0).where(train.result_score.notna()),
               'time_forfeit': train.status.eq('outoftime').where(train.status.notna())}
    result = []
    for col in feature_candidates(frame, 'full'):
        values = pd.to_numeric(train[col], errors='coerce').replace([np.inf, -np.inf], np.nan)
        median = values.median() if values.notna().any() else 0.
        imputed = values.fillna(median)
        row = dict(feature=col, training_rows=len(train))
        for name, target in targets.items():
            known = target.notna()
            y = target.loc[known].astype(int)
            def auc(x):
                if y.nunique() < 2:
                    return None
                a = float(roc_auc_score(y, x.loc[known]))
                return max(a, 1-a)
            row[name + '_auc'] = auc(imputed)
            row[name + '_missing_auc'] = auc(values.isna().astype(float))
            row[name + '_n'] = len(y)
        scores = [row[k] for k in ('lost_auc', 'time_forfeit_auc', 'lost_missing_auc', 'time_forfeit_missing_auc')]
        row['max_auc'] = max((a for a in scores if a is not None), default=None)
        row['exclude_strict'] = any(a is None or a > .70 for a in scores)
        result.append(row)
    return sorted(result, key=lambda r: -(r['max_auc'] if r['max_auc'] is not None else -1))


def audit_lf_proxies(frame):
    """Absolute Spearman against all LF quantities, using only train rows.

    Assess observed pairs, model-style median imputation and missing indicators.
    Categorical quantities use one-vs-rest indicators learned on train. Constant
    or wholly unavailable pairs have no measurable rank association (null rho).
    LF evidence stays audit metadata; it never enters the feature allowlist.
    """
    train = frame.loc[frame.split == 'train']
    sources = {c.removeprefix(LF_INPUT_PREFIX): train[c] for c in train if c.startswith(LF_INPUT_PREFIX)}
    # Allows direct use on small synthetic frames/legacy diagnostic estimates.
    if not sources:
        sources = {c: train[c] for c in sorted(ALL_LF_COLUMNS) if c in train}
    quantities = {}
    for name, values in sources.items():
        numeric = pd.to_numeric(values, errors='coerce').replace([np.inf, -np.inf], np.nan)
        if name == 'status':
            for category in sorted(values.dropna().unique()):
                quantities[name + '=' + str(category)] = values.eq(category).astype(float).where(values.notna())
        else:
            quantities[name] = numeric
        if values.isna().any():
            quantities[name + '__missing'] = values.isna().astype(float)
    # Prepare variable target arrays once. Avoid pandas joins for every pair.
    targets = []
    for name, target in quantities.items():
        array = target.to_numpy(dtype=float, na_value=np.nan)
        known = np.isfinite(array)
        if np.unique(array[known]).size > 1:
            targets.append((name, array, known))
    result = []
    for column in feature_candidates(frame):
        values = pd.to_numeric(train[column], errors='coerce').replace([np.inf, -np.inf], np.nan)
        signals = {'observed': values,
                   'imputed': values.fillna(values.median() if values.notna().any() else 0.),
                   'missing': values.isna().astype(float)}
        best = dict(feature=column, training_rows=len(train), lf_quantity=None,
                    representation=None, rho=None, abs_rho=None, n=0, exclude=False)
        seen = []
        for representation, signal in signals.items():
            array = signal.to_numpy(dtype=float, na_value=np.nan)
            known = np.isfinite(array)
            if np.unique(array[known]).size < 2 or any(np.array_equal(array, other, equal_nan=True) for other in seen):
                continue
            seen.append(array)
            for name, target, target_known in targets:
                paired = known & target_known
                if paired.sum() < 2:
                    continue
                x, y = rankdata(array[paired]), rankdata(target[paired])
                x, y = x - x.mean(), y - y.mean()
                denominator = np.sqrt(np.sum(x * x) * np.sum(y * y))
                if denominator == 0:
                    continue
                rho = float(np.clip(np.sum(x * y) / denominator, -1, 1))
                if best['abs_rho'] is None or abs(rho) > best['abs_rho']:
                    best.update(lf_quantity=name, representation=representation, rho=rho,
                                abs_rho=abs(rho), n=int(paired.sum()), exclude=abs(rho) >= .6)
        result.append(best)
    return sorted(result, key=lambda r: -(r['abs_rho'] if r['abs_rho'] is not None else -1))


def passes_audits(features, outcome_audit, lf_audit):
    """Selection must check actual feature membership, never trust a variant name."""
    if not features:
        return False
    allowed_outcome = {r['feature'] for r in outcome_audit if not r['exclude_strict']}
    allowed_lf = {r['feature'] for r in lf_audit if not r['exclude']}
    return set(features) <= allowed_outcome & allowed_lf


def enrich(data, frame):
    """Retrospective phase aggregates; status is audit metadata, never an input."""
    from pathlib import Path
    from ..data import storage
    raw = storage.read(data, 'games')[['game_id', 'initial_seconds', 'increment_seconds', 'status']]
    frame = frame.merge(raw, on='game_id', how='left', validate='many_to_one')
    moves = pd.read_parquet(Path(data) / 'processed/features/moves.parquet', columns=['player', 'game_id', 'ply', 'phase'])
    moves = moves[moves.player.isin(set(frame.player))]
    phases = pd.crosstab([moves.player, moves.game_id], moves.phase, normalize='index')
    phases = phases.rename(columns={p: 'phase_' + p + '_fraction' for p in phases})
    frame = frame.merge(phases, on=['player', 'game_id'], how='left', validate='one_to_one')
    return prepare(frame)
