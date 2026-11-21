"""Phase 1 evaluation: pre-registered variants on validation only; the test split stays sealed.

See reports/phase1_preregistration.md. The variants, hyperparameters and decision rules there are fixed before any
validation result is seen. Predictions are of the weak label (a behavioural proxy of post-loss tilt), not of anger.
"""
import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.feature_selection import mutual_info_regression
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, balanced_accuracy_score, brier_score_loss,
                             confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score)
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_sample_weight

from ..training.train import choose_threshold, numeric, tree_models

SPLITS = ('by_player', 'by_time')
SPEED = ['speed_blitz', 'speed_bullet', 'speed_rapid', 'speed_classical', 'speed_correspondence']
MIDDLEGAME = 'phase_middlegame_fraction'
E0 = ['initial_seconds', 'increment_seconds', *SPEED, 'risk_rate', 'attack_rate', 'defensive_rate',
      'style_switch_rate', MIDDLEGAME, 'rematch_streak_before', 'baseline_risk_rate_games',
      'baseline_attack_rate_games', 'baseline_style_switch_rate_games']
HISTORY = ([f'baseline_{k}_rate_{s}' for k in ('risk', 'attack', 'style_switch') for s in ('median', 'mad')]
           + [f'deviation_{k}_rate_z' for k in ('risk', 'attack', 'style_switch')]
           + [f'historical_{k}_rate_similar_fraction' for k in ('risk', 'attack', 'style_switch')]
           + ['behavioral_deviation_score_safe'])
DUPLICATE_GAMES = ['baseline_attack_rate_games', 'baseline_style_switch_rate_games']
M1 = [c for c in E0 if c != MIDDLEGAME]
VARIANTS = {
    'E0': dict(model='xgboost', features=E0, indicator=True, role='reference: the previous 16 features'),
    'M1': dict(model='xgboost', features=M1, indicator=True, role='main: E0 without phase_middlegame_fraction'),
    'M2': dict(model='xgboost', features=M1 + HISTORY, indicator=False, role='M1 + 13 history features'),
    'M3': dict(model='xgboost', features=[c for c in M1 if c not in SPEED + DUPLICATE_GAMES], indicator=True,
               role='M1 without constant speed_* and duplicate *_games'),
    'L1': dict(model='logistic', features=M1, indicator=False, role='linear baseline on M1 features'),
}
# Diagnostics only: some read LF inputs directly, so none is deployable.
BASELINES = {
    'B-prior': dict(model='prior', features=[]),
    'B-meta': dict(model='logistic', features=['initial_seconds', 'increment_seconds'], indicator=False),
    'B-length': dict(model='xgboost', features=['lf_input__plies'], indicator=False),
    'B-streak': dict(model='logistic', features=['losing_streak_before'], indicator=False, fill_zero=True),
    'B-result': dict(model='rule', features=['result_score']),
}
COMPARISONS = (('M2', 'M1'), ('M3', 'M1'), ('E0', 'M1'), ('L1', 'M1'))
NOISE = .05


def sha256(frame):
    return hashlib.sha256(frame.to_csv(index=False).encode()).hexdigest()


def split_checks(frame, split):
    """Re-checks independence of the existing split; raises on contamination."""
    labelled = frame[frame.split.isin(['train', 'validation', 'test'])]
    games = labelled.groupby('game_id').split.nunique()
    result = dict(rows=len(frame), purged=int((~frame.split.isin(['train', 'validation', 'test'])).sum()),
                  games_in_several_splits=int((games > 1).sum()))
    players = labelled.groupby('player_id').split.nunique()
    result['players_in_several_splits'] = int((players > 1).sum())
    if result['games_in_several_splits']:
        raise ValueError(f'{split}: a game is in several splits')
    if split == 'by_player' and result['players_in_several_splits']:
        raise ValueError('by_player: a player is in several splits')
    if split == 'by_time':
        end = pd.concat([pd.to_numeric(frame.end_upper_ms, errors='coerce'),
                         pd.to_numeric(frame.get('lf_input__next_end_upper_ms'), errors='coerce')], axis=1).max(axis=1)
        start = pd.to_numeric(frame.start_ms, errors='coerce')
        order = ('train', 'validation', 'test')
        for before, after in zip(order, order[1:]):
            crossing = int((end[frame.split == before] >= start[frame.split == after].min()).sum())
            result[f'{before}_label_end_after_{after}_start'] = crossing
            if crossing:
                raise ValueError(f'by_time: {before} labels reach into {after}')
    if 'baseline_latest_end_ms' in frame:
        latest = pd.to_numeric(frame.baseline_latest_end_ms, errors='coerce')
        result['history_after_game_start'] = int((latest >= pd.to_numeric(frame.start_ms, errors='coerce')).sum())
        if result['history_after_game_start']:
            raise ValueError(f'{split}: personal history reads the future')
    for name in ('train', 'validation', 'test'):
        part = frame[frame.split == name]
        y = part.weak_tilt_label.dropna()
        result[name] = dict(rows=len(part), players=int(part.player_id.nunique()), labelled=len(y),
                            tilt_rate=float(y.mean()) if len(y) else None)
    return result


