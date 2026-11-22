"""Locked S4 stages: p3b, train, report, gate, compare. No holdout evaluation.

Pure functions accept synthetic frames for tests. CLI stages verify the current
lock, append-only S3 snapshot, frozen code/data, and source content before/after.
The train command is operator work; it is never called on real data by tests.
"""
import argparse
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score, brier_score_loss
from threadpoolctl import threadpool_limits

from .train import calibrate, calibrated, predict_bundle
from ..features import prefix_features as prefix
from ..labels import dev_split as split
from ..evaluation import eval_metrics, p3b_features, model_fit, compare_p3b as whole

FITTED = ('M-v3', 'M-v3-ns', 'B-skill', 'P3-B/v3', 'P3-B@20/v3')
ADOPTION = ('P3-B/v3', 'R-pre', 'B-streak', 'B-skill')
UNFITTED = ('P3-B frozen', 'P3-B@20 frozen', 'R-pre', 'B-streak', 'B-length', 'B-result')
NORMAL = 'validation-only Platt scaling'
PARTS = ('V_A', 'V_B', 'pooled')
STRATA = ('all', 'lt20', '20to39', 'ge40', 'lt40')
KEYS = whole.KEYS
write_json = whole.write_json


def fold(player):
    return int(hashlib.sha256(('label-v3-cal-fold-1:' + player).encode()).hexdigest(), 16) % 2


def skill_columns(registry):
    selected = registry.loc[registry.column.eq('rating') | (
        registry.family.eq('baseline') & registry.column.str.endswith(('_median', '_mad'))), 'column'].tolist()
    if len(selected) != 15:
        raise ValueError('Skill family must contain exactly 15 registered columns')
    return selected


def matrix(frame, head, candidate, registry):
    """Accept S3 tables only. No whole-game join occurs in this path."""
    whole.refuse(frame)
    if candidate not in FITTED or candidate == 'P3-B/v3':
        raise ValueError('Whole-game comparator has a separate matrix path')
    excluded = [c for c in prefix.HISTORY if c not in set(registry.column)]
    base = prefix.model_matrix(frame, head, 'P3-B@20' if candidate == 'P3-B@20/v3' else 'M-v3', excluded)
    if not set(base) <= set(registry.column) or set(base) & whole.WHOLE_ONLY:
        raise ValueError('Unregistered or whole-game model input')
    skill = skill_columns(registry)
    if candidate == 'B-skill':
        base = base[skill]
    elif candidate == 'M-v3-ns':
        base = base.drop(columns=skill)
    return base


def train_rows(meta):
    whole.refuse(meta)
    if not meta.label.isin(['TILT', 'NOT', 'ABSTAIN']).all():
        raise ValueError('Unknown label')
    return np.flatnonzero((meta.part.eq('train') & meta.label.isin(['TILT', 'NOT'])).to_numpy())


def fit_head(frame, meta, candidate, threads=2):
    whole.refuse(meta)
    if len(frame) != len(meta) or not frame.index.equals(meta.index):
        raise ValueError('Head matrix and metadata are not aligned')
    rows = train_rows(meta)
    y = meta.label.map({'NOT': 0., 'TILT': 1.}).to_numpy(float)
    if int(np.count_nonzero(y[rows] == 1)) < 50:
        raise ValueError('Fewer than 50 positive labelled train rows')
    if len(np.unique(y[rows])) != 2:
        raise ValueError('Train head needs both classes')
    if threads != 2:
        raise ValueError('S4.2 fixes the classifier to threads=2')
    fitted = model_fit.Fitted(list(frame), True,
        p3b_features.NO_INDICATOR if candidate == 'P3-B/v3' else (), threads=2, seed=42)
    # Fit receives only labelled train rows; even imputer/scaler never see validation.
    fitted.fit(frame.iloc[rows], y[rows], np.arange(len(rows)))
    raw = fitted.predict(frame)
    cross, frozen, audit = calibrations(raw, meta)
    bundle = dict(features=fitted.features, columns=fitted.columns, imputer=fitted.imputer,
                  keep=fitted.keep, scaler=fitted.scaler, classifier=fitted.model,
                  calibration=frozen, format='phase5')
    return bundle, raw, cross, calibrated(frozen, raw), audit


