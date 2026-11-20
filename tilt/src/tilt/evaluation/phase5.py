"""Phase 5: pre-registered final model selection (reports/phase5_preregistration.md).

The preregistration's sha256 is checked before anything runs. Every model is fitted on labelled TRAIN rows only, as in
Phase 1/3; Platt scaling is fitted on validation; thresholds come from train+validation. Test labels are read only after
the validation reproduction gate has passed and validation.json has been written. Scores predict the weak label, a
behavioural proxy of tilt, not anger.
"""
import argparse
import hashlib
import json
import platform
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.metrics import (average_precision_score, brier_score_loss, f1_score, precision_score, recall_score,
                             roc_auc_score)
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_sample_weight

from ..core.train import calibrate, calibrated, choose_threshold, numeric, tree_models
from ..features.behavior import DEVIATIONS
from ..features.model_features import forbidden
from . import phase1, phase3

NOTICE = 'The model predicts a behavioral proxy of tilt, not independently validated anger.'
SPLITS = phase1.SPLITS
A, B = SPLITS
META = ('initial_seconds', 'increment_seconds')
CANDIDATES = ('P3-B', 'M3')
# Feature lists exactly as written in section 1 of the preregistration (gate 1a compares against these).
PREREGISTERED = {
    'M3': ['initial_seconds', 'increment_seconds', 'risk_rate', 'attack_rate', 'defensive_rate', 'style_switch_rate',
           'rematch_streak_before', 'baseline_risk_rate_games'],
}
PREREGISTERED['P3-B'] = PREREGISTERED['M3'] + ['attack_trend_3w', 'risk_volatility_3w', 'behavior_change_point']
NOMETA = {c: f'{c}-nometa' for c in CANDIDATES}
# name: (features, missing indicators?, columns without an indicator)
XGB = {
    'P3-B': (phase3.VARIANTS['P3-B'], True, phase3.NO_INDICATOR),
    'M3': (phase3.VARIANTS['M3'], True, phase3.NO_INDICATOR),
    'P3-B-nometa': ([c for c in phase3.VARIANTS['P3-B'] if c not in META], True, phase3.NO_INDICATOR),
    'M3-nometa': ([c for c in phase3.VARIANTS['M3'] if c not in META], True, phase3.NO_INDICATOR),
    'E0': (phase1.E0, True, set()),
    'M1': (phase1.M1, True, set()),
    'B-length': (['lf_input__plies'], False, set()),
}
OTHER = {name: phase1.BASELINES[name] for name in ('B-result', 'B-streak', 'B-prior', 'B-meta')}
MODELS = tuple(XGB) + tuple(OTHER)
BASELINES = ('B-prior', 'B-result', 'B-streak', 'B-meta', 'B-length')
GATE_BASELINES = ('B-prior', 'B-result', 'B-streak', 'B-meta')
PAIRS = tuple((c, b) for c in CANDIDATES for b in BASELINES) + (('P3-B', 'M3'), ('E0', 'M1')) + tuple(
    (c, NOMETA[c]) for c in CANDIDATES)
REPRODUCE = ('P3-B', 'M3', 'E0')
REPRODUCTION_TOLERANCE = .001
FLOOR = {A: .337, B: .278}
META_KEEP = .75
ECE_MAX = {A: .05, B: .08}
LONG = 40
REPEATS = 20
REPRODUCIBLE = 1e-6
PHASE0_TEST_SEEN = {'by_player lf_ablated xgboost (~E0)': .509, 'by_time lf_ablated random_forest': .548,
                    'class prior': .140, 'losing_streak': .246, 'result_only': .183}