def manifest(frame):
    return frame[['player_id', 'game_id', 'split']].sort_values(['split', 'player_id', 'game_id']).reset_index(drop=True)


def design(frame, features, train, indicator=False, fill_zero=False):
    """Train-only median imputation and scaling, as the existing pipeline does."""
    values = numeric(frame, features)
    if fill_zero:
        values = np.nan_to_num(values, nan=0.)
    imputer = SimpleImputer(strategy='median', add_indicator=indicator, keep_empty_features=True)
    imputer.fit(values[train])
    x = imputer.transform(values)
    return StandardScaler().fit(x[train]).transform(x).astype(np.float32)


def fit_predict(spec, frame, y, train, threads=2, seed=42):
    """Raw (uncalibrated) scores for every row; only train rows are fitted."""
    if spec['model'] == 'prior':
        return np.full(len(frame), float(y[train].mean()))
    if spec['model'] == 'rule':
        return frame.result_score.eq(0).astype(float).to_numpy()
    x = design(frame, spec['features'], train, spec.get('indicator', False), spec.get('fill_zero', False))
    if spec['model'] == 'logistic':
        model = LogisticRegression(C=1, class_weight='balanced', max_iter=2000, random_state=seed)
        model.fit(x[train], y[train].astype(int))
    elif spec['model'] == 'xgboost':
        model = tree_models('xgboost', seed=seed, threads=threads, trees=100)[0]
        model.fit(x[train], y[train].astype(int), sample_weight=compute_sample_weight('balanced', y[train]))
    else:
        raise ValueError('Unknown model ' + spec['model'])
    return model.predict_proba(x)[:, 1]


def calibration_bins(y, p, bins=10):
    edges = np.unique(np.quantile(p, np.linspace(0, 1, bins + 1)))
    groups = np.clip(np.searchsorted(edges, p, side='right') - 1, 0, max(len(edges) - 2, 0))
    rows, ece = [], 0.
    for g in np.unique(groups):
        mask = groups == g
        rows.append(dict(n=int(mask.sum()), mean_score=float(p[mask].mean()), tilt_rate=float(y[mask].mean())))
        ece += mask.mean() * abs(p[mask].mean() - y[mask].mean())
    return rows, float(ece)


def ranking(y, p):
    if len(np.unique(y)) < 2:
        return dict(n=len(y), positives=int(y.sum()), pr_auc=None, roc_auc=None)
    return dict(n=len(y), positives=int(y.sum()), pr_auc=float(average_precision_score(y, p)),
                roc_auc=float(roc_auc_score(y, p)))


def metrics(y, p, threshold):
    result = ranking(y, p)
    bins, ece = calibration_bins(y, p)
    predicted = (p >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, predicted, labels=[0, 1]).ravel()
    result.update(prevalence=float(y.mean()), brier=float(brier_score_loss(y, np.clip(p, 0, 1))), ece=ece,
                  calibration=bins, threshold=float(threshold),
                  precision=float(precision_score(y, predicted, zero_division=0)),
                  recall=float(recall_score(y, predicted, zero_division=0)),
                  macro_f1=float(f1_score(y, predicted, average='macro', zero_division=0)),
                  balanced_accuracy=float(balanced_accuracy_score(y, predicted)),
                  confusion=dict(tn=int(tn), fp=int(fp), fn=int(fn), tp=int(tp)))
    return result