def calibrations(raw, meta):
    """Cross-fitted validation scores; train scores use the frozen validation fit.

    Audit contains counts and fold membership, never private player/game keys.
    """
    whole.refuse(meta)
    y = meta.label.map({'NOT': 0., 'TILT': 1.}).to_numpy(float)
    validation = meta.part.isin(['V_A', 'V_B']).to_numpy()
    labelled = np.isfinite(y)
    folds = meta.player_id.map(fold).to_numpy()
    all_rows = np.flatnonzero(validation & labelled)
    frozen = calibrate(np.asarray(raw)[all_rows], y[all_rows].astype(int))
    result = calibrated(frozen, raw)
    audit = {'frozen': dict(status=frozen['status'], rows=len(all_rows)), 'cross': []}
    for held in (0, 1):
        source = np.flatnonzero(validation & labelled & (folds != held))
        destination = np.flatnonzero(validation & (folds == held))
        fit = calibrate(np.asarray(raw)[source], y[source].astype(int))
        if len(destination):
            result[destination] = calibrated(fit, np.asarray(raw)[destination])
        audit['cross'].append(dict(held_fold=held, source_fold=1-held, source_rows=len(source),
                                  scored_rows=len(destination), status=fit['status']))
    return result, frozen, audit


def composite(plies, pre, p20):
    plies, pre, p20 = np.asarray(plies), np.asarray(pre), np.asarray(p20)
    if not np.isfinite(p20[plies >= 20]).all() or not np.isfinite(pre).all():
        raise ValueError('Composite missing a required head score')
    return np.where(plies >= 20, p20, pre)


def validate_tables(meta, pre, p20, registry, whole_table):
    for frame in (meta, pre, p20, whole_table):
        whole.refuse(frame)
    if whole.keyset(meta) != whole.keyset(pre) or whole.keyset(meta) != whole.keyset(whole_table):
        raise ValueError('Target universe differs across tables')
    expected = whole.keyset(meta[meta.plies.ge(20)])
    if expected != whole.keyset(p20):
        raise ValueError('Prefix population differs from P-20')
    for frame in (pre, p20, whole_table):
        matched = meta[KEYS + ['part']].merge(frame[KEYS + ['part']], on=KEYS, suffixes=('_a', '_b'), validate='one_to_one')
        if not matched.part_a.eq(matched.part_b).all():
            raise ValueError('Split part changed')
    excluded = [c for c in prefix.HISTORY if c not in set(registry.column)]
    pd.testing.assert_frame_equal(registry.reset_index(drop=True), prefix.registry(excluded), check_dtype=False)
    if set(whole_table.columns) != set(KEYS + ['part', *whole.FEATURES]):
        raise ValueError('Whole-game table contains unexpected columns')


def ordered(frame, keys):
    return keys[KEYS].merge(frame, on=KEYS, validate='one_to_one')