RATING_BANDS = (('<1200', -np.inf, 1200), ('1200-1599', 1200, 1600), ('1600-1999', 1600, 2000), ('>=2000', 2000, np.inf))
IGNORED = {'elapsed_seconds', 'bundle_sha256', 'created_utc', 'paths'}
CODE = ('evaluation/phase5.py', 'evaluation/phase1.py', 'evaluation/phase3.py', 'core/train.py')


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Fitted:
    """Same matrix and model as phase3.design / phase1.design + XGBoost, but keeps the fitted pieces."""

    def __init__(self, features, indicator=True, no_indicator=(), threads=2, seed=42):
        self.features, self.indicator, self.no_indicator = list(features), indicator, set(no_indicator)
        self.threads, self.seed = threads, seed

    def fit(self, frame, y, train):
        values = numeric(frame, self.features)
        self.imputer = SimpleImputer(strategy='median', add_indicator=self.indicator,
                                     keep_empty_features=True).fit(values[train])
        n = len(self.features)
        sources = (self.imputer.indicator_.features_ if self.indicator and self.imputer.indicator_ is not None
                   else np.array([], int))
        kept = [(i, s) for i, s in enumerate(sources) if self.features[s] not in self.no_indicator]
        self.keep = list(range(n)) + [n + i for i, _ in kept]
        self.columns = self.features + [self.features[s] + '__missing' for _, s in kept]
        x = self.imputer.transform(values)[:, self.keep]
        self.scaler = StandardScaler().fit(x[train])
        x = self.scaler.transform(x).astype(np.float32)
        self.model = tree_models('xgboost', seed=self.seed, threads=self.threads, trees=100)[0]
        self.model.fit(x[train], y[train].astype(int), sample_weight=compute_sample_weight('balanced', y[train]))
        return self

    def matrix(self, frame):
        x = self.imputer.transform(numeric(frame, self.features))[:, self.keep]
        return self.scaler.transform(x).astype(np.float32)

    def predict(self, frame):
        return self.model.predict_proba(self.matrix(frame))[:, 1]

    def gain(self):
        """XGBoost gain per original feature (a missing indicator counts toward its feature)."""
        raw = self.model.get_booster().get_score(importance_type='gain')
        out = {f: 0. for f in self.features}
        for key, value in raw.items():
            out[self.columns[int(key[1:])].removesuffix('__missing')] += float(value)
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def ranking(y, p):
    return phase3.ranking(y, p)


def short_separation(score, plies):
    known = np.isfinite(plies) & np.isfinite(score)
    short = plies[known] < LONG
    if short.all() or not short.any():
        return None
    value = roc_auc_score(short, score[known])
    return float(max(value, 1 - value))


def calibration_metrics(y, prob, threshold, reference):
    bins, ece = phase1.calibration_bins(y, prob)
    brier = float(brier_score_loss(y, np.clip(prob, 0, 1)))
    baseline = float(brier_score_loss(y, np.full(len(y), reference)))
    flagged = (prob >= threshold).astype(int)
    return dict(brier=brier, brier_reference=baseline, brier_skill=1 - brier / baseline, ece=ece, reliability=bins,
                threshold=float(threshold), precision=float(precision_score(y, flagged, zero_division=0)),
                recall=float(recall_score(y, flagged, zero_division=0)),
                f1=float(f1_score(y, flagged, zero_division=0)), flag_rate=float(flagged.mean()))


def bootstrap(players, y, scores, long, pairs, excess=(), repetitions=1000, seed=42):
    """Player-cluster bootstrap shared by all models (paired); same draws as Phase 3 for the same seed. The ≥40-ply
    metric filters each resample after drawing players; 'excess' is PR-AUC minus prevalence on that filtered sample."""
    rng = np.random.default_rng(seed)
    index = pd.Series(np.arange(len(players))).groupby(players).apply(np.array).tolist()
    keys = ('primary', 'secondary')
    draws = {k: {name: [] for name in scores} for k in keys}
    deltas = {k: {f'{a}-{b}': [] for a, b in pairs} for k in keys}
    over = {name: [] for name in excess}
    skipped = dict(primary=0, secondary=0)
    for _ in range(repetitions):
        rows = np.concatenate([index[i] for i in rng.integers(0, len(index), len(index))])
        for key, sample in (('primary', rows), ('secondary', rows[long[rows]])):
            if len(np.unique(y[sample])) < 2:
                skipped[key] += 1
                continue
            ap = {name: average_precision_score(y[sample], p[sample]) for name, p in scores.items()}
            for name in scores:
                draws[key][name].append(ap[name])
            for a, b in pairs:
                deltas[key][f'{a}-{b}'].append(ap[a] - ap[b])
            if key == 'secondary':
                for name in excess:
                    over[name].append(ap[name] - y[sample].mean())

    def ci(values):
        return [float(np.quantile(values, .025)), float(np.quantile(values, .975))] if values else None
    return dict(ci={k: {n: ci(v) for n, v in d.items()} for k, d in draws.items()},
                paired={k: {n: dict(mean=float(np.mean(v)), ci=ci(v)) if v else None for n, v in d.items()}
                        for k, d in deltas.items()},
                excess_ge40={n: dict(mean=float(np.mean(v)), ci=ci(v)) if v else None for n, v in over.items()},
                skipped=skipped, repetitions=repetitions)


