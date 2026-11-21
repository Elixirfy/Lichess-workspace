"""Reproducible weak-label tree and CPU sequence training; validation calibration."""
import json
from pathlib import Path
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_sample_weight
from threadpoolctl import threadpool_limits

from ..data.dataset import _safe_export
from ..labels.labels import pseudonym, private_id
from ..features.model_features import enrich, feature_list, audit_outcome_proxies, audit_lf_proxies
from ..labels.weak_labels import SPLIT_POLICY, WEAK_VERSION, LF_INPUT_PREFIX
from ..data import storage

VARIANTS = ('full', 'no_history', 'lf_ablated', 'lf_ablated_no_history')
MODELS = ('random_forest', 'xgboost', 'lightgbm', 'lstm')


def snapshots(data, ids):
    frame = pd.read_parquet(Path(data) / 'processed/features/games.parquet')
    frame = frame[frame.player.map(pseudonym).isin(ids)].copy()
    frame = enrich(data, frame)
    return pd.DataFrame([_safe_export(r) for r in storage.records(frame)]).sort_values(['player_id', 'start_ms', 'game_id']).reset_index(drop=True)


def aligned(data, split='by_player'):
    weak = pd.read_parquet(Path(data) / 'processed' / 'out' / f'weak_{split}.parquet')
    features = snapshots(data, set(weak.player_id))
    targets = ['player_id', 'game_id', 'weak_tilt_label', 'weak_tilt_prob', 'weak_majority_prob', 'split']
    targets += [c for c in weak if c.startswith(LF_INPUT_PREFIX)]
    return features.merge(weak[targets], on=['player_id', 'game_id'], how='left', validate='one_to_one')


def numeric(frame, columns):
    return frame.reindex(columns=columns).apply(pd.to_numeric, errors='coerce').replace([np.inf, -np.inf], np.nan).to_numpy(dtype=np.float64, na_value=np.nan)


def fit_preprocessor(frame, columns, train):
    imputer = SimpleImputer(strategy='median', add_indicator=True, keep_empty_features=True)
    x = imputer.fit_transform(numeric(frame.iloc[train], columns))
    scaler = StandardScaler().fit(x)
    return dict(imputer=imputer, scaler=scaler)


def transform(bundle, frame):
    x = bundle['preprocessor']['imputer'].transform(numeric(frame, bundle['features']))
    return bundle['preprocessor']['scaler'].transform(x).astype(np.float32)


def calibrate(prob, y):
    """Platt scaling is validation-only, with explicit fallback for small cohorts."""
    if len(y) < 20 or np.count_nonzero(y == 1) < 10 or len(np.unique(y)) < 2:
        return dict(model=None, status='identity: fewer than 20 validation rows, fewer than 10 validation weak positives, or only one class')
    logits = np.log(np.clip(prob, 1e-6, 1 - 1e-6) / np.clip(1 - prob, 1e-6, 1))[:, None]
    model = LogisticRegression(C=1, random_state=42).fit(logits, y)
    # A reversed calibration slope is not silently accepted as an emotion score.
    if model.coef_[0, 0] <= 0:
        return dict(model=None, status='identity: validation association nonpositive')
    return dict(model=model, status='validation-only Platt scaling')


def calibrated(calibration, prob):
    if calibration['model'] is None:
        return np.clip(prob, 0, 1)
    logits = np.log(np.clip(prob, 1e-6, 1 - 1e-6) / np.clip(1 - prob, 1e-6, 1))[:, None]
    return calibration['model'].predict_proba(logits)[:, 1]


def choose_threshold(train_prob, train_y, validation_prob, validation_y):
    """Choose on calibrated validation scores only; never accept test inputs.

    Sparse validation uses the labelled-train (1 - weak-positive-rate) quantile.
    The higher order statistic with >= yields that rate for untied train scores;
    a single threshold cannot split tied scores (notably constant diagnostics).
    """
    train_prob, train_y = np.asarray(train_prob), np.asarray(train_y)
    validation_prob, validation_y = np.asarray(validation_prob), np.asarray(validation_y)
    valid = np.isfinite(validation_y) & np.isfinite(validation_prob)
    p, y = validation_prob[valid], validation_y[valid]
    if np.count_nonzero(y == 1) >= 10 and len(np.unique(y)) == 2:
        thresholds, groups, counts = np.unique(p, return_inverse=True, return_counts=True)
        true_positives = np.bincount(groups, weights=y)[::-1].cumsum()[::-1]
        predicted_positives = counts[::-1].cumsum()[::-1]
        # Count ratios avoid precision/recall rounding breaking exact F1 ties.
        f1 = 2 * true_positives / (y.sum() + predicted_positives)
        threshold = thresholds[np.flatnonzero(f1 == f1.max())[-1]]
        return dict(threshold=float(threshold), threshold_source='validation F1 maximum; ties use higher threshold')
    labelled = np.isfinite(train_y)
    scores = train_prob[labelled & np.isfinite(train_prob)]
    if not labelled.any() or not len(scores):
        raise ValueError('Threshold fallback requires labelled train rows with finite scores')
    prior = float(train_y[labelled].mean())
    threshold = (np.nextafter(scores.max(), np.inf) if prior == 0 else
                 np.quantile(scores, 1 - prior, method='higher'))
    return dict(threshold=float(threshold), threshold_source=(
        'train calibrated-score quantile matching train weak-positive rate '
        '(higher order statistic; score ties may prevent exact rate): '
        'fewer than 10 validation weak positives or only one scored class'))