def fit_all(meta, pre, p20, registry, whole_table, deployed, out, provenance, threads=2):
    """Train-only classifiers; nine heads, each with two cross and one frozen Platt."""
    validate_tables(meta, pre, p20, registry, whole_table)
    meta = meta.sort_values(KEYS).reset_index(drop=True)
    pre, whole_table = ordered(pre, meta), ordered(whole_table, meta)
    p20 = ordered(p20, meta[meta.plies.ge(20)])
    combined = pre.merge(p20, on=KEYS + ['part'], validate='one_to_one')
    # Check every head BEFORE any fitting; no partially fitted run on a head stop.
    for pop in (meta, meta[meta.plies.ge(20)]):
        rows = train_rows(pop)
        if int(pop.iloc[rows].label.eq('TILT').sum()) < 50:
            raise ValueError('Fewer than 50 positive labelled train rows')
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if (out / 'bundles').exists() or (out / 'predictions.parquet').exists():
        raise FileExistsError('Training output already exists; use a fresh run directory')
    (out / 'bundles').mkdir()
    result = meta[KEYS + ['part', 'label', 'plies', 'result_score']].copy()
    audit, bundle_names = {}, []
    for candidate in FITTED:
        heads = ('whole',) if candidate == 'P3-B/v3' else ('pre', 'p20')
        bundle = dict(candidate=candidate, prereg_sha256=whole.CURRENT_SHA,
                      code_sha256=provenance, heads={}, protocol='train only; all-validation frozen Platt; no refit')
        audit[candidate] = {}
        for head in heads:
            index = np.flatnonzero(meta.plies.ge(20).to_numpy()) if head == 'p20' else np.arange(len(meta))
            hmeta = meta.iloc[index].reset_index(drop=True)
            frame = (whole_table[list(whole.FEATURES)].copy() if head == 'whole' else
                     matrix(combined if head == 'p20' else pre, head, candidate, registry))
            fitted, raw, cross, frozen, details = fit_head(frame, hmeta, candidate, threads)
            bundle['heads'][head] = fitted
            audit[candidate][head] = details
            for kind, values in [('raw', raw), ('calibrated', cross), ('frozen', frozen)]:
                scores = np.full(len(meta), np.nan)
                scores[index] = values
                result[f'{candidate}::{head}::{kind}'] = scores
        for kind in ('raw', 'calibrated', 'frozen'):
            result[f'{candidate}::composite::{kind}'] = (
                result[f'{candidate}::whole::{kind}'] if heads == ('whole',) else composite(
                    meta.plies, result[f'{candidate}::pre::{kind}'], result[f'{candidate}::p20::{kind}']))
        name = candidate.replace('/', '_').replace('@', 'at') + '.joblib'
        joblib.dump(bundle, out / 'bundles' / name, compress=0)
        bundle_names.append(name)
    # Frozen references are scored, never recalibrated or used to train anything.
    result['P3-B frozen::composite::calibrated'] = predict_bundle(deployed, whole_table)[0]
    cut = matrix(combined, 'p20', 'P3-B@20/v3', registry).rename(
        columns={c: c.removeprefix('p20_') for c in combined if c.startswith('p20_')})
    score20 = np.full(len(meta), np.nan)
    score20[meta.plies.ge(20)] = predict_bundle(deployed, cut)[0]
    result['P3-B@20 frozen::composite::calibrated'] = score20
    for name, values in [('R-pre', prefix.r_pre(pre)), ('B-streak', pre.losing_streak_before),
                         ('B-length', meta.plies), ('B-result', 1-meta.result_score.fillna(0.5))]:
        if not np.isfinite(values).all():
            raise ValueError('Missing unfitted reference score')
        result[f'{name}::composite::calibrated'] = np.asarray(values, float)
    result.to_parquet(out / 'predictions.parquet', index=False)
    write_json(out / 'calibration_status.json', audit)
    (out / 'bundles.sha256').write_text(''.join(f'{split.sha(out / "bundles" / n)}  bundles/{n}\n' for n in sorted(bundle_names)))
    (out / 'code_hash.txt').write_text(''.join(f'{v}  {k}\n' for k, v in sorted(provenance.items())))
    write_json(out / 'training_provenance.json', dict(prereg_sha256=whole.CURRENT_SHA,
        code_sha256=provenance, classifier_threads=2, seed=42, trees=100,
        whole_table_sha256=split.sha(out / 'features_p3b_whole.parquet'),
        predictions_sha256=split.sha(out / 'predictions.parquet')))
    return result


def stratum(frame, name):
    return {'all': np.ones(len(frame), bool), 'lt20': frame.plies.lt(20).to_numpy(),
            '20to39': frame.plies.between(20, 39).to_numpy(),
            'ge40': frame.plies.ge(40).to_numpy(), 'lt40': frame.plies.lt(40).to_numpy()}[name]


def metric(y, scores, fitted):
    good = np.isfinite(y) & np.isfinite(scores)
    y, scores = y[good], scores[good]
    result = eval_metrics.ranking(y, scores)
    result['prevalence'] = float(y.mean()) if len(y) else None
    if fitted:
        bins, ece = eval_metrics.calibration_bins(y, scores) if len(y) else ([], None)
        result.update(brier=float(brier_score_loss(y, scores)) if len(y) else None,
                      ece=ece, reliability=bins)
    return result