def permutation_importance(fitted, frame, rows, y, repeats=REPEATS, seed=42):
    """Mean PR-AUC drop when one original feature is shuffled among the evaluation rows."""
    part = frame.iloc[rows].copy()
    base = average_precision_score(y, fitted.predict(part))
    rng = np.random.default_rng(seed)
    out = {}
    for feature in fitted.features:
        original = part[feature].to_numpy().copy()
        drops = []
        for _ in range(repeats):
            part[feature] = original[rng.permutation(len(original))]
            drops.append(base - average_precision_score(y, fitted.predict(part)))
        part[feature] = original
        out[feature] = float(np.mean(drops))
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def subgroups(part, y, scores):
    plies = pd.to_numeric(part.lf_input__plies, errors='coerce').to_numpy(dtype=float)
    rating = pd.to_numeric(part['rating'], errors='coerce').to_numpy(dtype=float) if 'rating' in part else None
    masks = {'loss': part.result_score.eq(0).to_numpy(), 'not_loss': part.result_score.gt(0).to_numpy(),
             'plies_ge_40': plies >= LONG, 'plies_lt_40': plies < LONG}
    if rating is not None:
        masks |= {f'rating {name}': (rating >= low) & (rating < high) for name, low, high in RATING_BANDS}
    return {group: dict(n=int(mask.sum()), models={name: ranking(y[mask], s[mask]) for name, s in scores.items()})
            for group, mask in masks.items()}


def fit_all(frame, y, train, threads):
    fitted = {name: Fitted(f, ind, no, threads).fit(frame, y, train) for name, (f, ind, no) in XGB.items()}
    raw = {name: model.predict(frame) for name, model in fitted.items()}
    raw |= {name: phase1.fit_predict(spec, frame, y, train, threads=threads) for name, spec in OTHER.items()}
    return fitted, raw


def validation_stage(frame, threads=2, repetitions=1000):
    """Everything that may be computed before the test labels are read. Uses train and validation rows only."""
    y = frame.weak_tilt_label.to_numpy(dtype=float, na_value=np.nan)
    known = np.isfinite(y)
    split = frame.split.to_numpy()
    train = np.flatnonzero((split == 'train') & known)
    val = np.flatnonzero((split == 'validation') & known)
    fitted, raw = fit_all(frame, y, train, threads)
    yv = y[val].astype(int)
    plies = pd.to_numeric(frame.lf_input__plies, errors='coerce').to_numpy(dtype=float)
    long = plies[val] >= LONG
    calibration, prob, thresholds = {}, {}, {}
    for name, p in raw.items():
        calibration[name] = calibrate(p[val], yv)
        prob[name] = calibrated(calibration[name], p)
        thresholds[name] = choose_threshold(prob[name][train], y[train], prob[name][val], y[val])
    metrics = {name: dict(primary=ranking(yv, p[val]), secondary=ranking(yv[long], p[val][long]),
                          short_separation=short_separation(p[val], plies[val]),
                          calibration=calibration[name]['status'], **thresholds[name])
               for name, p in raw.items()}
    boot = bootstrap(frame.player_id.iloc[val].to_numpy(), yv, {n: p[val] for n, p in raw.items()}, long, PAIRS,
                     CANDIDATES, repetitions)
    for name in metrics:
        metrics[name]['primary']['ci95'] = boot['ci']['primary'][name]
        metrics[name]['secondary']['ci95'] = boot['ci']['secondary'][name]
    importance = {c: permutation_importance(fitted[c], frame, val, yv) for c in CANDIDATES}
    reference = float(y[np.concatenate([train, val])].mean())
    state = dict(y=y, train=train, val=val, fitted=fitted, raw=raw, prob=prob, thresholds=thresholds,
                 calibration=calibration, reference=reference, plies=plies)
    summary = dict(rows=dict(train=len(train), validation=len(val)), models=metrics, bootstrap=boot,
                   importance=importance, gain={c: fitted[c].gain() for c in CANDIDATES},
                   reference_prevalence_train_validation=reference)
    return state, summary


