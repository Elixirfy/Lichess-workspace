"""Behavioural proxy labels, isolated from the human annotation database.

All LF reads (including their temporal scope) are declared below. Label-model
parameters are fitted on the training partition separately for each split.
"""
from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..data import storage
from ..data.collect import usernames
from ..data.dataset import _safe_export, _split_player as _dataset_split_player
from .labels import private_id

ABSTAIN, NOT_TILT, TILT = -1, 0, 1
NOTICE = 'Behavioural proxies, not measured emotions. Metrics measure agreement with weak labels.'
SPLIT_POLICY = dict(by_player='60/20/20', by_time='70/85')
WEAK_VERSION = 3
LF_INPUT_PREFIX = 'lf_input__'
ENDING_INPUTS = ('status', 'plies', 'final_eval_cp', 'final_eval_mate')


def _split_player(pid):
    """Same stable hash/test bucket; enlarge weak-label validation only."""
    return _dataset_split_player(pid, validation_fraction=.2)


@dataclass(frozen=True)
class LF:
    name: str
    current: tuple[str, ...]
    future: tuple[str, ...] = ()
    past: tuple[str, ...] = ()

    @property
    def inputs(self):
        return self.current + self.past + self.future


LFS = (
    LF('abandon', ('status', 'result_score', 'final_eval_cp', 'final_eval_mate',
                   'last_adverse_distance', 'adverse_event', 'ply', 'eval_after_cp', 'eval_after_mate')),
    LF('early_resign', ('status', 'result_score', 'plies', 'final_eval_cp', 'final_eval_mate',
                        'last_adverse_distance', 'adverse_event', 'ply', 'eval_after_cp', 'eval_after_mate')),
    LF('carryover', ('start_ms', 'deviation_mean_cpl_z'),
       past=('previous_result_score', 'previous_end_upper_ms', 'previous_same_session', 'result_score', 'end_upper_ms')),
    LF('session_spiral', ('deviation_mean_cpl_z', 'start_ms'),
       past=('prior_session_loss_run', 'session_shrinking_gaps', 'rest_gap_seconds', 'result_score', 'end_upper_ms')),
    LF('normal_accuracy', ('mean_accuracy', 'baseline_mean_accuracy_median', 'deviation_mean_cpl_z') + ENDING_INPUTS),
    LF('rest_and_recover', ('end_upper_ms',) + ENDING_INPUTS,
       ('next_start_ms', 'next_end_upper_ms', 'next_deviation_mean_cpl_z', 'start_ms', 'deviation_mean_cpl_z')),
    LF('calm_play', ('adverse_events', 'mean_accuracy', 'baseline_mean_accuracy_median') + ENDING_INPUTS),
    LF('composed_loss', ('status', 'result_score', 'plies', 'final_eval_cp', 'final_eval_mate',
                         'end_upper_ms', 'ply', 'eval_after_cp', 'eval_after_mate'),
       ('next_start_ms', 'next_end_upper_ms', 'next_deviation_mean_cpl_z', 'start_ms', 'deviation_mean_cpl_z')),
    LF('expected_loss', ('result_score', 'rating_difference', 'rating', 'opponent_rating',
                         'mean_accuracy', 'baseline_mean_accuracy_median', 'deviation_mean_cpl_z') + ENDING_INPUTS),
    LF('fast_erratic_after_loss', ('start_ms', 'mean_think', 'baseline_mean_think_median', 'deviation_mean_cpl_z'),
       past=('previous_result_score', 'previous_end_upper_ms', 'previous_same_session', 'result_score', 'end_upper_ms')),
)


