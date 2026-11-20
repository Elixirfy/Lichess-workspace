"""Frozen L2 deterministic post-loss proxy audit, isolated from the v1 pipeline.

The model predicts a behavioral proxy of tilt, not independently validated anger.
Only the grouped decile diagnostic fits anything; no predictive model is trained.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold

from .weak_labels import ABSTAIN, NOT_TILT, TILT, LF_INPUT_PREFIX
from .weak_labels_v2 import load_train, require_train

LF_NAMES = ('deteriorated', 'fast_erratic', 'steady')
COMMON_CURRENT = ('plies', 'move_count', 'start_ms')
COMMON_PAST = ('previous_result_score', 'previous_same_session', 'previous_end_upper_ms')
LF_PROVENANCE = {
    'deteriorated': dict(current=('deviation_mean_cpl_z',), past=(), future=()),
    'fast_erratic': dict(current=('deviation_mean_cpl_z', 'mean_think'),
                        past=('baseline_mean_think_median',), future=()),
    'steady': dict(current=('deviation_mean_cpl_z', 'adverse_events'), past=(), future=()),
}


def verify_design(path):
    """Check frozen bytes before loading data or computing any statistic."""
    path = Path(path)
    raw = path.read_bytes()
    lines = path.with_suffix('.sha256').read_text().splitlines()
    digest = hashlib.sha256(raw).hexdigest()
    if len(lines) != 2 or lines[0] != f'{digest}  {path.name}' or not lines[1].startswith('UTC '):
        raise ValueError('Frozen design hash mismatch or missing UTC timestamp')
    design = json.loads(raw)
    if lines[1] != 'UTC ' + design['frozen_at_utc']:
        raise ValueError('Frozen design timestamp mismatch')
    return design, digest


def number(row, key):
    value = row.get(key)
    if value is None or pd.isna(value):
        return np.nan
    try:
        return float(value)
    except (TypeError, ValueError):
        return np.nan


def common_gate(row, spec, parameters):
    plies, moves = number(row, 'plies'), number(row, 'move_count')
    previous = number(row, 'previous_result_score')
    same = row.get('previous_same_session')
    start, end = number(row, 'start_ms'), number(row, 'previous_end_upper_ms')
    gap = (start - end) / 1000
    return bool(np.isfinite([plies, moves, previous, start, end, gap]).all()
                and plies >= spec['min_plies'] and moves >= spec['min_move_count']
                and previous == 0 and isinstance(same, (bool, np.bool_)) and same
                and 0 <= gap <= parameters['gap_seconds'])


def vote(row, spec, parameters):
    """All three LFs use exactly one gate; own move_count is never inferred."""
    if not common_gate(row, spec, parameters):
        return [ABSTAIN] * 3
    z = number(row, 'deviation_mean_cpl_z')
    if not np.isfinite(z):
        return [ABSTAIN] * 3
    think = number(row, 'mean_think')
    baseline = number(row, 'baseline_mean_think_median')
    events = number(row, 'adverse_events')
    rate = events / number(row, 'move_count')
    fast = (np.isfinite([think, baseline]).all() and baseline > 0
            and 0 <= think <= .65 * baseline)
    return [TILT if z >= parameters['deteriorated_z'] else ABSTAIN,
            TILT if z >= parameters['fast_z'] and fast else ABSTAIN,
            NOT_TILT if z < parameters['steady_z'] and np.isfinite(rate)
            and 0 <= rate <= parameters['adverse_rate'] else ABSTAIN]


def aggregate(votes):
    votes = np.asarray(votes, dtype=int)
    if votes.ndim != 2 or votes.shape[1] != 3 or not np.isin(votes, [-1, 0, 1]).all():
        raise ValueError('Expected three deterministic LF votes per row')
    return np.where((votes == TILT).any(axis=1), TILT,
                    np.where((votes == NOT_TILT).any(axis=1), NOT_TILT, ABSTAIN))


def context_records(frame):
    require_train(frame)
    fields = set(COMMON_CURRENT + COMMON_PAST)
    fields.update(k for lf in LF_PROVENANCE.values() for side in ('current', 'past') for k in lf[side])
    return frame.reindex(columns=[LF_INPUT_PREFIX + k for k in sorted(fields)]).rename(
        columns=lambda c: c[len(LF_INPUT_PREFIX):]).to_dict('records')


def evidence(frame, spec, parameters):
    rows = context_records(frame)
    eligible = np.asarray([common_gate(r, spec, parameters) for r in rows], dtype=bool)
    votes = np.asarray([vote(r, spec, parameters) for r in rows], dtype=int).reshape(-1, 3)
    return eligible, votes, aggregate(votes)


def numeric(frame, field):
    if LF_INPUT_PREFIX + field not in frame:
        return np.full(len(frame), np.nan)
    return pd.to_numeric(frame[LF_INPUT_PREFIX + field], errors='coerce').to_numpy(dtype=float, na_value=np.nan)


def fraction(n, d):
    return float(n / d) if d else None


def group_summary(mask, y, eligible):
    known = mask & (y != ABSTAIN)
    return dict(rows=int(mask.sum()), common_gate_rows=int((mask & eligible).sum()),
                labelled=int(known.sum()), tilt=int((mask & (y == TILT)).sum()),
                not_tilt=int((mask & (y == NOT_TILT)).sum()),
                coverage_all_train=fraction(known.sum(), mask.sum()),
                coverage_common_gate=fraction(known.sum(), (mask & eligible).sum()),
                tilt_rate=fraction((mask & (y == TILT)).sum(), known.sum()))


def fit_deciles(plies, y):
    """No validation values enter either edges or empirical rates."""
    edges = np.unique(np.quantile(plies, np.arange(1, 10) / 10, method='linear'))
    bins = np.digitize(plies, edges, right=False)
    counts = np.bincount(bins, minlength=len(edges) + 1)
    tilt = np.bincount(bins, weights=y, minlength=len(edges) + 1)
    rates = np.full(len(counts), float(np.mean(y)))
    np.divide(tilt, counts, out=rates, where=counts > 0)
    return edges, rates, counts


class G6CannotCompute(ValueError):
    """The frozen protocol requires an immediate stop on an impossible G6."""


def decile_oof(plies, y, players, seed=None):
    # seed is accepted for compatibility but deliberately has no effect.
    if pd.isna(players).any() or len(np.unique(players)) < 5:
        raise G6CannotCompute('G6 impossible: missing player_id or fewer than five labelled TRAIN players')
    if len(np.unique(y)) != 2:
        raise G6CannotCompute('G6 impossible: labelled TRAIN has only one class')
    scores = np.full(len(y), np.nan)
    folds = []
    splitter = GroupKFold(n_splits=5)
    for i, (train, hold) in enumerate(splitter.split(plies, y, groups=players)):
        if set(players[train]) & set(players[hold]):
            raise AssertionError('G6 player leakage')
        if len(np.unique(y[train])) != 2:
            raise G6CannotCompute(f'G6 impossible: training fold {i} has only one class')
        edges, rates, counts = fit_deciles(plies[train], y[train])
        scores[hold] = rates[np.digitize(plies[hold], edges, right=False)]
        folds.append(dict(fold=i, fit_rows=len(train), oof_rows=len(hold),
                          internal_edges=edges.tolist(), tilt_rates=rates.tolist(),
                          fit_bin_counts=counts.tolist()))
    if not np.isfinite(scores).all():
        raise AssertionError('Incomplete OOF scores')
    auc = float(roc_auc_score(y, scores)) if len(np.unique(y)) == 2 else None
    return dict(auc=auc, folds=folds)


def structural_check(spec, parameters):
    """Finite boundary examples plus source read provenance; no real data."""
    expected = set(COMMON_CURRENT + COMMON_PAST)
    expected.update(k for item in LF_PROVENANCE.values() for side in ('current', 'past') for k in item[side])
    accessed = set()

    class Provenance(dict):
        def get(self, key, default=None):
            if key not in expected:
                raise AssertionError(f'Undeclared LF read: {key}')
            accessed.add(key)
            return super().get(key, default)

        def __getitem__(self, key):
            if key not in expected:
                raise AssertionError(f'Undeclared LF read: {key}')
            accessed.add(key)
            return super().__getitem__(key)

    # Length never enters an LF after the shared gate. Exercise every integer
    # length through 1000 plus a very long game; unit tests also cover boundaries.
    for plies in [*range(spec['min_plies'], 1001), 1000000]:
        row = dict(plies=plies, move_count=max(spec['min_move_count'], plies // 2),
                   start_ms=120000, previous_end_upper_ms=0,
                   previous_result_score=0, previous_same_session=True,
                   mean_think=6.5, baseline_mean_think_median=10., adverse_events=0)
        assert TILT in vote(Provenance(row | dict(deviation_mean_cpl_z=2.)), spec, parameters)
        assert NOT_TILT in vote(Provenance(row | dict(deviation_mean_cpl_z=-100.)), spec, parameters)
    assert accessed == expected
    return dict(passed=True, common_current=list(COMMON_CURRENT), common_past=list(COMMON_PAST),
                lf_provenance=LF_PROVENANCE, observed_read_set=sorted(accessed),
                argument='Above shared floors, LFs do not depend on plies; z=2 yields TILT and z=-100, events=0 yields NOT at any eligible length.')


def summary(frame, spec, parameters, seed):
    require_train(frame)
    eligible, votes, y = evidence(frame, spec, parameters)
    known = y != ABSTAIN
    plies = numeric(frame, 'plies')
    buckets = {}
    edges = [float(x) for x in spec['bucket_edges']]
    for name, lo, hi in zip(spec['bucket_labels'], edges[:-1], edges[1:]):
        buckets[name] = group_summary((plies >= lo) & (plies < hi), y, eligible)
    auc = float(roc_auc_score(y[known], plies[known])) if len(np.unique(y[known])) == 2 else None
    linear = max(auc, 1 - auc) if auc is not None else None
    rates = [g['tilt_rate'] for g in buckets.values()]
    spread = max(rates) - min(rates) if all(r is not None for r in rates) else None
    g6 = decile_oof(plies[known], y[known], frame.player_id.to_numpy()[known], seed)
    previous = numeric(frame, 'previous_result_score')
    same = frame[LF_INPUT_PREFIX + 'previous_same_session'].eq(True).fillna(False).to_numpy(dtype=bool)
    population = (previous == 0) & same
    conflicts = int(((votes == TILT).any(axis=1) & (votes == NOT_TILT).any(axis=1)).sum())
    pop = {name: dict(rows=int((y == c).sum()), previous_same_session_loss_rows=int(((y == c) & population).sum()),
                     share=fraction(((y == c) & population).sum(), (y == c).sum()))
           for name, c in [('tilt', TILT), ('not_tilt', NOT_TILT)]}
    all_rows = group_summary(np.ones(len(y), dtype=bool), y, eligible)
    current = numeric(frame, 'result_score')
    result_masks = dict(loss=current == 0, draw=current == .5, win=current == 1,
                        unknown=~np.isin(current, [0, .5, 1]))
    rating = numeric(frame, 'rating')
    rating_masks = {'<1200': np.isfinite(rating) & (rating < 1200),
                    '1200–1599': (rating >= 1200) & (rating < 1600),
                    '1600–1999': (rating >= 1600) & (rating < 2000),
                    '>=2000': np.isfinite(rating) & (rating >= 2000), 'unknown': ~np.isfinite(rating)}
    old = pd.to_numeric(frame.weak_tilt_label, errors='coerce').to_numpy(dtype=float, na_value=np.nan)
    joint = known & np.isin(old, [0, 1])
    old_known = np.isin(old, [0, 1])
    agreement = dict(intersection_rows=int(joint.sum()), agreement=fraction((y[joint] == old[joint]).sum(), joint.sum()),
                     newly_labelled=int((known & ~old_known).sum()), lost_labels=int((~known & old_known).sum()),
                     counts={f'v1_{a}_v2_{b}': int((joint & (old == a) & (y == b)).sum()) for a in [0, 1] for b in [0, 1]})
    return dict(**all_rows, buckets=buckets, plies_auc=auc, direction_free_auc=linear,
                bucket_tilt_rate_range=spread, g6=g6, population=pop, conflicts=conflicts,
                structure=structural_check(spec, parameters),
                lfs=[dict(name=name, votes=int((votes[:, j] != ABSTAIN).sum())) for j, name in enumerate(LF_NAMES)],
                current_result={k: group_summary(m, y, eligible) for k, m in result_masks.items()},
                rating_band={k: group_summary(m, y, eligible) for k, m in rating_masks.items()}, agreement_v1=agreement)


def score_gates(r, gates):
    g2 = gates['G2']
    return dict(G1=r['structure']['passed'],
                G2=bool(all(b['tilt'] >= g2['min_tilt_per_bucket'] and b['not_tilt'] >= g2['min_not_per_bucket']
                            for b in r['buckets'].values()) and r['tilt'] >= g2['min_total_tilt'] and r['labelled'] >= g2['min_labelled']),
                G3=r['coverage_common_gate'] is not None and r['coverage_common_gate'] >= gates['G3']['min_common_gate_coverage'],
                G4=r['direction_free_auc'] is not None and r['direction_free_auc'] <= gates['G4']['max_direction_free_plies_auc'],
                G5=r['bucket_tilt_rate_range'] is not None and r['bucket_tilt_rate_range'] <= gates['G5']['max_bucket_tilt_rate_range'],
                G6=r['g6']['auc'] is not None and r['g6']['auc'] <= gates['G6']['max_pooled_oof_auc'],
                G7=all(r['population'][k]['share'] == gates['G7'][f'previous_same_session_loss_share_{k}']
                       for k in ('tilt', 'not_tilt')) and r['conflicts'] == gates['G7']['max_conflicts'])


def fallback_reasons(results, design):
    return [f'{split}:{gate}' for split, r in results.items()
            for gate in design['fallback']['trigger_gates'] if not r['gates'][gate]]


def sensitivity_summary(frame, spec, parameters):
    """Exactly the seven predeclared report-only metrics; no gate or G6 fit."""
    _, votes, y = evidence(frame, spec, parameters)
    known = y != ABSTAIN
    plies = numeric(frame, 'plies')
    auc = float(roc_auc_score(y[known], plies[known])) if len(np.unique(y[known])) == 2 else None
    edges = [float(x) for x in spec['bucket_edges']]
    rates = [fraction(((y == TILT) & (plies >= lo) & (plies < hi)).sum(),
                      (known & (plies >= lo) & (plies < hi)).sum())
             for lo, hi in zip(edges[:-1], edges[1:])]
    return dict(labelled=int(known.sum()), tilt=int((y == TILT).sum()), not_tilt=int((y == NOT_TILT).sum()),
                tilt_rate=fraction((y == TILT).sum(), known.sum()),
                direction_free_auc=max(auc, 1 - auc) if auc is not None else None,
                bucket_tilt_rate_range=max(rates) - min(rates) if all(r is not None for r in rates) else None,
                conflicts=int(((votes == TILT).any(axis=1) & (votes == NOT_TILT).any(axis=1)).sum()))


def load_train_with_groups(path):
    """Reuse L1's TRAIN loader and add only the G6 group id with the same predicate."""
    frame = load_train(path)
    groups = pd.read_parquet(path, columns=['split', 'player_id'], filters=[('split', '==', 'train')])
    require_train(groups)
    if len(frame) != len(groups):
        raise ValueError('TRAIN projection alignment mismatch')
    frame = frame.drop(columns=['weak_tilt_prob'], errors='ignore')
    frame['player_id'] = groups.player_id.to_numpy()
    return frame