def test_stage(frame, state, repetitions=1000):
    """Reads the labelled test rows. Only called after the reproduction gate passed and validation.json was written."""
    y, raw, prob = state['y'], state['raw'], state['prob']
    test = np.flatnonzero((frame.split.to_numpy() == 'test') & np.isfinite(y))
    yt = y[test].astype(int)
    plies = state['plies'][test]
    long = plies >= LONG
    models = {}
    for name, p in raw.items():
        primary, secondary = ranking(yt, p[test]), ranking(yt[long], p[test][long])
        models[name] = dict(primary=primary | dict(lift=primary['pr_auc'] / primary['prevalence']),
                            secondary=secondary,
                            excess_ge40=secondary['pr_auc'] - secondary['prevalence'],
                            short_separation=short_separation(p[test], plies),
                            calibrated=calibration_metrics(yt, prob[name][test], state['thresholds'][name]['threshold'],
                                                           state['reference']))
    boot = bootstrap(frame.player_id.iloc[test].to_numpy(), yt, {n: p[test] for n, p in raw.items()}, long, PAIRS,
                     CANDIDATES, repetitions)
    for name in models:
        models[name]['primary']['ci95'] = boot['ci']['primary'][name]
        models[name]['secondary']['ci95'] = boot['ci']['secondary'][name]
    part = frame.iloc[test]
    prediction = part[['player_id', 'game_id', 'split', 'weak_tilt_label']].copy()
    for name in raw:
        prediction[name] = raw[name][test]
        prediction[f'{name}__calibrated'] = prob[name][test]
    summary = dict(rows=len(test), players=int(part.player_id.nunique()), models=models, bootstrap=boot,
                   subgroups=subgroups(part, yt, {n: p[test] for n, p in raw.items()}),
                   importance={c: permutation_importance(state['fitted'][c], frame, test, yt) for c in CANDIDATES})
    return summary, prediction


def registry_features(folder):
    folder = Path(folder)
    old = pd.read_csv(folder / 'feature_registry.csv').feature_name
    new = pd.read_csv(folder / 'phase2_feature_registry.csv').feature
    return set(old) | set(new)


def banned(feature):
    return (feature.startswith('lf_input__') or feature in ('result_score', 'plies', phase1.MIDDLEGAME)
            or feature.endswith('_p40') or feature in DEVIATIONS or forbidden(feature))


def gates(candidate, results, registered):
    """Section 5 of the preregistration, applied mechanically. Gate 8 is decided by `compare`."""
    va, ta, tb = (results[A]['validation'], results[A]['test'], results[B]['test'])
    features = XGB[candidate][0]
    nometa = NOMETA[candidate]

    def ap(t, name):
        return t['models'][name]['primary']['pr_auc']
    out = {}
    bad = [f for f in features if banned(f)]
    excess_low = ta['bootstrap']['excess_ge40'][candidate]['ci'][0]
    out['1'] = dict(passed=features == PREREGISTERED[candidate] and not bad and excess_low > 0
                    and tb['models'][candidate]['excess_ge40'] > 0,
                    feature_list_matches=features == PREREGISTERED[candidate], banned=bad,
                    excess_ge40_ci_low_A=excess_low, excess_ge40_B=tb['models'][candidate]['excess_ge40'])
    vs_a = {b: ta['bootstrap']['paired']['primary'][f'{candidate}-{b}']['ci'][0] for b in GATE_BASELINES}
    vs_b = {b: ap(tb, candidate) - ap(tb, b) for b in GATE_BASELINES}
    gate2_b = all(v > 0 for v in vs_b.values())
    out['2'] = dict(passed=all(v > 0 for v in vs_a.values()) and gate2_b, delta_ci_low_A=vs_a, delta_B=vs_b)
    out['3'] = dict(passed=ap(ta, candidate) >= FLOOR[A], pr_auc_A=ap(ta, candidate), floor=FLOOR[A])
    out['4'] = dict(passed=ap(tb, candidate) >= FLOOR[B] and gate2_b, pr_auc_B=ap(tb, candidate), floor=FLOOR[B],
                    gate2_B=gate2_b)
    ratio = {s: ap(results[s]['test'], nometa) / ap(results[s]['test'], candidate) for s in SPLITS}
    out['5'] = dict(passed=all(r >= META_KEEP for r in ratio.values()), nometa_ratio=ratio, minimum=META_KEEP)
    cal = {s: results[s]['test']['models'][candidate]['calibrated'] for s in SPLITS}
    out['6'] = dict(passed=all(cal[s]['brier_skill'] > 0 and cal[s]['ece'] <= ECE_MAX[s] for s in SPLITS),
                    brier_skill={s: cal[s]['brier_skill'] for s in SPLITS}, ece={s: cal[s]['ece'] for s in SPLITS},
                    ece_max=ECE_MAX)
    unregistered = [f for f in features if f not in registered]
    top3 = list(va['importance'][candidate])[:3]
    top5 = list(ta['importance'][candidate])[:5]
    overlap = [f for f in top3 if f in top5]
    out['7'] = dict(passed=not unregistered and len(overlap) >= 2, unregistered=unregistered,
                    validation_top3=top3, test_top5=top5, overlap=overlap)
    out['8'] = dict(passed=None, status='pending: decided by the compare command after the second run')
    out['all_1_to_7'] = all(out[k]['passed'] for k in '1234567')
    return out


