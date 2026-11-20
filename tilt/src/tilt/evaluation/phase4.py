"""Phase 4: what does the weak label encode? TRAIN rows only; validation and test labels are never read.

Descriptive analysis for reports/phase4_label_validation.md. Nothing here trains or selects a model. Needs TILT_SALT
(to map feature-table ids to the exported pseudonymous ids); the salt is never printed.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from ..labels.labels import private_id, pseudonym
from ..labels.weak_labels import LFS

LF = [f'lf_{lf.name}' for lf in LFS]
SPLITS = ('by_player', 'by_time')


def clock_summary(processed):
    """Per player and game: share of own moves with a low clock, and the lowest clock fraction."""
    moves = pd.read_parquet(Path(processed) / 'features/moves.parquet',
                            columns=['player', 'game_id', 'clock_pressure', 'clock_fraction'])
    moves['clock_pressure'] = moves.clock_pressure.eq('low').astype(float).where(moves.clock_pressure.notna())
    clock = moves.groupby(['player', 'game_id']).agg(pressure_share=('clock_pressure', 'mean'),
                                                     min_clock_fraction=('clock_fraction', 'min')).reset_index()
    clock['player_id'] = clock.pop('player').map(pseudonym)
    clock['game_id'] = clock.game_id.map(lambda g: private_id('game:' + g))
    return clock


def table(frame, groups):
    y = frame.weak_tilt_label
    out = {}
    for name, mask in groups.items():
        known = mask & y.notna()
        out[name] = dict(rows=int(mask.sum()),
                         coverage=round(float(y[mask].notna().mean()), 3) if mask.any() else None,
                         labelled=int(known.sum()),
                         tilt_rate=round(float(y[known].mean()), 3) if known.any() else None)
    return out


def auc(frame, column, mask=None):
    """Raw ROC-AUC of one quantity against the weak label (below .5 means higher values go with NOT_TILT)."""
    x = pd.to_numeric(frame[column], errors='coerce')
    keep = frame.weak_tilt_label.notna() & x.notna()
    if mask is not None:
        keep &= mask
    y = frame.weak_tilt_label[keep].astype(int)
    if y.nunique() < 2:
        return None
    return dict(n=int(keep.sum()), auc=round(float(roc_auc_score(y, x[keep])), 3))


def analyse(f):
    y = f.weak_tilt_label
    votes = f[LF]
    plies = pd.to_numeric(f.lf_input__plies, errors='coerce')
    status = f.lf_input__status
    loss, win, draw = f.result_score.eq(0), f.result_score.eq(1), f.result_score.eq(.5)
    prev_loss = pd.to_numeric(f.lf_input__previous_result_score, errors='coerce').eq(0)
    long = plies >= 40
    tilt_votes, not_votes = (votes == 1).any(axis=1), (votes == 0).any(axis=1)
    r = dict(train_rows=len(f), labelled=int(y.notna().sum()), tilt_rate=round(float(y.mean()), 4),
             speeds=f.speed.value_counts().to_dict())
    r['lf'] = {c: dict(tilt=int((votes[c] == 1).sum()), not_tilt=int((votes[c] == 0).sum())) for c in LF}
    r['vote_patterns'] = dict(only_tilt_votes=int((tilt_votes & ~not_votes).sum()),
                              only_not_votes=int((not_votes & ~tilt_votes).sum()),
                              conflicting=int((tilt_votes & not_votes).sum()),
                              no_vote=int((~tilt_votes & ~not_votes).sum()))
    r['labelled_tilt_from_only_tilt_votes'] = round(float(((y == 1) & tilt_votes & ~not_votes).sum() / (y == 1).sum()), 3)
    r['labelled_not_from_only_not_votes'] = round(float(((y == 0) & not_votes & ~tilt_votes).sum() / (y == 0).sum()), 3)
    adverse = pd.to_numeric(f.adverse_events, errors='coerce')
    r['adverse_events_zero_ge40'] = int((adverse[long] == 0).sum())

    # Q1: loss.
    r['q1_result'] = table(f, dict(loss=loss, draw=draw, win=win))
    r['q1_tilt_with_current_or_previous_loss'] = round(float((loss | prev_loss)[y == 1].mean()), 3)
    r['q1_tilt_with_current_loss'] = round(float(loss[y == 1].mean()), 3)
    r['q1_not_tilt_with_current_loss'] = round(float(loss[y == 0].mean()), 3)
    r['q1_long_games'] = table(f, dict(loss_ge40=loss & long, not_loss_ge40=~loss & f.result_score.notna() & long))

    # Q2: poor play.
    z = pd.to_numeric(f.deviation_mean_cpl_z, errors='coerce')
    bins = pd.cut(z, [-np.inf, -1, 0, 1, 1.5, np.inf], labels=['<-1', '-1..0', '0..1', '1..1.5', '>=1.5'])
    r['q2_cpl_z'] = table(f, {str(b): bins.eq(b) for b in bins.cat.categories} | {'missing': z.isna()})
    quality = ('deviation_mean_cpl_z', 'mean_cpl', 'mean_accuracy', 'blunder_rate')
    r['q2_auc'] = {c: auc(f, c) for c in quality}
    r['q2_auc_ge40'] = {c: auc(f, c, long) for c in quality}
    bad = z >= 1.5
    r['q2_bad_play_by_loss_context'] = table(f, dict(bad_after_loss=bad & prev_loss, bad_no_previous_loss=bad & ~prev_loss,
                                                     bad_current_loss=bad & loss, bad_current_win=bad & win))

    # Q3: time pressure.
    r['q3_status'] = table(f, {s: status.eq(s) for s in ('mate', 'resign', 'outoftime', 'timeout', 'draw', 'stalemate')})
    r['q3_status_ge40'] = table(f, {s: status.eq(s) & long for s in ('mate', 'resign', 'outoftime')})
    ps = f.pressure_share
    r['q3_pressure_share'] = table(f, dict(none=ps.eq(0), low=(ps > 0) & (ps <= .2), high=ps > .2, missing=ps.isna()))
    timing = ('pressure_share', 'min_clock_fraction', 'mean_think')
    r['q3_auc'] = {c: auc(f, c) for c in timing}
    r['q3_auc_ge40'] = {c: auc(f, c, long) for c in timing}
    r['q3_fast_erratic_share_of_tilt'] = round(float(((votes.lf_fast_erratic_after_loss == 1) & (y == 1)).sum() / (y == 1).sum()), 3)

    # Q4: attacking style; no LF reads these flags.
    style = ('attack_rate', 'risk_rate', 'sacrifice_rate', 'defensive_rate')
    r['q4_auc'] = {c: auc(f, c) for c in style}
    r['q4_auc_ge40'] = {c: auc(f, c, long) for c in style}
    r['q4_auc_loss_ge40'] = {c: auc(f, c, long & loss) for c in style}
    quartile = pd.qcut(pd.to_numeric(f.attack_rate, errors='coerce'), 4, labels=False, duplicates='drop')
    r['q4_attack_quartile_ge40'] = table(f, {f'Q{int(k) + 1}': quartile.eq(k) & long for k in sorted(quartile.dropna().unique())})

    # Q5: rating and speed.
    rating = pd.to_numeric(f.rating, errors='coerce')
    bands = {'<1200': rating < 1200, '1200-1599': (rating >= 1200) & (rating < 1600),
             '1600-1999': (rating >= 1600) & (rating < 2000), '>=2000': rating >= 2000}
    r['q5_rating'] = table(f, bands)
    r['q5_rating_ge40'] = table(f, {k: m & long for k, m in bands.items()})
    diff = pd.to_numeric(f.rating_difference, errors='coerce')
    r['q5_rating_difference'] = table(f, {'<=-200': diff <= -200, '-200..200': (diff > -200) & (diff < 200), '>=200': diff >= 200})
    counts = f[y.notna()].groupby('player_id').size()
    r['q5_players'] = dict(players=int(f.player_id.nunique()), labelled_per_player_median=float(counts.median()),
                           top5_players_share_of_labelled=round(float(counts.nlargest(5).sum() / counts.sum()), 3))
    return r


def run(data, out):
    processed = Path(data) / 'processed'
    clock = clock_summary(processed)
    report = {}
    for split in SPLITS:
        weak = pd.read_parquet(processed / f'out/weak_{split}.parquet')
        train = weak[weak.split == 'train']  # validation and test labels are not read
        train = train.merge(clock, on=['player_id', 'game_id'], how='left', validate='one_to_one')
        report[split] = analyse(train)
    Path(out).mkdir(parents=True, exist_ok=True)
    (Path(out) / 'phase4_analysis.json').write_text(json.dumps(report, indent=1, default=str))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description='Phase 4: train-only weak-label validation analysis')
    parser.add_argument('--data', default='data', help='tilt data folder (contains processed/)')
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    run(args.data, args.out)
    print('written', Path(args.out) / 'phase4_analysis.json')


if __name__ == '__main__':
    main()