class LabelModel:
    """Symmetric Dawid–Skene EM conditional on non-abstain votes only.

    A fixed balanced class prior avoids estimating prevalence from one-sided LF
    coverage. Beta(6,2) pseudocounts regularise each conditional vote accuracy;
    projection to (.5, 1) fixes polarity. These are assumptions, not validation.
    Abstentions contribute exactly zero log evidence, regardless of the LF.
    """
    def fit(self, votes, iterations=150):
        votes = self._votes(votes)
        votes = votes[(votes != ABSTAIN).any(axis=1)]
        self.fitted_rows = len(votes)
        self.prior = .5
        self.accuracies = np.full(votes.shape[1], .75)
        for _ in range(iterations if len(votes) else 0):
            old = self.accuracies.copy()
            p = self.predict(votes)
            for j in range(votes.shape[1]):
                active = votes[:, j] != ABSTAIN
                correct = np.where(votes[active, j] == TILT, p[active], 1 - p[active]).sum()
                self.accuracies[j] = np.clip((correct + 6) / (active.sum() + 8), .500001, .999999)
            if np.max(np.abs(old - self.accuracies), initial=0) < 1e-7:
                break
        return self

    @staticmethod
    def _votes(votes):
        votes = np.asarray(votes)
        if votes.ndim != 2 or not np.isin(votes, [ABSTAIN, NOT_TILT, TILT]).all():
            raise ValueError('LF votes must be a matrix containing only -1, 0, 1')
        return votes.astype(int)

    def predict(self, votes):
        votes = self._votes(votes)
        if votes.shape[1] != len(self.accuracies):
            raise ValueError('LF count differs from fitted model')
        signed = np.where(votes == ABSTAIN, 0, 2 * votes - 1)
        log_odds = np.log(self.prior / (1 - self.prior)) + signed @ np.log(self.accuracies / (1 - self.accuracies))
        p = 1 / (1 + np.exp(-np.clip(log_odds, -35, 35)))
        p[(votes == ABSTAIN).all(axis=1)] = np.nan
        return p

    def state(self):
        a = self.accuracies
        emissions = np.stack([np.stack([a, 1-a], axis=1), np.stack([1-a, a], axis=1)], axis=1)
        return dict(prior=self.prior, prior_policy='fixed balanced; coverage is not prevalence evidence',
                    accuracies=a.tolist(), emissions=emissions.tolist(), abstention='ignored; class-independent',
                    fitted_rows=self.fitted_rows, status='fitted on train only' if self.fitted_rows else 'prior only: no covered training rows')


def vote(row):
    """Only declared LF inputs may be read here; context construction is separate."""
    def known(*names):
        return all(pd.notna(row.get(n)) for n in names)
    result = row.get('result_score')
    loss = pd.notna(result) and result == 0
    gap = (row['next_start_ms'] - row['end_upper_ms']) / 1000 if known('next_start_ms', 'end_upper_ms') else np.nan
    next_z = row.get('next_deviation_mean_cpl_z', np.nan)
    z = row.get('deviation_mean_cpl_z', np.nan)
    prior_gap = (row['start_ms'] - row['previous_end_upper_ms']) / 1000 if known('start_ms', 'previous_end_upper_ms') else np.nan
    after_loss = known('previous_result_score', 'previous_same_session') and row['previous_result_score'] == 0 and bool(row['previous_same_session'])
    normal = known('mean_accuracy', 'baseline_mean_accuracy_median') and row['mean_accuracy'] >= row['baseline_mean_accuracy_median']
    rested_normal = 300 <= gap <= 1800 and pd.notna(next_z) and abs(next_z) <= 1
    clearly_lost = (known('final_eval_cp') and row['final_eval_cp'] <= -500) or (known('final_eval_mate') and row['final_eval_mate'] < 0)
    # Normal play averages need a substantive sample and an interpretable end.
    # They cannot adjudicate abandonment or resignation from a viable position.
    orderly = known('plies', 'status') and row['plies'] >= 40 and (
        row['status'] in ('mate', 'stalemate', 'draw', 'outoftime') or
        (row['status'] == 'resign' and clearly_lost))
    abrupt_viable = known('final_eval_cp', 'last_adverse_distance') and (
        pd.isna(row.get('final_eval_mate')) and row['final_eval_cp'] > -150 and
        row['last_adverse_distance'] <= 6)
    return [
        TILT if loss and row.get('status') == 'timeout' and abrupt_viable else ABSTAIN,
        TILT if loss and row.get('status') == 'resign' and known('plies', 'final_eval_cp', 'last_adverse_distance')
        and pd.isna(row.get('final_eval_mate')) and row['plies'] <= 60 and row['final_eval_cp'] > -150
        and row['last_adverse_distance'] <= 6 else ABSTAIN,
        TILT if after_loss and 0 <= prior_gap <= 60 and pd.notna(z) and z >= 1.5 else ABSTAIN,
        TILT if known('prior_session_loss_run', 'session_shrinking_gaps') and row['prior_session_loss_run'] >= 3
        and row['session_shrinking_gaps'] and pd.notna(z) and z >= 1.5 else ABSTAIN,
        NOT_TILT if orderly and normal and pd.notna(z) and abs(z) <= 1 else ABSTAIN,
        NOT_TILT if orderly and rested_normal else ABSTAIN,
        NOT_TILT if orderly and normal and known('adverse_events') and row['adverse_events'] == 0 else ABSTAIN,
        NOT_TILT if loss and row.get('status') == 'resign' and known('plies') and row['plies'] >= 80
        and clearly_lost and rested_normal else ABSTAIN,
        NOT_TILT if orderly and loss and known('rating_difference', 'mean_accuracy', 'baseline_mean_accuracy_median')
        and row['rating_difference'] <= -200 and row['mean_accuracy'] >= row['baseline_mean_accuracy_median'] - 5
        and pd.notna(z) and abs(z) <= 1 else ABSTAIN,
        TILT if after_loss and 0 <= prior_gap <= 120 and known('mean_think', 'baseline_mean_think_median')
        and row['baseline_mean_think_median'] > 0 and row['mean_think'] <= .65 * row['baseline_mean_think_median']
        and pd.notna(z) and z >= 1 else ABSTAIN,
    ]