def decide(results, registered):
    by = {c: gates(c, results, registered) for c in CANDIDATES}
    delta = {s: results[s]['test']['models']['P3-B']['primary']['pr_auc']
             - results[s]['test']['models']['M3']['primary']['pr_auc'] for s in SPLITS}
    if by['P3-B']['all_1_to_7'] and all(v > 0 for v in delta.values()):
        choice, rule = 'P3-B', 1
    elif by['M3']['all_1_to_7']:
        choice, rule = 'M3', 2
    else:
        choice, rule = None, 3
    comparable = ('P3-B', 'M3', 'E0', 'M1', 'P3-B-nometa', 'M3-nometa')
    best = {s: max(comparable, key=lambda n: results[s]['test']['models'][n]['primary']['pr_auc']) for s in SPLITS}
    return dict(gates=by, p3b_minus_m3_test=delta, provisional_choice=choice, rule=rule,
                highest_test_pr_auc_among_models=best, e0_highest=any(v == 'E0' for v in best.values()),
                status='provisional until gate 8 (compare)')


def save_artifact(out, choice, fitted, state, metadata):
    folder = Path(out) / 'artifact'
    folder.mkdir(parents=True, exist_ok=True)
    bundle = dict(variant=choice, split=A, notice=NOTICE, features=fitted.features, columns=fitted.columns,
                  imputer=fitted.imputer, keep=fitted.keep, scaler=fitted.scaler, classifier=fitted.model,
                  calibration=state['calibration'][choice], **state['thresholds'][choice])
    path = folder / f'{A}__{choice}.joblib'
    joblib.dump(bundle, path, compress=3)
    (folder / 'features.json').write_text(json.dumps(fitted.features, indent=1))
    metadata = metadata | dict(variant=choice, split=A, bundle=path.name, bundle_sha256=sha256_file(path),
                               threshold=state['thresholds'][choice], calibration=state['calibration'][choice]['status'])
    (folder / 'metadata.json').write_text(json.dumps(metadata, indent=1))
    return metadata


def metrics_table(results):
    rows = []
    for s in SPLITS:
        for stage in ('validation', 'test'):
            for name, m in results[s][stage]['models'].items():
                cal = m.get('calibrated', {})
                rows.append(dict(split=s, set=stage, model=name, n=m['primary']['n'],
                                 positives=m['primary']['positives'], prevalence=m['primary']['prevalence'],
                                 pr_auc=m['primary']['pr_auc'], pr_auc_ci_low=m['primary']['ci95'][0],
                                 pr_auc_ci_high=m['primary']['ci95'][1], roc_auc=m['primary']['roc_auc'],
                                 n_ge40=m['secondary']['n'], prevalence_ge40=m['secondary']['prevalence'],
                                 pr_auc_ge40=m['secondary']['pr_auc'], short_separation=m['short_separation'],
                                 brier=cal.get('brier'), brier_skill=cal.get('brier_skill'), ece=cal.get('ece'),
                                 threshold=cal.get('threshold'), precision=cal.get('precision'),
                                 recall=cal.get('recall'), f1=cal.get('f1'), flag_rate=cal.get('flag_rate')))
    return pd.DataFrame(rows)