def tree_models(name, seed=42, threads=2, trees=100):
    common = dict(n_estimators=trees, random_state=seed, n_jobs=threads)
    if name == 'random_forest':
        return (RandomForestClassifier(**common, max_depth=10, min_samples_leaf=8, max_features=.8),
                RandomForestRegressor(**common, max_depth=10, min_samples_leaf=8, max_features=.8))
    if name == 'xgboost':
        from xgboost import XGBClassifier, XGBRegressor
        args = dict(**common, max_depth=3, learning_rate=.06, subsample=.85, colsample_bytree=.85,
                    tree_method='hist', reg_lambda=3)
        return XGBClassifier(**args, eval_metric='logloss'), XGBRegressor(**args, objective='reg:squarederror')
    if name == 'lightgbm':
        from lightgbm import LGBMClassifier, LGBMRegressor
        args = dict(**common, num_leaves=15, learning_rate=.06, min_child_samples=15,
                    verbosity=-1, deterministic=True, force_col_wise=True)
        return LGBMClassifier(**args), LGBMRegressor(**args)
    raise ValueError('Unknown tree model')


def predict_bundle(bundle, frame, sequence_indices=None):
    if bundle.get('format') == 'phase5':
        # Phase 5 bundle (service/deployment.py): imputer + kept columns + scaler + XGBoost, no regressor.
        x = bundle['imputer'].transform(numeric(frame, bundle['features']))[:, bundle['keep']]
        raw = bundle['classifier'].predict_proba(bundle['scaler'].transform(x).astype(np.float32))[:, 1]
        return calibrated(bundle['calibration'], raw), np.full(len(raw), np.nan), raw
    x = transform(bundle, frame)
    if bundle['model'] == 'lstm':
        from .sequence import materialize, predict, prior_indices
        ids = prior_indices(frame) if sequence_indices is None else sequence_indices
        raw, regression = predict(bundle['sequence'], materialize(x, ids))
    else:
        if bundle['model'] == 'lightgbm':
            # The wrapper assigns names even to a NumPy fit; native prediction
            # avoids spurious feature-name warnings without suppressing warnings.
            raw = bundle['classifier'].booster_.predict(x, num_threads=bundle['classifier'].n_jobs)
            regression = bundle['regressor'].booster_.predict(x, num_threads=bundle['regressor'].n_jobs)
        else:
            raw = bundle['classifier'].predict_proba(x)[:, 1]
            regression = bundle['regressor'].predict(x)
    return calibrated(bundle['calibration'], raw), np.clip(regression, 0, 100), raw