def load_cohort(data, users_file):
    users = usernames(users_file)
    if not users:
        raise ValueError('A nonempty --users-file is required; opponents must not enter the cohort')
    frame = pd.read_parquet(Path(data) / 'processed/features/games.parquet')
    frame = frame[frame.player.str.lower().isin(users)].copy()
    if frame.empty:
        raise ValueError('No feature rows for the supplied cohort')
    if (frame.baseline_latest_end_ms.notna() & (frame.baseline_latest_end_ms >= frame.start_ms)).any():
        raise ValueError('Non-prior baseline found')
    return frame.sort_values(['player', 'start_ms', 'game_id']).reset_index(drop=True)


def contexts(data, frame):
    """Label-only aftermath; never returned as model predictors."""
    raw = storage.read(data, 'games').set_index('game_id')
    moves = pd.read_parquet(Path(data) / 'processed/features/moves.parquet',
                            columns=['player', 'game_id', 'ply', 'eval_after_cp', 'eval_after_mate', 'adverse_event'])
    moves = moves.sort_values('ply')
    final_positions = moves.groupby('game_id', sort=False).tail(1).set_index('game_id')
    moves = moves[moves.player.isin(set(frame.player))]
    lookup = {}
    for key, group in moves.groupby(['player', 'game_id'], sort=False):
        adverse = group[group.adverse_event.fillna(False)]
        terminal = final_positions.loc[key[1]]
        sign = 1 if terminal.player == key[0] else -1
        lookup[key] = dict(final_eval_cp=sign * terminal.eval_after_cp if pd.notna(terminal.eval_after_cp) else np.nan,
                           final_eval_mate=sign * terminal.eval_after_mate if pd.notna(terminal.eval_after_mate) else np.nan,
                           last_adverse_distance=terminal.ply - adverse.ply.max() if len(adverse) else np.nan)
        # Audit upstream move quantities as game-level summaries as well as the
        # exact terminal/adverse quantities consumed by vote(). Never predictors.
        for column in ('ply', 'eval_after_cp', 'eval_after_mate', 'adverse_event'):
            values = pd.to_numeric(group[column], errors='coerce')
            for statistic in ('min', 'max', 'mean'):
                lookup[key][LF_INPUT_PREFIX + column + '__' + statistic] = getattr(values, statistic)()
    records, membership = [], []
    for _, group in frame.groupby('player', sort=False):
        entries = storage.records(group)
        for position, (index, row) in enumerate(zip(group.index, entries)):
            source = raw.loc[row['game_id']]
            ctx = {**row, **lookup.get((row['player'], row['game_id']), {}),
                   'status': source.status, 'plies': source.plies}
            deps = {row['game_id']}
            ends = [row['end_upper_ms']]
            nxt = entries[position + 1] if position + 1 < len(entries) else None
            if nxt and row['end_upper_ms'] is not None and nxt['start_ms'] is not None and nxt['start_ms'] >= row['end_upper_ms'] and nxt['end_upper_ms'] is not None:
                ctx['next_start_ms'] = nxt['start_ms']
                # Only LFs with rest-gap support inspect next-game performance.
                if nxt['start_ms'] - row['end_upper_ms'] <= 1800000:
                    ctx.update(next_end_upper_ms=nxt['end_upper_ms'],
                               next_deviation_mean_cpl_z=nxt.get('deviation_mean_cpl_z'))
                    deps.add(nxt['game_id'])
                    ends.append(nxt['end_upper_ms'])
            # Only completed prior games may supply loss/run/requeue context.
            completed = group[(group.end_upper_ms < row['start_ms']) & (group.start_ms < row['start_ms'])]
            previous = completed.iloc[-1] if len(completed) else None
            if previous is not None:
                ctx.update(previous_result_score=previous.result_score, previous_end_upper_ms=previous.end_upper_ms,
                           previous_same_session=previous.session_id == row['session_id'])
                deps.add(previous.game_id)
            prior = completed[completed.session_id == row['session_id']]
            run = 0
            for value in reversed(prior.result_score.tolist()):
                if pd.isna(value) or value != 0:
                    break
                run += 1
            gaps = prior.rest_gap_seconds.tail(2).tolist() + [(row['start_ms'] - previous.end_upper_ms) / 1000 if previous is not None else np.nan]
            gaps = pd.Series(gaps, dtype=float)
            ctx['prior_session_loss_run'] = run
            ctx['session_shrinking_gaps'] = len(gaps) == 3 and gaps.notna().all() and bool((gaps.to_numpy()[1:] < gaps.to_numpy()[:-1]).all()) and bool((gaps >= 0).all())
            # Retain magnitudes, not just the boolean comparison used by the LF.
            for number, value in enumerate(gaps):
                ctx[LF_INPUT_PREFIX + 'session_gap_' + str(number)] = value
            deps.update(prior.game_id)
            ctx['label_end_upper_ms'] = max(ends) if all(pd.notna(v) for v in ends) else np.nan
            records.append((index, ctx))
            membership.append((index, deps))
    ordered = pd.DataFrame([r for _, r in sorted(records)]).reset_index(drop=True)
    return ordered, [ids for _, ids in sorted(membership)]