def run(aligned, behavior, phase1_out, phase3_results, prereg, prereg_sha, registries, out, repetitions=1000,
        threads=2):
    start = time.monotonic()
    expected = Path(prereg_sha).read_text().split()[0]
    if sha256_file(prereg) != expected:
        raise SystemExit('Preregistration changed after it was hashed: refusing to run')
    aligned, out, phase1_out = Path(aligned), Path(out), Path(phase1_out)
    if (out / 'results.json').exists():
        raise SystemExit(f'{out} already holds a run; use a new folder (old results are never overwritten)')
    (out / 'predictions').mkdir(parents=True, exist_ok=True)
    registered = registry_features(registries)
    p1 = json.loads((phase1_out / 'phase1_results.json').read_text())
    p3 = json.loads(Path(phase3_results).read_text())
    target = {s: {'P3-B': p3[s]['validation']['P3-B']['primary']['pr_auc'],
                  'M3': p3[s]['validation']['M3']['primary']['pr_auc'],
                  'E0': p1[s]['validation']['E0']['pr_auc']} for s in SPLITS}
    src = Path(__file__).resolve().parents[1]
    code = {c: sha256_file(src / c) for c in CODE}
    extra = pd.read_parquet(behavior, columns=['player_id', 'game_id', *phase3.B])
    frames, states, results = {}, {}, dict(prereg_sha256=expected, code_sha256=code, notice=NOTICE,
                                           phase0_test_seen=PHASE0_TEST_SEEN, repetitions=repetitions, seed=42,
                                           models={n: list(XGB[n][0]) if n in XGB else OTHER[n]['features']
                                                   for n in MODELS})
    for s in SPLITS:
        frame = pd.read_parquet(aligned / f'aligned_{s}.parquet')
        rows = len(frame)
        frame = frame.merge(extra, on=['player_id', 'game_id'], how='left', validate='one_to_one')
        assert len(frame) == rows
        checks = phase1.split_checks(frame, s)
        checks['manifest_sha256'] = phase1.sha256(phase1.manifest(frame))
        old = pd.read_csv(phase1_out / 'manifests' / f'{s}.csv')
        checks['manifest_matches_phase1'] = checks['manifest_sha256'] == phase1.sha256(old)
        if not checks['manifest_matches_phase1']:
            raise SystemExit(f'{s}: split manifest differs from Phase 1')
        states[s], summary = validation_stage(frame, threads, repetitions)
        reproduction = {n: dict(value=summary['models'][n]['primary']['pr_auc'], target=target[s][n]) for n in REPRODUCE}
        for r in reproduction.values():
            r['ok'] = abs(r['value'] - r['target']) <= REPRODUCTION_TOLERANCE
        frames[s] = frame
        results[s] = dict(checks=checks, reproduction=reproduction, validation=summary)
        print(f'{s}: validation done', flush=True)
    gate = all(r['ok'] for s in SPLITS for r in results[s]['reproduction'].values())
    (out / 'validation.json').write_text(json.dumps({s: results[s] for s in SPLITS} | dict(reproduction_gate=gate),
                                                    indent=1))
    if not gate:
        raise SystemExit('Validation reproduction gate failed: test labels not read')
    for s in SPLITS:  # the test labels are read from here on
        results[s]['test'], prediction = test_stage(frames[s], states[s], repetitions)
        prediction.to_parquet(out / 'predictions' / f'test_{s}.parquet', index=False)
        print(f'{s}: test done', flush=True)
    results['decision'] = decide(results, registered)
    table = metrics_table(results)
    table.to_csv(out / 'metrics.csv', index=False)
    import sklearn
    import xgboost
    metadata = dict(seed=42, prereg_sha256=expected, code_sha256=code, notice=NOTICE,
                    manifest_sha256={s: results[s]['checks']['manifest_sha256'] for s in SPLITS},
                    metrics_sha256=sha256_file(out / 'metrics.csv'),
                    versions=dict(python=platform.python_version(), numpy=np.__version__, pandas=pd.__version__,
                                  sklearn=sklearn.__version__, xgboost=xgboost.__version__))
    choice = results['decision']['provisional_choice']
    results['artifact'] = (save_artifact(out, choice, states[A]['fitted'][choice], states[A], metadata)
                           if choice else dict(created=False, reason='no candidate passed gates 1-7') | metadata)
    results['elapsed_seconds'] = time.monotonic() - start
    (out / 'results.json').write_text(json.dumps(results, indent=1, default=float))
    return results


