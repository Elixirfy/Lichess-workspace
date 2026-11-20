"""L1 proposals only: train-only diagnostics, with no predictive-model fitting.

Thresholds were fixed in ~/tilt-labels-v2/design_before_results.json before the
first audit. Nothing imports this module into the production label pipeline.
Labels are behavioural proxies; label-model accuracies are assumptions/EM
estimates, not estimates against independent human ground truth.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.metrics import roc_auc_score

from .weak_labels import ABSTAIN, NOT_TILT, TILT, LF_INPUT_PREFIX, LFS, LabelModel, vote as v1_vote

SCHEMES = ('floor40', 'symmetric20', 'speed_quality20')
LF_NAMES = {
    'v1': tuple(lf.name for lf in LFS),
    'floor40': tuple(lf.name for lf in LFS),
    'symmetric20': ('carryover', 'session_spiral', 'fast_erratic_after_loss', 'calm_rate'),
    'speed_quality20': ('fast_deterioration', 'calm_rate'),
}
BUCKETS = ('<20', '20–39', '40–59', '60–79', '>=80')


def _number(row, name):
    value = row.get(name)
    return float(value) if value is not None and pd.notna(value) else np.nan


def vote(row, scheme):
    """Vote from unprefixed LF context. Missing eligibility always abstains.

    floor40: exact v1 rules behind one shared >=40-plies gate.
    symmetric20: three v1 after-loss rules and revised calm_rate, all behind
    >=20 plies AND >=10 own moves. calm_rate requires |CPL z|<=1 and
    0<=adverse_events/own_moves<=.25; it reads no ending or result.
    speed_quality20: same gate/NOT rule; one TILT rule requires z>=1.5
    and 0<=think<=.65*positive personal think baseline, without a loss gate.
    """
    if scheme not in SCHEMES:
        raise ValueError(f'Unknown scheme: {scheme}')
    empty = [ABSTAIN] * len(LF_NAMES[scheme])
    plies = _number(row, 'plies')
    if scheme == 'floor40':
        return v1_vote(row) if np.isfinite(plies) and plies >= 40 else empty
    moves = _number(row, 'move_count')
    if not (np.isfinite(plies) and np.isfinite(moves) and plies >= 20 and moves >= 10):
        return empty
    z = _number(row, 'deviation_mean_cpl_z')
    events = _number(row, 'adverse_events')
    calm = np.isfinite(z) and abs(z) <= 1 and 0 <= events <= .25 * moves
    think = _number(row, 'mean_think')
    baseline = _number(row, 'baseline_mean_think_median')
    fast = np.isfinite(think) and np.isfinite(baseline) and baseline > 0 and 0 <= think <= .65 * baseline
    if scheme == 'speed_quality20':
        return [TILT if z >= 1.5 and fast else ABSTAIN, NOT_TILT if calm else ABSTAIN]
    start = _number(row, 'start_ms')
    previous_end = _number(row, 'previous_end_upper_ms')
    gap = (start - previous_end) / 1000
    same = row.get('previous_same_session')
    after_loss = (_number(row, 'previous_result_score') == 0 and
                  same is not None and pd.notna(same) and bool(same))
    shrinking = row.get('session_shrinking_gaps')
    spiral = (_number(row, 'prior_session_loss_run') >= 3 and
              shrinking is not None and pd.notna(shrinking) and bool(shrinking))
    return [
        TILT if after_loss and 0 <= gap <= 60 and z >= 1.5 else ABSTAIN,
        TILT if spiral and z >= 1.5 else ABSTAIN,
        TILT if after_loss and 0 <= gap <= 120 and fast and z >= 1 else ABSTAIN,
        NOT_TILT if calm else ABSTAIN,
    ]


class DiagnosticLabelModel(LabelModel):
    """Same EM as v1, exposing actual stopping diagnostics without editing v1."""
    def fit(self, votes, iterations=150, tolerance=1e-7):
        if iterations < 1 or tolerance <= 0:
            raise ValueError('Positive iteration budget and tolerance required')
        votes = self._votes(votes)
        votes = votes[(votes != ABSTAIN).any(axis=1)]
        self.fitted_rows = len(votes)
        self.prior = .5
        self.accuracies = np.full(votes.shape[1], .75)
        self.iterations_run = 0
        self.max_delta = 0.
        self.converged = not len(votes)
        for i in range(iterations if len(votes) else 0):
            old = self.accuracies.copy()
            p = self.predict(votes)
            for j in range(votes.shape[1]):
                active = votes[:, j] != ABSTAIN
                correct = np.where(votes[active, j] == TILT, p[active], 1 - p[active]).sum()
                self.accuracies[j] = np.clip((correct + 6) / (active.sum() + 8), .500001, .999999)
            self.iterations_run = i + 1
            self.max_delta = float(np.max(np.abs(old - self.accuracies), initial=0))
            if self.max_delta < tolerance:
                self.converged = True
                break
        self.tolerance = tolerance
        return self

    def state(self):
        return super().state() | dict(iterations=self.iterations_run, converged=self.converged,
                                     max_delta=self.max_delta, tolerance=self.tolerance)


def require_train(frame):
    """Fail closed before any feature/label statistic, even for mixed frames."""
    if 'split' not in frame or not frame['split'].eq('train').all():
        raise ValueError('Only an explicitly TRAIN-only frame is permitted')


def load_train(path):
    """Project LF evidence + v1 labels; apply TRAIN predicate at parquet scan.

    Schema is metadata only. No held-out feature/label table is materialised,
    counted, summarised, hashed, or exported by this audit.
    """
    columns = [c for c in pq.read_schema(path).names
               if c.startswith(LF_INPUT_PREFIX) or c in ('split', 'weak_tilt_label', 'weak_tilt_prob')]
    frame = pd.read_parquet(path, columns=columns, filters=[('split', '==', 'train')])
    require_train(frame)
    return frame.reset_index(drop=True)


def vote_matrix(frame, scheme):
    require_train(frame)
    if scheme not in ('v1', *SCHEMES):
        raise ValueError(f'Unknown scheme: {scheme}')
    context = frame.filter(regex='^' + LF_INPUT_PREFIX).rename(columns=lambda c: c[len(LF_INPUT_PREFIX):])
    fn = v1_vote if scheme == 'v1' else lambda row: vote(row, scheme)
    return np.asarray([fn(row) for row in context.to_dict('records')], dtype=int).reshape(len(frame), len(LF_NAMES[scheme]))


def lf_statistics(votes, names):
    active = votes != ABSTAIN
    covered = active.any(axis=1)
    overlap = active.sum(axis=1) > 1
    conflict = (votes == TILT).any(axis=1) & (votes == NOT_TILT).any(axis=1)
    rows = len(votes)
    def fraction(n, d):
        return float(n / d) if d else None
    per_lf = []
    for j, name in enumerate(names):
        fires = active[:, j]
        per_lf.append(dict(name=name, votes=int(fires.sum()), tilt_votes=int((votes[:, j] == TILT).sum()),
                           not_tilt_votes=int((votes[:, j] == NOT_TILT).sum()),
                           coverage=fraction(fires.sum(), rows),
                           firing_rate_among_covered=fraction(fires.sum(), covered.sum()),
                           overlap_rows=int((fires & overlap).sum()), conflict_rows=int((fires & conflict).sum()),
                           conflict_given_firing=fraction((fires & conflict).sum(), fires.sum())))
    pairs = []
    for j, first in enumerate(names):
        for k in range(j + 1, len(names)):
            joint = active[:, j] & active[:, k]
            pairs.append(dict(first=first, second=names[k], overlap_rows=int(joint.sum()),
                              conflict_rows=int((joint & (votes[:, j] != votes[:, k])).sum())))
    return dict(overlap_rows=int(overlap.sum()), conflict_rows=int(conflict.sum()),
                overlap_rate=fraction(overlap.sum(), rows), conflict_rate=fraction(conflict.sum(), rows),
                conflict_among_covered=fraction(conflict.sum(), covered.sum()), lfs=per_lf, pairs=pairs)


def summary(frame, votes, scheme):
    require_train(frame)
    model = DiagnosticLabelModel().fit(votes)
    p = model.predict(votes)
    y = np.where(np.isfinite(p), p >= .5, np.nan)
    covered = np.isfinite(y)
    positive = y == TILT
    n = len(frame)
    plies = pd.to_numeric(frame[LF_INPUT_PREFIX + 'plies'], errors='coerce').to_numpy(dtype=float)
    result = pd.to_numeric(frame[LF_INPUT_PREFIX + 'result_score'], errors='coerce').to_numpy(dtype=float)
    previous = pd.to_numeric(frame[LF_INPUT_PREFIX + 'previous_result_score'], errors='coerce').to_numpy(dtype=float)
    def group(mask):
        labelled = covered & mask
        return dict(rows=int(mask.sum()), labelled=int(labelled.sum()), tilt=int((positive & mask).sum()),
                    not_tilt=int(((y == NOT_TILT) & mask).sum()),
                    coverage=float(covered[mask].mean()) if mask.any() else None,
                    tilt_rate=float(y[labelled].mean()) if labelled.any() else None)
    buckets = pd.cut(plies, [-np.inf, 20, 40, 60, 80, np.inf], right=False, labels=BUCKETS)
    valid = covered & np.isfinite(plies)
    auc = float(roc_auc_score(y[valid], plies[valid])) if len(np.unique(y[valid])) == 2 else None
    v1 = frame.weak_tilt_label.to_numpy(dtype=float, na_value=np.nan)
    joint = covered & np.isfinite(v1)
    transitions = {f'{a}->{b}': int(((np.isnan(v1) if a == 'abstain' else v1 == a) &
                                    (np.isnan(y) if b == 'abstain' else y == b)).sum())
                   for a in (0, 1, 'abstain') for b in (0, 1, 'abstain')}
    by_result = {}
    for name, mask in [('loss', result == 0), ('draw', result == .5), ('win', result == 1),
                       ('unknown', ~np.isin(result, [0, .5, 1]))]:
        by_result[name] = group(mask) | dict(share_of_all_tilt=float((positive & mask).sum() / positive.sum())
                                           if positive.any() else None)
    r = dict(scheme=scheme, **group(np.ones(n, dtype=bool)),
             ply_buckets={b: group(np.asarray(buckets == b)) for b in BUCKETS},
             missing_plies=group(~np.isfinite(plies)), plies_roc_auc=auc,
             plies_direction_free_auc=max(auc, 1 - auc) if auc is not None else None,
             tilt_with_current_or_previous_loss=int((positive & ((result == 0) | (previous == 0))).sum()),
             tilt_with_current_or_previous_loss_share=float(((result == 0) | (previous == 0))[positive].mean())
             if positive.any() else None,
             tilt_loss_context_unknown=int((positive & ~((result == 0) | (previous == 0)) &
                                            (~np.isfinite(result) | ~np.isfinite(previous))).sum()),
             result=by_result, lf=lf_statistics(votes, LF_NAMES[scheme]), ds=model.state(),
             agreement_v1=dict(joint_labelled=int(joint.sum()),
                               agreement=float((y[joint] == v1[joint]).mean()) if joint.any() else None,
                               newly_labelled=int((covered & ~np.isfinite(v1)).sum()),
                               lost_labels=int((~covered & np.isfinite(v1)).sum()), transitions=transitions))
    if scheme == 'v1':
        old_p = frame.weak_tilt_prob.to_numpy(dtype=float, na_value=np.nan)
        both = np.isfinite(old_p) & np.isfinite(p)
        r['v1_reconstruction'] = dict(coverage_mismatches=int((covered != np.isfinite(v1)).sum()),
                                      label_mismatches=int((y[joint] != v1[joint]).sum()),
                                      max_probability_difference=float(np.max(np.abs(p[both] - old_p[both]), initial=0)))
    return r


def run(aligned, out):
    """Audit two existing split policies, fitting only the requested label model."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    target = out / 'audit_results.json'
    if target.exists():
        raise FileExistsError(f'Use a fresh output directory: {target}')
    results = dict(scope='TRAIN only; no predictive models; no held-out statistics', splits={})
    for split in ('by_player', 'by_time'):
        path = Path(aligned) / f'aligned_{split}.parquet'
        frame = load_train(path)
        digest = hashlib.sha256(frame.to_csv(index=False).encode()).hexdigest()
        results['splits'][split] = dict(source=str(path), train_projected_sha256=digest,
                                        train_rows=len(frame), schemes={})
        for scheme in ('v1', *SCHEMES):
            r = summary(frame, vote_matrix(frame, scheme), scheme)
            results['splits'][split]['schemes'][scheme] = r
        print(f'{split}: TRAIN audit complete', flush=True)
    target.write_text(json.dumps(results, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    flat, lfs, pairs, buckets, outcomes = [], [], [], [], []
    for split, split_result in results['splits'].items():
        for scheme, r in split_result['schemes'].items():
            key = dict(split=split, scheme=scheme)
            flat.append(key | {k: r[k] for k in ('rows', 'labelled', 'tilt', 'not_tilt', 'coverage', 'tilt_rate',
                                                'plies_roc_auc', 'plies_direction_free_auc',
                                                'tilt_with_current_or_previous_loss_share')} |
                        dict(agreement_v1=r['agreement_v1']['agreement'], ds_converged=r['ds']['converged'],
                             ds_iterations=r['ds']['iterations'], conflict_rows=r['lf']['conflict_rows']))
            lfs.extend(key | lf for lf in r['lf']['lfs'])
            pairs.extend(key | pair for pair in r['lf']['pairs'])
            buckets.extend(key | dict(bucket=b) | g for b, g in r['ply_buckets'].items())
            outcomes.extend(key | dict(result=b) | g for b, g in r['result'].items())
    for name, records in [('summary', flat), ('lf_inventory', lfs), ('lf_pairs', pairs),
                           ('ply_buckets', buckets), ('result_breakdown', outcomes)]:
        pd.DataFrame(records).to_csv(out / f'{name}.csv', index=False)
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--aligned', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    run(args.aligned, args.out)


if __name__ == '__main__':
    main()