def bootstrap(players, y, scores, pairs, repetitions=1000, seed=42):
    """Phase 5 draws: sorted player groups, paired samples, percentile intervals.

    Skip one-class draws (including no-positive draws), exactly as model_fit.bootstrap.
    Expose both skip reasons. Samples contain every row of each drawn player,
    repeated together if that player was drawn more than once.
    """
    players, y = np.asarray(players), np.asarray(y)
    if not len(y):
        return dict(ci={k: None for k in scores}, paired={f'{a}-{b}': None for a,b in pairs},
                    repetitions=repetitions, skipped=repetitions, no_positive=repetitions, one_class=0)
    rng = np.random.default_rng(seed)
    groups = pd.Series(np.arange(len(players))).groupby(players).apply(np.array).tolist()
    # Rank each fixed score once. Integer multiplicities reproduce physically
    # repeated rows, including tied scores, without sorting 1000 times per model.
    ranked = {}
    for name, values in scores.items():
        values = np.asarray(values)
        order = np.argsort(values, kind='mergesort')[::-1]
        starts = np.r_[0, np.flatnonzero(np.diff(values[order])) + 1]
        ranked[name] = (order, starts)
    def average_precision(name, weights):
        order, starts = ranked[name]
        count = np.add.reduceat(weights[order], starts)
        positives = np.add.reduceat(weights[order] * y[order].astype(int), starts)
        present = count > 0
        totals, tps = np.cumsum(count[present]), np.cumsum(positives[present])
        precision, recall = tps / totals, tps / tps[-1]
        # This is sklearn's non-interpolated AP summation, with integer counts.
        return float(-np.sum(np.diff(np.r_[recall[::-1], 0]) * precision[::-1]))
    draws = {name: [] for name in scores}
    delta = {f'{a}-{b}': [] for a, b in pairs}
    no_positive, one_class = 0, 0
    for _ in range(repetitions):
        rows = np.concatenate([groups[i] for i in rng.integers(0, len(groups), len(groups))])
        if not np.any(y[rows] == 1):
            no_positive += 1
            continue
        if len(np.unique(y[rows])) < 2:
            one_class += 1
            continue
        weights = np.bincount(rows, minlength=len(y))
        ap = {name: average_precision(name, weights) for name in scores}
        for name in draws:
            draws[name].append(ap[name])
        for a, b in pairs:
            delta[f'{a}-{b}'].append(ap[a]-ap[b])
    def ci(values):
        return [float(v) for v in np.quantile(values, [.025, .975])] if values else None
    return dict(ci={k: ci(v) for k, v in draws.items()},
                paired={k: dict(mean=float(np.mean(v)), ci=ci(v)) if v else None for k, v in delta.items()},
                repetitions=repetitions, skipped=no_positive+one_class, no_positive=no_positive, one_class=one_class)