def differences(a, b, path='', found=None):
    """Largest absolute numeric difference and non-numeric mismatches between two JSON trees."""
    found = found if found is not None else dict(max_abs=0., mismatches=[])
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            if key in IGNORED:
                continue
            if key not in a or key not in b:
                found['mismatches'].append(f'{path}/{key}: missing')
            else:
                differences(a[key], b[key], f'{path}/{key}', found)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            found['mismatches'].append(f'{path}: length')
        for i, (x, y) in enumerate(zip(a, b)):
            differences(x, y, f'{path}/{i}', found)
    elif isinstance(a, bool) or isinstance(b, bool) or a is None or b is None or isinstance(a, str):
        if a != b:
            found['mismatches'].append(f'{path}: {a!r} != {b!r}')
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if not (np.isnan(a) and np.isnan(b)):
            found['max_abs'] = max(found['max_abs'], abs(a - b))
    elif a != b:
        found['mismatches'].append(f'{path}: type')
    return found


def compare(first, second):
    """Gate 8: the second run must reproduce the first to 1e-6. Writes final_decision.json into the first run."""
    first, second = Path(first), Path(second)
    one, two = (json.loads((p / 'results.json').read_text()) for p in (first, second))
    found = differences(one, two)
    for s in SPLITS:
        a = pd.read_parquet(first / 'predictions' / f'test_{s}.parquet')
        b = pd.read_parquet(second / 'predictions' / f'test_{s}.parquet')
        if not a[['player_id', 'game_id']].equals(b[['player_id', 'game_id']]):
            found['mismatches'].append(f'predictions {s}: rows differ')
            continue
        numbers = [c for c in a.columns if c not in ('player_id', 'game_id', 'split')]
        found['max_abs'] = max(found['max_abs'], float(np.nanmax(np.abs(a[numbers].to_numpy(float)
                                                                         - b[numbers].to_numpy(float)))))
    ok = found['max_abs'] <= REPRODUCIBLE and not found['mismatches']
    decision = one['decision']
    final = dict(gate_8=dict(passed=ok, max_abs_difference=found['max_abs'], mismatches=found['mismatches'][:50],
                             tolerance=REPRODUCIBLE),
                 choice=decision['provisional_choice'] if ok else None,
                 rule=decision['rule'] if ok else 3, provisional=decision['provisional_choice'],
                 artifact_sha256=dict(first=one['artifact'].get('bundle_sha256'),
                                      second=two['artifact'].get('bundle_sha256')))
    (first / 'final_decision.json').write_text(json.dumps(final, indent=1))
    return final


def main(argv=None):
    parser = argparse.ArgumentParser(description='Phase 5: pre-registered final model selection')
    sub = parser.add_subparsers(dest='command', required=True)
    r = sub.add_parser('run')
    r.add_argument('--aligned', required=True)
    r.add_argument('--behavior', required=True)
    r.add_argument('--phase1-out', required=True, help='folder with phase1_results.json and manifests/')
    r.add_argument('--phase3-results', required=True)
    r.add_argument('--prereg', required=True)
    r.add_argument('--prereg-sha256', required=True)
    r.add_argument('--registries', required=True, help='folder with the two feature registry CSV files')
    r.add_argument('--out', required=True)
    r.add_argument('--repetitions', type=int, default=1000)
    r.add_argument('--threads', type=int, default=2)
    c = sub.add_parser('compare')
    c.add_argument('first')
    c.add_argument('second')
    args = parser.parse_args(argv)
    if args.command == 'run':
        result = run(args.aligned, args.behavior, args.phase1_out, args.phase3_results, args.prereg,
                     args.prereg_sha256, args.registries, args.out, args.repetitions, args.threads)
        print(json.dumps(dict(decision={k: v for k, v in result['decision'].items() if k != 'gates'},
                              gates={c: {k: g[k]['passed'] if isinstance(g[k], dict) else g[k] for k in g}
                                     for c, g in result['decision']['gates'].items()}), indent=1))
    else:
        print(json.dumps(compare(args.first, args.second), indent=1))


if __name__ == '__main__':
    main()