def bootstrap(players, y, scores, comparisons, repetitions=1000, seed=42):
    """Player-cluster bootstrap; every model sees the same resamples, so differences are paired."""
    rng = np.random.default_rng(seed)
    index = pd.Series(np.arange(len(players))).groupby(players).apply(np.array).tolist()
    draws = {name: dict(pr_auc=[], roc_auc=[]) for name in scores}
    deltas = {f'{a}-{b}': [] for a, b in comparisons}
    for _ in range(repetitions):
        rows = np.concatenate([index[i] for i in rng.integers(0, len(index), len(index))])
        if len(np.unique(y[rows])) < 2:
            continue
        ap = {name: average_precision_score(y[rows], p[rows]) for name, p in scores.items()}
        for name, p in scores.items():
            draws[name]['pr_auc'].append(ap[name])
            draws[name]['roc_auc'].append(roc_auc_score(y[rows], p[rows]))
        for a, b in comparisons:
            deltas[f'{a}-{b}'].append(ap[a] - ap[b])
    def ci(values):
        return [float(np.quantile(values, .025)), float(np.quantile(values, .975))] if values else None
    return ({name: {k: ci(v) for k, v in d.items()} for name, d in draws.items()},
            {k: dict(mean=float(np.mean(v)), ci=ci(v)) if v else None for k, v in deltas.items()},
            len(next(iter(draws.values()))['pr_auc']))


def nonlinear(frame, features, target='lf_input__plies', seed=42):
    """Recorded only, never used to drop a feature: eta^2 by feature decile and mutual information."""
    train = frame[frame.split == 'train']
    t = pd.to_numeric(train[target], errors='coerce')
    result = []
    for column in features:
        x = pd.to_numeric(train[column], errors='coerce')
        known = x.notna() & t.notna()
        if x[known].nunique() < 2:
            result.append(dict(feature=column, eta2=None, mutual_information=None))
            continue
        groups = pd.qcut(x[known].rank(method='first'), 10, labels=False)
        tk = t[known]
        between = tk.groupby(groups).apply(lambda g: len(g) * (g.mean() - tk.mean()) ** 2).sum()
        eta2 = float(between / ((tk - tk.mean()) ** 2).sum())
        mi = float(mutual_info_regression(x[known].to_numpy()[:, None], tk.to_numpy(), random_state=seed)[0])
        result.append(dict(feature=column, eta2=eta2, mutual_information=mi))
    return sorted(result, key=lambda r: -(r['eta2'] or 0))


def subgroups(frame, rows, y, scores):
    part = frame.iloc[rows]
    masks = {'loss': part.result_score.eq(0).to_numpy(), 'not_loss': part.result_score.gt(0).to_numpy(),
             'plies_ge_40': pd.to_numeric(part.lf_input__plies, errors='coerce').ge(40).to_numpy(),
             'history_ge_5': pd.to_numeric(part.history_games, errors='coerce').ge(5).to_numpy()}
    return {group: {name: ranking(y[mask], p[mask]) | dict(prevalence=float(y[mask].mean()) if mask.any() else None)
                    for name, p in scores.items()} for group, mask in masks.items()}


def decide(results):
    """The pre-registered rules, applied mechanically to validation PR-AUC."""
    def delta(split, a, b):
        return results[split]['validation'][a]['pr_auc'] - results[split]['validation'][b]['pr_auc']
    a, b = SPLITS
    history = delta(a, 'M2', 'M1') >= NOISE and delta(b, 'M2', 'M1') > 0
    cleanup = all(abs(delta(s, 'M3', 'M1')) < NOISE for s in SPLITS)
    length = {s: results[s]['validation']['B-length']['pr_auc'] for s in SPLITS}
    return dict(
        middlegame=dict(decision='excluded (step 0: TILT rate 100% where middlegame = 0)',
                        length_only_pr_auc=length, length_only_at_least_0_30={s: v >= .30 for s, v in length.items()},
                        e0_minus_m1={s: delta(s, 'E0', 'M1') for s in SPLITS}),
        history=dict(accepted=history, m2_minus_m1={s: delta(s, 'M2', 'M1') for s in SPLITS}),
        cleanup=dict(use_m3=cleanup, m3_minus_m1={s: delta(s, 'M3', 'M1') for s in SPLITS}),
        main=('M3' if cleanup else 'M1') + (' + history' if history else ''))