def report(predictions, out, repetitions=1000):
    whole.refuse(predictions)
    if repetitions != 1000:
        raise ValueError('S4 bootstrap is fixed at 1000 resamples')
    out = Path(out)
    paths = ('metrics_validation.json', 'bootstrap_validation.json', 'length_auc.json')
    if any((out / name).exists() for name in paths):
        raise FileExistsError('Report output already exists')
    validation = predictions[predictions.part.isin(['V_A', 'V_B'])].reset_index(drop=True)
    labelled = validation[validation.label.isin(['TILT', 'NOT'])].reset_index(drop=True)
    metrics = {'validation': {}, 'train_heads': {}, 'score_kind': 'cross-fitted validation Platt',
               'ece_bins': '10 quantile bins; duplicate edges collapse; phase1.calibration_bins unchanged'}
    boot, lengths = {}, {}
    columns = [c for c in predictions if c.endswith('::calibrated')]
    for part in PARTS:
        part_frame = labelled if part == 'pooled' else labelled[labelled.part.eq(part)]
        metrics['validation'][part], boot[part], lengths[part] = {}, {}, {}
        for name in STRATA:
            frame = part_frame.loc[stratum(part_frame, name)]
            y = frame.label.map({'NOT': 0., 'TILT': 1.}).to_numpy(float)
            metrics['validation'][part][name] = {}
            available = {}
            for col in columns:
                candidate, head, _ = col.split('::')
                values = frame[col].to_numpy(float)
                metrics['validation'][part][name][candidate + '::' + head] = metric(y, values, candidate in FITTED)
                if head == 'composite' and np.isfinite(values).all():
                    available[candidate] = values
            pairs = [('M-v3', c) for c in ADOPTION if c in available]
            boot[part][name] = bootstrap(frame.player_id.to_numpy(), y, available, pairs, repetitions)
            # Restricted-population reference gets its own clustered CI.
            for col in columns:
                candidate, head, _ = col.split('::')
                key = candidate + '::' + head
                valid = np.isfinite(frame[col].to_numpy(float))
                sub = bootstrap(frame.loc[valid, 'player_id'].to_numpy(), y[valid],
                                {key: frame.loc[valid, col].to_numpy(float)}, [], repetitions)
                metrics['validation'][part][name][key]['pr_auc_ci95'] = sub['ci'][key]
                metrics['validation'][part][name][key]['bootstrap_skipped'] = sub['skipped']
            boot[part][name]['point_delta'] = {
                f'M-v3-{c}': float(average_precision_score(y, available['M-v3']) - average_precision_score(y, available[c]))
                if len(np.unique(y)) == 2 else None for c in ADOPTION if c in available}
        # Length diagnostics use labelled validation rows per S4.1, never ABSTAIN.
        for candidate in (*FITTED, *UNFITTED):
            col = candidate + '::composite::calibrated'
            values = part_frame[col].to_numpy(float)
            valid = np.isfinite(values)
            lengths[part][candidate] = {}
            for threshold in (20, 40):
                y = part_frame.plies.to_numpy()[valid] < threshold
                auc = float(roc_auc_score(y, values[valid])) if len(np.unique(y)) == 2 else None
                lengths[part][candidate][f'lt{threshold}'] = dict(n=int(valid.sum()), roc_auc=auc,
                    symmetric_auc=max(auc, 1-auc) if auc is not None else None)
    train = predictions[predictions.part.eq('train') & predictions.label.isin(['TILT', 'NOT'])]
    for col in columns:
        candidate, head, _ = col.split('::')
        if candidate in FITTED and head != 'composite':
            metrics['train_heads'][candidate + '::' + head] = metric(
                train.label.map({'NOT': 0., 'TILT': 1.}).to_numpy(float), train[col].to_numpy(float), True)
    write_json(out / paths[0], metrics)
    write_json(out / paths[1], boot)
    write_json(out / paths[2], lengths)
    return metrics, boot, lengths


def compare(first, second, output):
    """Every prediction/metric byte and every bundle must match, tolerance 0.0."""
    first, second = Path(first), Path(second)
    required = ['features_p3b_whole.parquet', 'p3b_parity.json', 'predictions.parquet',
                'metrics_validation.json', 'bootstrap_validation.json', 'length_auc.json',
                'bundles.sha256', 'code_hash.txt', 'calibration_status.json', 'training_provenance.json']
    files1 = sorted(p.relative_to(first).as_posix() for p in (first / 'bundles').glob('*.joblib'))
    files2 = sorted(p.relative_to(second).as_posix() for p in (second / 'bundles').glob('*.joblib'))
    if len(files1) != len(FITTED) or files1 != files2:
        raise ValueError('Missing or different candidate bundles')
    checks = {name: (first / name).is_file() and (second / name).is_file() and
              split.sha(first / name) == split.sha(second / name) for name in required + files1}
    maximum = 0.
    if (first / 'predictions.parquet').exists() and (second / 'predictions.parquet').exists():
        a, b = (pd.read_parquet(p / 'predictions.parquet') for p in (first, second))
        whole.refuse(a)
        whole.refuse(b)
        if list(a.columns) != list(b.columns) or a.shape != b.shape:
            maximum = None
        else:
            for col in a.select_dtypes(include='number'):
                x, y = a[col].to_numpy(float), b[col].to_numpy(float)
                if not np.array_equal(np.isnan(x), np.isnan(y)):
                    maximum = None
                    break
                finite = np.isfinite(x) & np.isfinite(y)
                if finite.any():
                    maximum = max(maximum, float(np.max(np.abs(x[finite]-y[finite]))))
    passed = all(checks.values()) and maximum == 0.
    record = dict(passed=passed, checks=checks, largest_absolute_prediction_difference=maximum,
                  run1_hashes={n: split.sha(first / n) for n in required + files1 if (first / n).is_file()},
                  run2_hashes={n: split.sha(second / n) for n in required + files2 if (second / n).is_file()})
    if Path(output).exists():
        raise FileExistsError('Determinism output already exists')
    write_json(output, record)
    return record