def lf_quantities(ctx):
    """Privacy-safe scalar LF evidence; includes temporal differences/aliases.

    Every declared scalar source has a column, even when entirely missing.
    Move-array sources have summaries from contexts instead. Categorical status
    is encoded by the train-only audit, never by arbitrary integer ordering.
    """
    quantities = {c: ctx[c] for c in ctx if c.startswith(LF_INPUT_PREFIX)}
    arrays = {'ply', 'eval_after_cp', 'eval_after_mate', 'adverse_event'}
    for column in sorted({c for lf in LFS for c in lf.inputs} - arrays):
        quantities[LF_INPUT_PREFIX + column] = ctx.get(column, pd.Series(np.nan, index=ctx.index))
    for name, start, end in (('next_rest_gap_seconds', 'next_start_ms', 'end_upper_ms'),
                             ('previous_rest_gap_seconds', 'start_ms', 'previous_end_upper_ms')):
        quantities[LF_INPUT_PREFIX + name] = (ctx.get(start, pd.Series(np.nan, index=ctx.index)) -
                                               ctx.get(end, pd.Series(np.nan, index=ctx.index))) / 1000
    # Own move count is the direct analogue of board plies, including FEN games.
    quantities[LF_INPUT_PREFIX + 'move_count'] = ctx.get('move_count', pd.Series(np.nan, index=ctx.index))
    return pd.DataFrame(quantities, index=ctx.index)