def run(aligned, out, design_path):
    design, digest = verify_design(design_path)  # Must precede output/statistics/data access.
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    target = out / 'results.json'
    if target.exists():
        raise FileExistsError(f'Refusing to overwrite old results: {target}')
    results = dict(design_sha256=digest, started_at_utc=datetime.now(timezone.utc).isoformat(),
                   scope=design['scope'], designs={}, fallback_computed=False)
    results['provenance'] = dict(source_sha256={str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [Path(__file__), Path(__file__).with_name('weak_labels_v2.py'), Path(__file__).with_name('weak_labels.py')]},
        packages={p: importlib.metadata.version(p) for p in ('numpy', 'pandas', 'pyarrow', 'scikit-learn')},
        loader='L1 load_train; separate TRAIN-filtered player_id projection; no player ids exported; stored v1 probability discarded',
        g6_splitter='GroupKFold(n_splits=5); no shuffle, no random_state; independent of seed')
    frames = {s: load_train_with_groups(Path(aligned) / f'aligned_{s}.parquet') for s in ('by_player', 'by_time')}
    for name in ('postloss20', 'postloss40'):
        if name == 'postloss40':
            reasons = fallback_reasons(results['designs']['postloss20'], design)
            results['fallback_reasons'] = reasons
            if not reasons:
                break
            results['fallback_computed'] = True
        results['designs'][name] = {}
        for split, frame in frames.items():
            verify_design(design_path)
            try:
                r = summary(frame, design['designs'][name], design['parameters'], design['seed'])
            except G6CannotCompute as error:
                results['designs'][name][split] = dict(gates={'G6': False}, error=str(error))
                results['stopped'] = dict(design=name, split=split, gate='G6', reason=str(error))
                results['verdict'] = 'Stopped: G6 cannot compute; no acceptance verdict'
                results['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
                verify_design(design_path)
                with target.open('x') as f:
                    f.write(json.dumps(results, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
                print(results['verdict'] + ': ' + str(error), flush=True)
                return results
            r['gates'] = score_gates(r, design['gates'])
            results['designs'][name][split] = r
            print(f'{name} {split}: ' + ', '.join(f'{g}={"PASS" if p else "FAIL"}' for g, p in r['gates'].items()), flush=True)
    accepted = [name for name, splits in results['designs'].items() if all(all(r['gates'].values()) for r in splits.values())]
    results['verdict'] = accepted[0] + ' accepted' if accepted else (
        'both failed => weak-label direction stops' if results['fallback_computed'] else 'postloss20 failed; fallback not authorised by trigger gates; weak-label direction stops')
    # Sensitivity follows the locked verdict and cannot affect it. No G6 fit here.
    for name, splits in results['designs'].items():
        for split, r in splits.items():
            r['sensitivity'] = []
            if name in design['sensitivity']['applies_to']:
                for params in design['sensitivity']['grid']:
                    verify_design(design_path)
                    r['sensitivity'].append(dict(parameters=params,
                        **sensitivity_summary(frames[split], design['designs'][name], params)))
    verify_design(design_path)
    results['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
    with target.open('x') as f:
        f.write(json.dumps(results, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    tables = {key: [] for key in ('gates', 'summary', 'buckets', 'current_result', 'rating_band', 'agreement_v1', 'sensitivity')}
    for name, splits in results['designs'].items():
        for split, r in splits.items():
            key = dict(design=name, split=split)
            tables['gates'].extend(key | dict(gate=g, passed=p) for g, p in r['gates'].items())
            tables['summary'].append(key | {k: r[k] for k in ('rows', 'common_gate_rows', 'labelled', 'tilt', 'not_tilt',
                'coverage_all_train', 'coverage_common_gate', 'direction_free_auc', 'bucket_tilt_rate_range', 'conflicts')} | dict(g6_auc=r['g6']['auc']))
            for table in ('buckets', 'current_result', 'rating_band'):
                tables[table].extend(key | dict(group=g) | item for g, item in r[table].items())
            tables['agreement_v1'].append(key | {k: v for k, v in r['agreement_v1'].items() if k != 'counts'} | r['agreement_v1']['counts'])
            tables['sensitivity'].extend(key | item['parameters'] | {k: v for k, v in item.items() if k != 'parameters'} for item in r['sensitivity'])
    for table, records in tables.items():
        path = out / f'{table}.csv'
        with path.open('x') as f:
            pd.DataFrame(records).to_csv(f, index=False)
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--aligned', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--design', required=True)
    args = parser.parse_args(argv)
    results = run(args.aligned, args.out, args.design)
    if 'stopped' in results:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