def gate(out, determinism, test_evidence):
    out = Path(out)
    metrics = json.loads((out / 'metrics_validation.json').read_text())
    boot = json.loads((out / 'bootstrap_validation.json').read_text())
    calibration = json.loads((out / 'calibration_status.json').read_text())
    det = json.loads(Path(determinism).read_text()) if determinism else None
    evidence = json.loads(Path(test_evidence).read_text())
    code = whole.code_hashes()
    checks = {}
    for part in ('V_A', 'V_B'):
        values = metrics['validation'][part]['all']
        a, b = (values[c + '::composite']['pr_auc'] for c in ('M-v3', 'R-pre'))
        checks[part + '_beats_R_pre'] = a is not None and b is not None and a > b
    ci = boot['pooled']['all']['paired']['M-v3-R-pre']
    checks['pooled_ci_positive'] = bool(ci and ci['ci'] and ci['ci'][0] > 0)
    required_heads = {'M-v3': {'pre', 'p20'}, 'P3-B/v3': {'whole'}, 'B-skill': {'pre', 'p20'}}
    checks['calibration_normal'] = all(set(calibration.get(c, {})) == heads and all(
        h['frozen']['status'] == NORMAL and len(h['cross']) == 2 and
        all(f['status'] == NORMAL and f['held_fold'] == i and f['source_fold'] == 1-i
            for i, f in enumerate(h['cross'])) for h in calibration[c].values())
        for c, heads in required_heads.items())
    checks['tests_and_isolation'] = bool(evidence.get('passed') and evidence.get('s3_leakage_passed') and
        evidence.get('code_sha256') == code and evidence.get('isolation_passed'))
    checks['parity'] = bool(json.loads((out / 'p3b_parity.json').read_text()).get('passed'))
    # First gate records pending determinism. The compare step finalizes it.
    checks['determinism'] = None if det is None else bool(det.get('passed') and any(
        hashes and all((out / n).is_file() and split.sha(out / n) == expected
                       for n, expected in hashes.items())
        for hashes in (det.get('run1_hashes', {}), det.get('run2_hashes', {}))))
    result = dict(checks=checks, passed=all(v is True for v in checks.values()),
        status='pending determinism' if checks['determinism'] is None and all(
            v is True for k, v in checks.items() if k != 'determinism') else
            ('passed' if all(v is True for v in checks.values()) else 'stopped'),
        code_sha256=code, prereg_sha256=whole.CURRENT_SHA)
    write_json(out / 's4_gate.json', result)
    return result