def run(data, epochs=12, trees=100, threads=2, models=MODELS, variants=VARIANTS):
    data = Path(data)
    weak_manifest = json.loads((data / 'processed/out/weak_manifest.json').read_text())
    if weak_manifest['salt_fingerprint'] != private_id('tilt-weak-model-salt-v1'):
        raise ValueError('TILT_SALT differs from weak-label export salt')
    if weak_manifest.get('version') != WEAK_VERSION:
        raise ValueError('Weak-label pipeline changed; rebuild weak labels on the compute machine before train')
    if weak_manifest.get('split_policy') != SPLIT_POLICY:
        raise ValueError('Weak-label splits changed to 60/20/20 and 70/85; rebuild weak labels on the compute machine')
    folder = data / 'processed' / 'models'
    folder.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    manifest = dict(title='Tilt weak-label model', seed=42, threads=threads, epochs=epochs, trees=trees,
                    prediction_point='game completion; outcome and LF families withheld',
                    weak_manifest=weak_manifest, outcome_proxy_audits={}, lf_proxy_audits={}, runs=[], skipped=[], status='training', training_run_id=str(time.time_ns()))
    (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    for split in ('by_player', 'by_time'):
        frame = aligned(data, split)
        audit = audit_outcome_proxies(frame)
        lf_audit = audit_lf_proxies(frame)
        manifest['outcome_proxy_audits'][split] = audit
        manifest['lf_proxy_audits'][split] = lf_audit
        y = frame.weak_tilt_label.to_numpy(dtype=float, na_value=np.nan)
        soft = frame.weak_tilt_prob.to_numpy(dtype=float, na_value=np.nan)
        mask = np.isfinite(y)
        train = np.flatnonzero((frame.split == 'train') & mask)
        val = np.flatnonzero((frame.split == 'validation') & mask)
        if not len(train) or len(np.unique(y[train])) < 2:
            manifest['skipped'].append(dict(split=split, reason='Training weak labels do not contain both classes'))
            continue
        from .sequence import prior_indices
        indices = prior_indices(frame)
        weights = compute_sample_weight('balanced', y[train])
        for variant in variants:
            try:
                columns = feature_list(frame, variant, audit, lf_audit)
            except ValueError as error:
                if str(error) != 'No admissible model features':
                    raise
                manifest['skipped'].append(dict(split=split, variant=variant, reason=str(error)))
                continue
            prep = fit_preprocessor(frame, columns, train)
            for name in models:
                run_id = f'{split}__{variant}__{name}'
                bundle = dict(model=name, variant=variant, split=split, features=columns,
                              preprocessor=prep, calibration=dict(model=None, status='pending'))
                x = transform(bundle, frame)
                with threadpool_limits(limits=threads):
                    if name == 'lstm':
                        from .sequence import fit, materialize
                        bundle['sequence'] = fit(materialize(x, indices), y, soft, train, val, epochs=epochs, threads=threads)
                    else:
                        classifier, regressor = tree_models(name, trees=trees, threads=threads)
                        classifier.fit(x[train], y[train].astype(int), sample_weight=weights)
                        regressor.fit(x[train], 100 * soft[train])
                        bundle.update(classifier=classifier, regressor=regressor)
                    _, _, raw = predict_bundle(bundle, frame, indices)
                bundle['calibration'] = calibrate(raw[val], y[val].astype(int))
                # Imputer statistics are train-only medians, with zero for a
                # completely unobserved feature (keep_empty_features=True).
                bundle['reference'] = np.nan_to_num(prep['imputer'].statistics_).tolist()
                prob, regression, raw = predict_bundle(bundle, frame, indices)
                bundle.update(choose_threshold(prob[train], y[train], prob[val], y[val]))
                prediction = frame[['player_id', 'game_id', 'speed', 'rating', 'split', 'weak_tilt_label', 'weak_tilt_prob', 'weak_majority_prob', 'result_score', 'status']].copy()
                prediction['predicted_weak_tilt_prob'] = prob
                prediction['raw_weak_tilt_prob'] = raw
                prediction['predicted_weak_tilt_score_regression'] = regression
                storage.write_frame(data / 'processed' / 'out' / f'predictions__{run_id}.parquet', prediction)
                joblib.dump(bundle, folder / f'{run_id}.joblib', compress=3)
                (folder / f'{run_id}.features.json').write_text(json.dumps(columns, indent=2))
                manifest['runs'].append(dict(id=run_id, split=split, variant=variant, model=name,
                                              features=columns, training_rows=len(train), validation_rows=len(val),
                                              validation_positives=int(y[val].sum()),
                                              threshold=bundle['threshold'], threshold_source=bundle['threshold_source'],
                                              calibration=bundle['calibration']['status']))
                print(f'Trained weak-label model: {run_id} ({len(train)} train, {len(val)} validation)', flush=True)
        # Diagnostic baselines are intentionally permitted to read losing streak;
        # they are not eligible deployable models under the LF feature guard.
        prior = float(y[train].mean())
        baseline = LogisticRegression(C=1, random_state=42).fit(frame[['losing_streak_before']].fillna(0).iloc[train], y[train])
        for name, prob in (('class_prior', np.full(len(frame), prior)),
                           ('losing_streak', baseline.predict_proba(frame[['losing_streak_before']].fillna(0))[:, 1]),
                           ('result_only', frame.result_score.eq(0).where(frame.result_score.notna()).to_numpy(dtype=float, na_value=np.nan))):
            prediction = frame[['player_id', 'game_id', 'speed', 'rating', 'split', 'weak_tilt_label', 'weak_tilt_prob', 'weak_majority_prob', 'result_score', 'status']].copy()
            prediction['predicted_weak_tilt_prob'] = prob
            prediction['raw_weak_tilt_prob'] = prob
            prediction['predicted_weak_tilt_score_regression'] = 100 * soft[train].mean() if name == 'class_prior' else 100 * prob
            run_id = f'{split}__baseline__{name}'
            threshold = choose_threshold(prob[train], y[train], prob[val], y[val])
            storage.write_frame(data / 'processed' / 'out' / f'predictions__{run_id}.parquet', prediction)
            joblib.dump(dict(model=name, split=split, variant='baseline', **threshold), folder / f'{run_id}.joblib')
            manifest['runs'].append(dict(id=run_id, split=split, variant='baseline', model=name,
                                         training_rows=len(train), validation_rows=len(val), validation_positives=int(y[val].sum()),
                                         calibration='uncalibrated diagnostic', **threshold))
    manifest['elapsed_seconds'] = time.monotonic() - start
    manifest['status'] = 'complete'
    (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    return dict(trained=len(manifest['runs']), skipped=manifest['skipped'], elapsed_seconds=manifest['elapsed_seconds'])