def split_rows(frame, membership):
    by_player = frame.player_id.map(_split_player).to_numpy(dtype=object)
    # Dependency games include future label games, not only the predicted game.
    holdouts = {part: set().union(*(ids for ids, p in zip(membership, by_player) if p == part))
                for part in ('validation', 'test')}
    for i, (ids, part) in enumerate(zip(membership, by_player.copy())):
        if (part == 'train' and ids & (holdouts['test'] | holdouts['validation'])) or (part == 'validation' and ids & holdouts['test']):
            by_player[i] = 'purged_shared_game'
    starts = sorted(frame.start_ms.dropna().unique())
    if not starts:
        raise ValueError('No start times for time split')
    validation, test = (int(starts[min(len(starts) - 1, int(f * len(starts)))]) for f in (.7, .85))
    by_time = []
    for row in frame.itertuples():
        end = row.label_end_upper_ms
        if pd.isna(row.start_ms) or pd.isna(end):
            part = 'excluded_unknown_end'
        elif end < validation:
            part = 'train'
        elif row.start_ms >= test:
            part = 'test'
        elif row.start_ms >= validation and end < test:
            part = 'validation'
        else:
            part = 'purged_crossing_cutoff'
        by_time.append(part)
    return dict(by_player=by_player, by_time=np.array(by_time)), dict(validation_ms=validation, test_ms=test)


def statistics(votes, model):
    active = votes != ABSTAIN
    conflict = (votes == TILT).any(axis=1) & (votes == NOT_TILT).any(axis=1)
    return dict(rows=len(votes), coverage=float(active.any(axis=1).mean()),
                overlap=float((active.sum(axis=1) > 1).mean()), conflict=float(conflict.mean()),
                lfs=[dict(name=lf.name, inputs=list(lf.inputs), current=list(lf.current), past=list(lf.past), future=list(lf.future),
                          coverage=float(active[:, j].mean()), votes=int(active[:, j].sum()),
                          overlap=int((active[:, j] & (active.sum(axis=1) > 1)).sum()),
                          conflict=int((active[:, j] & conflict).sum()), estimated_accuracy=float(model.accuracies[j]))
                     for j, lf in enumerate(LFS)])


def attach_labels(frame, votes, model):
    frame = frame.copy()
    frame['weak_tilt_prob'] = model.predict(votes)
    frame['weak_tilt_label'] = pd.array(np.where(frame.weak_tilt_prob.notna(), frame.weak_tilt_prob >= .5, None), dtype='Int64')
    counts = (votes != ABSTAIN).sum(axis=1)
    frame['weak_majority_prob'] = np.divide((votes == TILT).sum(axis=1), counts,
                                           out=np.full(len(votes), np.nan), where=counts > 0)
    for j, lf in enumerate(LFS):
        frame['lf_' + lf.name] = votes[:, j]
    return frame


def partition_balance(frame):
    balance = {}
    for part in sorted(set(frame.split) | {'train', 'validation', 'test'}):
        group = frame[frame.split == part]
        labelled = int(group.weak_tilt_label.notna().sum())
        positives = int(group.weak_tilt_label.eq(1).sum())
        balance[part] = dict(players=int(group.player_id.nunique()), rows=len(group),
                             labelled=labelled, positives=positives,
                             positive_rate=positives / labelled if labelled else None)
    return balance


