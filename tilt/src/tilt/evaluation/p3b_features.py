"""Phase 3 evaluation: pre-registered behavioural variants on validation only; the test split stays sealed.

See reports/phase3_preregistration.md (variants, rules and implementation notes fixed before any run). Predictions are
of the weak label, not of anger.
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_sample_weight

from ..training.train import choose_threshold, numeric, tree_models
from . import eval_metrics

SPLITS = eval_metrics.SPLITS
M3 = list(eval_metrics.VARIANTS['M3']['features'])
RATES = ['attack_rate', 'risk_rate', 'defensive_rate', 'style_switch_rate']
D = [f'{r}_p40' for r in RATES]
B = ['attack_trend_3w', 'risk_volatility_3w', 'behavior_change_point']
NO_INDICATOR = set(B)
USED = D + B
VARIANTS = {
    'M3': M3,
    'P3-D': M3 + D,
    'P3-R': [f'{c}_p40' if c in RATES else c for c in M3],
    'P3-B': M3 + B,
    'P3-DB': M3 + D + B,
}
ADDITIONS = ('P3-D', 'P3-B', 'P3-DB')
DIAGNOSTIC = {'B-length': ['lf_input__plies']}
REFERENCE = {'by_player': .449, 'by_time': .370}
TOLERANCE = .005
NOISE = .05
LONG = 40


def design(frame, features, train):
    """Median imputation with missing indicators except for NO_INDICATOR columns, then scaling; train rows only."""
    values = numeric(frame, features)
    imputer = SimpleImputer(strategy='median', add_indicator=True, keep_empty_features=True).fit(values[train])
    x = imputer.transform(values)
    sources = imputer.indicator_.features_ if imputer.indicator_ is not None else np.array([], int)
    keep = list(range(len(features))) + [len(features) + i for i, s in enumerate(sources)
                                         if features[s] not in NO_INDICATOR]
    x = x[:, keep]
    return StandardScaler().fit(x[train]).transform(x).astype(np.float32)


def fit_predict(features, frame, y, train, threads=2, seed=42, indicator=True):
    if indicator:
        x = design(frame, features, train)
    else:  # B-length: the Phase 1 diagnostic had no indicator
        x = eval_metrics.design(frame, features, train, False)
    model = tree_models('xgboost', seed=seed, threads=threads, trees=100)[0]
    model.fit(x[train], y[train].astype(int), sample_weight=compute_sample_weight('balanced', y[train]))
    return model.predict_proba(x)[:, 1]


def ranking(y, p):
    return eval_metrics.ranking(y, p) | dict(prevalence=float(y.mean()) if len(y) else None)


def bootstrap(players, y, scores, long, base='M3', repetitions=1000, seed=42):
    """Player-cluster bootstrap shared by every model (paired differences); the secondary metric filters each
    resample to games of at least LONG plies after drawing players and skips one-class resamples."""
    rng = np.random.default_rng(seed)
    index = pd.Series(np.arange(len(players))).groupby(players).apply(np.array).tolist()
    keys = ('primary', 'secondary')
    draws = {k: {name: [] for name in scores} for k in keys}
    deltas = {k: {name: [] for name in scores if name != base} for k in keys}
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
                if name != base:
                    deltas[key][name].append(ap[name] - ap[base])

    def ci(values):
        return [float(np.quantile(values, .025)), float(np.quantile(values, .975))] if values else None
    return dict(ci={k: {n: ci(v) for n, v in d.items()} for k, d in draws.items()},
                paired={k: {n: dict(mean=float(np.mean(v)), ci=ci(v)) if v else None for n, v in d.items()}
                        for k, d in deltas.items()},
                skipped=skipped, repetitions=repetitions)


def eta2(score, plies):
    known = np.isfinite(score) & np.isfinite(plies)
    s, t = pd.Series(score[known]), pd.Series(plies[known])
    if s.nunique() < 2:
        return None
    groups = pd.qcut(s.rank(method='first'), 10, labels=False)
    between = t.groupby(groups.to_numpy()).apply(lambda g: len(g) * (g.mean() - t.mean()) ** 2).sum()
    return float(between / ((t - t.mean()) ** 2).sum())


def decide(results):
    """Pre-registered rules (section 4 and the implementation notes), applied mechanically."""
    a, b = SPLITS
    reproduction = {s: results[s]['validation']['M3']['primary']['pr_auc'] for s in SPLITS}
    reproduced = all(abs(reproduction[s] - REFERENCE[s]) <= TOLERANCE for s in SPLITS)
    out = dict(m3_reproduction=dict(values=reproduction, reference=REFERENCE, tolerance=TOLERANCE, ok=reproduced))
    if not reproduced:
        return out | dict(main=None, stopped='M3 reproduction outside tolerance: no rule applied')

    def delta(split, name, key='primary'):
        part = results[split]['validation'][name][key]['pr_auc'], results[split]['validation']['M3'][key]['pr_auc']
        return part[0] - part[1]

    def paired(split, name, key='primary'):
        return results[split]['bootstrap']['paired'][key][name]

    variants, accepted = {}, []
    for name in ADDITIONS:
        rule_a = delta(a, name) >= NOISE and paired(a, name)['ci'][0] > 0
        rule_b = delta(b, name) > 0
        rule_c = all(delta(s, name, 'secondary') > 0 for s in SPLITS)
        secondary_ci_positive = all(paired(s, name, 'secondary')['ci'][0] > 0 for s in SPLITS)
        verdict = ('accepted' if rule_a and rule_b and rule_c else
                   'gain from short games: not accepted' if rule_a and rule_b else
                   'signal on games >= 40 plies, not enough to accept' if secondary_ci_positive and not rule_a else
                   'not accepted')
        variants[name] = dict(rule_1a=rule_a, rule_1b=rule_b, rule_1c=rule_c, verdict=verdict,
                              primary_delta={s: delta(s, name) for s in SPLITS},
                              secondary_delta={s: delta(s, name, 'secondary') for s in SPLITS},
                              primary_ci={s: paired(s, name)['ci'] for s in SPLITS},
                              secondary_ci={s: paired(s, name, 'secondary')['ci'] for s in SPLITS})
        if verdict == 'accepted':
            accepted.append(name)
    replace = (all(delta(s, 'P3-R') > -NOISE for s in SPLITS)
               and all(paired(s, 'P3-R', 'secondary')['ci'][1] >= 0 for s in SPLITS))
    variants['P3-R'] = dict(rule_2=replace, primary_delta={s: delta(s, 'P3-R') for s in SPLITS},
                            secondary_delta={s: delta(s, 'P3-R', 'secondary') for s in SPLITS},
                            primary_ci={s: paired(s, 'P3-R')['ci'] for s in SPLITS},
                            secondary_ci={s: paired(s, 'P3-R', 'secondary')['ci'] for s in SPLITS})
    if accepted:
        best = max(results[a]['validation'][n]['primary']['pr_auc'] for n in accepted)
        close = [n for n in accepted if best - results[a]['validation'][n]['primary']['pr_auc'] < NOISE]
        main = min(close, key=lambda n: (len(VARIANTS[n]), -results[a]['validation'][n]['primary']['pr_auc']))
    else:
        main = 'P3-R' if replace else 'M3'
    return out | dict(variants=variants, accepted=accepted, main=main)


def run(aligned, behavior, out, repetitions=1000, threads=2, phase1_manifests=None):
    aligned, out = Path(aligned), Path(out)
    (out / 'predictions').mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    extra = pd.read_parquet(behavior, columns=['player_id', 'game_id', *USED])
    results = dict(seed=42, repetitions=repetitions, variants=VARIANTS | DIAGNOSTIC, no_indicator=sorted(NO_INDICATOR))
    for split in SPLITS:
        frame = pd.read_parquet(aligned / f'aligned_{split}.parquet')
        rows = len(frame)
        frame = frame.merge(extra, on=['player_id', 'game_id'], how='left', validate='one_to_one')
        assert len(frame) == rows
        checks = eval_metrics.split_checks(frame, split)
        checks['manifest_sha256'] = eval_metrics.sha256(eval_metrics.manifest(frame))
        if phase1_manifests:
            old = pd.read_csv(Path(phase1_manifests) / f'{split}.csv')
            checks['manifest_matches_phase1'] = checks['manifest_sha256'] == eval_metrics.sha256(old)
            if not checks['manifest_matches_phase1']:
                raise ValueError(f'{split}: split manifest differs from Phase 1')
        y = frame.weak_tilt_label.to_numpy(dtype=float, na_value=np.nan)
        known = np.isfinite(y)
        train = np.flatnonzero((frame.split == 'train').to_numpy() & known)
        val = np.flatnonzero((frame.split == 'validation').to_numpy() & known)
        assert not (frame.split.iloc[val] == 'test').any()  # sealed
        raw = {name: fit_predict(cols, frame, y, train, threads) for name, cols in VARIANTS.items()}
        raw |= {name: fit_predict(cols, frame, y, train, threads, indicator=False) for name, cols in DIAGNOSTIC.items()}
        yv = y[val].astype(int)
        plies = pd.to_numeric(frame.lf_input__plies, errors='coerce').to_numpy(dtype=float)[val]
        long = plies >= LONG
        scores = {name: p[val] for name, p in raw.items()}
        validation = {}
        for name, p in raw.items():
            threshold = choose_threshold(p[train], y[train], p[val], y[val])['threshold']
            summary = eval_metrics.metrics(yv, p[val], threshold)
            summary.pop('calibration')
            validation[name] = dict(primary=ranking(yv, p[val]), secondary=ranking(yv[long], p[val][long]),
                                    recorded=summary, eta2_plies=eta2(p[val], plies))
        boot = bootstrap(frame.player_id.iloc[val].to_numpy(), yv, scores, long, repetitions=repetitions)
        for name in validation:
            validation[name]['primary']['ci95'] = boot['ci']['primary'][name]
            validation[name]['secondary']['ci95'] = boot['ci']['secondary'][name]
        prediction = frame[['player_id', 'game_id', 'split', 'weak_tilt_label']].iloc[val].copy()
        for name, p in scores.items():
            prediction[name] = p
        prediction.to_parquet(out / 'predictions' / f'validation_{split}.parquet', index=False)
        results[split] = dict(checks=checks, validation=validation, bootstrap=boot,
                              subgroups=eval_metrics.subgroups(frame, val, yv, scores))
        print(f'{split}: done', flush=True)
    results['decision'] = decide(results)
    results['elapsed_seconds'] = time.monotonic() - start
    (out / 'phase3_results.json').write_text(json.dumps(results, indent=1))
    table = []
    for s in SPLITS:
        for name, v in results[s]['validation'].items():
            table.append(dict(split=s, model=name, columns=len((VARIANTS | DIAGNOSTIC)[name]),
                              n=v['primary']['n'], prevalence=v['primary']['prevalence'],
                              pr_auc=v['primary']['pr_auc'], pr_auc_ci_low=v['primary']['ci95'][0],
                              pr_auc_ci_high=v['primary']['ci95'][1],
                              n_ge40=v['secondary']['n'], prevalence_ge40=v['secondary']['prevalence'],
                              pr_auc_ge40=v['secondary']['pr_auc'], pr_auc_ge40_ci_low=v['secondary']['ci95'][0],
                              pr_auc_ge40_ci_high=v['secondary']['ci95'][1], roc_auc=v['primary']['roc_auc'],
                              brier=v['recorded']['brier'], ece=v['recorded']['ece'], eta2_plies=v['eta2_plies']))
    pd.DataFrame(table).to_csv(out / 'phase3_metrics.csv', index=False)
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description='Phase 3: pre-registered validation-only evaluation')
    parser.add_argument('--aligned', required=True, help='folder with the Phase 1 aligned_by_player/by_time.parquet')
    parser.add_argument('--behavior', required=True, help='Phase 2 behavior_features.parquet')
    parser.add_argument('--out', required=True)
    parser.add_argument('--phase1-manifests', help='Phase 1 manifests folder; the splits must be identical')
    parser.add_argument('--repetitions', type=int, default=1000)
    parser.add_argument('--threads', type=int, default=2)
    args = parser.parse_args(argv)
    result = run(args.aligned, args.behavior, args.out, args.repetitions, args.threads, args.phase1_manifests)
    print(json.dumps(result['decision'], indent=1))


if __name__ == '__main__':
    main()