def load_training(args):
    wanted = whole.targets(args.s3)
    meta = pd.read_parquet(Path(args.s3) / 'labels_dev.parquet', columns=KEYS + [
        'part', 'label', 'plies', 'result_score'])
    meta = wanted[KEYS + ['part']].merge(meta, on=KEYS + ['part'], validate='one_to_one')
    if whole.keyset(meta) != whole.keyset(wanted):
        raise ValueError('Labels missing for target')
    pre = pd.read_parquet(Path(args.s3) / 'features_pre.parquet')
    p20 = pd.read_parquet(Path(args.s3) / 'features_p20.parquet')
    registry = pd.read_csv(Path(args.s3) / 'feature_registry.csv')
    table = pd.read_parquet(Path(args.out) / 'features_p3b_whole.parquet')
    parity = json.loads((Path(args.out) / 'p3b_parity.json').read_text())
    if (not parity.get('passed') or parity.get('sample') or
            parity.get('code_sha256') != whole.code_hashes() or
            parity.get('table_sha256') != split.sha(Path(args.out) / 'features_p3b_whole.parquet')):
        raise ValueError('Missing complete current parity evidence')
    deployed = whole.load_deployed(args.deployment_pointer, args.deployed_bundle)
    return meta, pre, p20, registry, table, deployed


def verify_run(args):
    whole.verify_inputs(args)
    for name in ('out', 'determinism'):
        if getattr(args, name, None):
            whole.verify_destination(getattr(args, name), args)
    out = Path(args.out)
    provenance = json.loads((out / 'training_provenance.json').read_text())
    if provenance['code_sha256'] != whole.code_hashes() or provenance['prereg_sha256'] != whole.CURRENT_SHA:
        raise ValueError('Training provenance differs from current code or lock')
    if provenance['predictions_sha256'] != split.sha(out / 'predictions.parquet'):
        raise ValueError('Predictions changed since training')
    if provenance['whole_table_sha256'] != split.sha(out / 'features_p3b_whole.parquet'):
        raise ValueError('Whole-game table changed since training')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='step', required=True)
    for step in ('p3b', 'train', 'report', 'gate', 'compare'):
        p = sub.add_parser(step)
        whole.common(p)
        p.add_argument('--threads', type=int, default=2,
                       help='native report thread limit; classifier is locked to 2')
        if step != 'compare':
            p.add_argument('--out', type=Path, required=True)
        if step in ('p3b', 'train'):
            p.add_argument('--deployment-pointer', type=Path, required=True)
            p.add_argument('--deployed-bundle', type=Path, required=True)
        if step == 'p3b':
            for name in ('phase5-aligned', 'phase5-behavior'):
                p.add_argument('--' + name, type=Path, required=True)
            p.add_argument('--processes', type=int, default=1)
            p.add_argument('--max-players', type=int, default=0)
        if step == 'gate':
            p.add_argument('--determinism', type=Path)
            p.add_argument('--test-evidence', type=Path, required=True)
        if step == 'compare':
            p.add_argument('--run1', type=Path, required=True)
            p.add_argument('--run2', type=Path, required=True)
            p.add_argument('--determinism', type=Path, required=True)
            p.add_argument('--test-evidence', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.threads < 1 or (args.step == 'train' and args.threads != 2):
        parser.error('training threads are fixed at 2; other thread limits must be positive')
    whole.verify_inputs(args)
    for name in ('out', 'determinism'):
        if getattr(args, name, None):
            whole.verify_destination(getattr(args, name), args)
    status = 0
    with threadpool_limits(limits=args.threads):
        if args.step == 'p3b':
            if args.processes < 1 or args.max_players < 0:
                parser.error('processes must be positive; max-players nonnegative')
            whole.run(args)
        elif args.step == 'train':
            fit_all(*load_training(args), args.out, whole.code_hashes(), args.threads)
        elif args.step == 'report':
            verify_run(args)
            report(pd.read_parquet(args.out / 'predictions.parquet'), args.out)
        elif args.step == 'gate':
            verify_run(args)
            result = gate(args.out, args.determinism, args.test_evidence)
            status = 2 if result['status'] == 'stopped' else 0
        else:
            result = compare(args.run1, args.run2, args.determinism)
            for out in (args.run1, args.run2):
                args.out = out
                verify_run(args)
                gate(out, args.determinism, args.test_evidence)
            status = 0 if result['passed'] and all(json.loads((p / 's4_gate.json').read_text())['passed']
                for p in (args.run1, args.run2)) else 2
    whole.verify_inputs(args)
    if status:
        raise SystemExit(status)


if __name__ == '__main__':
    main()