def outcome_gate(frame):
    """Train covered rows with known outcomes only; no held-out threshold tuning."""
    covered = frame[frame.weak_tilt_label.notna() & frame.result_score.notna()]
    loss = covered.result_score.eq(0)
    agreement = float((covered.weak_tilt_label.astype(int) == loss.astype(int)).mean()) if len(covered) else None
    strata = {}
    for name, mask in (('losses', loss), ('non_losses', ~loss)):
        labels = covered.loc[mask, 'weak_tilt_label']
        rate = float(labels.mean()) if len(labels) else None
        strata[name] = dict(n=len(labels), weak_tilt_rate=rate, weak_not_tilt_rate=1-rate if rate is not None else None)
    failed = agreement is None or agreement > .75 or any(
        s['weak_tilt_rate'] is None or not .1 <= s['weak_tilt_rate'] <= .9 for s in strata.values())
    return dict(status='FAILED: label ≈ outcome' if failed else 'PASSED', failed=failed,
                labelled_rows=len(covered), excluded_unknown_outcome=int((frame.weak_tilt_label.notna() & frame.result_score.isna()).sum()),
                agreement=agreement, strata=strata, scope='train labelled rows with known outcome only',
                thresholds=dict(max_agreement=.75, min_class_fraction_per_outcome=.1))


def build(data, users_file):
    data = Path(data)
    frame = load_cohort(data, users_file)
    ctx, membership = contexts(data, frame)
    votes = np.array([vote(r) for r in storage.records(ctx)], dtype=int)
    exported = pd.DataFrame([_safe_export(r) for r in storage.records(frame)])
    exported = pd.concat([exported, lf_quantities(ctx)], axis=1)
    exported['label_end_upper_ms'] = ctx.label_end_upper_ms
    splits, cutoffs = split_rows(exported, membership)
    manifest = dict(title='Tilt weak-label model', notice=NOTICE, version=WEAK_VERSION, split_policy=SPLIT_POLICY, cutoffs=cutoffs,
                    players=int(frame.player.nunique()), games=int(frame.game_id.nunique()), rows=len(frame),
                    feature_manifest=json.loads((data / 'processed/features/manifest.json').read_text()), splits={})
    output = data / 'processed' / 'out'
    for name, partition in splits.items():
        train = partition == 'train'
        model = LabelModel().fit(votes[train])
        table = attach_labels(exported, votes, model)
        table['split'] = partition
        storage.write_frame(output / f'weak_{name}.parquet', table)
        stats = statistics(votes, model)
        stats.update(model=model.state(), outcome_gate=outcome_gate(table.loc[train]), training_rows=int(train.sum()),
                     labelled_rows=int(table.weak_tilt_label.notna().sum()),
                     positive_rows=int((table.weak_tilt_label == 1).sum()),
                     partition_balance=partition_balance(table),
                     partitions={p: int((partition == p).sum()) for p in sorted(set(partition))})
        manifest['splits'][name] = stats
        # Session unit: pool LF votes, then fit a separate model on train sessions.
        sessions, session_votes = [], []
        for (pid, sid), group in table.groupby(['player_id', 'session_id'], sort=True):
            values = votes[group.index]
            pooled = np.where((values == TILT).any(axis=0), TILT,
                              np.where((values == NOT_TILT).any(axis=0), NOT_TILT, ABSTAIN))
            parts = set(group.split)
            sessions.append(dict(player_id=pid, session_id=sid, game_count=len(group),
                                 split=next(iter(parts)) if len(parts) == 1 else 'purged_mixed_session'))
            session_votes.append(pooled)
        session_frame = pd.DataFrame(sessions)
        sv = np.asarray(session_votes)
        sm = LabelModel().fit(sv[session_frame.split == 'train'])
        session_frame = attach_labels(session_frame, sv, sm)
        storage.write_frame(output / f'weak_sessions_{name}.parquet', session_frame)
        stats['session_statistics'] = statistics(sv, sm)
        stats['session_statistics']['labelled_rows'] = int(session_frame.weak_tilt_label.notna().sum())
    manifest['salt_fingerprint'] = private_id('tilt-weak-model-salt-v1')
    (output / 'weak_manifest.json').write_text(json.dumps(manifest, indent=2))
    return {k: manifest[k] for k in ('players', 'games', 'rows', 'splits')}