def run(aligned, out, previous=None, repetitions=1000, threads=2):
    aligned, out = Path(aligned), Path(out)
    (out / 'manifests').mkdir(parents=True, exist_ok=True)
    (out / 'predictions').mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    specs = VARIANTS | BASELINES
    results = dict(seed=42, repetitions=repetitions, variants={k: {**v, 'features': list(v['features'])} for k, v in specs.items()})
    for split in SPLITS:
        frame = pd.read_parquet(aligned / f'aligned_{split}.parquet')
        checks = split_checks(frame, split)
        table = manifest(frame)
        table.to_csv(out / 'manifests' / f'{split}.csv', index=False)
        checks['manifest_sha256'] = sha256(table)
        y = frame.weak_tilt_label.to_numpy(dtype=float, na_value=np.nan)
        known = np.isfinite(y)
        train = np.flatnonzero((frame.split == 'train').to_numpy() & known)
        val = np.flatnonzero((frame.split == 'validation').to_numpy() & known)
        # The test split is sealed: nothing below reads a test label.
        assert not (frame.split.iloc[val] == 'test').any()
        raw = {name: fit_predict(spec, frame, y, train, threads=threads) for name, spec in specs.items()}
        yv = y[val].astype(int)
        scores = {name: p[val] for name, p in raw.items()}
        validation = {}
        for name, p in raw.items():
            threshold = choose_threshold(p[train], y[train], p[val], y[val])['threshold']
            validation[name] = metrics(yv, p[val], threshold)
        intervals, paired, used = bootstrap(frame.player_id.iloc[val].to_numpy(), yv, scores, COMPARISONS, repetitions)
        for name in validation:
            validation[name]['ci95'] = intervals[name]
        prediction = frame[['player_id', 'game_id', 'split', 'weak_tilt_label']].iloc[val].copy()
        for name, p in scores.items():
            prediction[name] = p
        prediction.to_parquet(out / 'predictions' / f'validation_{split}.parquet', index=False)
        results[split] = dict(checks=checks, validation=validation, paired_differences=paired, bootstrap_used=used,
                              subgroups=subgroups(frame, val, yv, scores),
                              nonlinear=nonlinear(frame, sorted(set(M1 + HISTORY + [MIDDLEGAME]))))
        if previous:
            old = Path(previous) / f'predictions__{split}__lf_ablated__xgboost.parquet'
            if old.exists():
                old = pd.read_parquet(old, columns=['player_id', 'game_id', 'raw_weak_tilt_prob'])
                joined = prediction[['player_id', 'game_id', 'E0']].merge(old, on=['player_id', 'game_id'], how='left')
                results[split]['e0_reproduction'] = dict(
                    rows=len(joined), matched=int(joined.raw_weak_tilt_prob.notna().sum()),
                    max_abs_difference=float((joined.E0 - joined.raw_weak_tilt_prob).abs().max()))
        print(f'{split}: done', flush=True)
    results['decision'] = decide(results)
    results['elapsed_seconds'] = time.monotonic() - start
    (out / 'phase1_results.json').write_text(json.dumps(results, indent=1))
    rows = [dict(split=s, model=name, **{k: v.get(k) for k in ('n', 'positives', 'prevalence', 'pr_auc', 'roc_auc', 'brier',
                                                                 'ece', 'threshold', 'precision', 'recall', 'macro_f1',
                                                                 'balanced_accuracy')},
                 pr_auc_ci_low=v['ci95']['pr_auc'][0], pr_auc_ci_high=v['ci95']['pr_auc'][1])
            for s in SPLITS for name, v in results[s]['validation'].items()]
    pd.DataFrame(rows).to_csv(out / 'phase1_metrics.csv', index=False)
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description='Phase 1: pre-registered validation-only evaluation')
    parser.add_argument('--aligned', required=True, help='folder with aligned_by_player/by_time.parquet')
    parser.add_argument('--out', required=True)
    parser.add_argument('--previous', help='folder with the previous predictions__*.parquet (reproduction check)')
    parser.add_argument('--repetitions', type=int, default=1000)
    parser.add_argument('--threads', type=int, default=2)
    args = parser.parse_args(argv)
    result = run(args.aligned, args.out, args.previous, args.repetitions, args.threads)
    print(json.dumps(result['decision'], indent=1))


if __name__ == '__main__':
    main()
