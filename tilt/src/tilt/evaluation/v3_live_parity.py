"""I1 gate: the live M-v3 path reproduces S3 features/labels and S4 scores exactly.

Development players only, chosen by a fixed hash order. Every comparison is exact
(max |diff| 0, nulls equal). The output holds counts only, never identifiers.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

import joblib
import numpy as np
import pandas as pd

from ..core import live_v3 as live
from ..features import prefix_v3 as prefix
from ..labels import split_v3 as split

KEYS = split.KEYS
HEADER_COMPARED = ['session_id', 'start_ms', 'end_ms', 'end_upper_ms', 'rating', 'opponent_rating',
                   'result_score', 'speed', *prefix.HISTORY, 'status', 'plies', 'rated',
                   'initial_seconds', 'increment_seconds', 'white_rating', 'black_rating']
SCORES = [f'M-v3::{h}::frozen' for h in ('pre', 'p20', 'composite')]


def order(cohort, player_id):
    return hashlib.sha256(f'live-v3-parity-1:{cohort}:{player_id}'.encode()).hexdigest()


def same(actual, expected, name):
    """Exact frame equality on keys, columns, nulls and values."""
    if set(actual.columns) != set(expected.columns):
        raise ValueError(f'{name}: column inventory differs')
    a = actual.sort_values(KEYS).reset_index(drop=True)[list(expected.columns)]
    b = expected.sort_values(KEYS).reset_index(drop=True)
    if len(a) != len(b) or a.duplicated(KEYS).any() or not a[KEYS].equals(b[KEYS]):
        raise ValueError(f'{name}: row inventory differs')
    for c in b.columns:
        if not a[c].isna().equals(b[c].isna()):
            raise ValueError(f'{name}: null mismatch in {c}')
        good = b[c].notna()
        if not a.loc[good, c].eq(b.loc[good, c]).all():
            raise ValueError(f'{name}: value mismatch in {c}')
    return len(a)


def choose(manifest, drops, per_cohort, with_drops):
    dev = manifest[manifest.part.isin(split.PARTS)][['cohort', 'player_id']].drop_duplicates()
    dev = dev.assign(key=[order(c, p) for c, p in dev.itertuples(index=False)]).sort_values('key')
    chosen = pd.concat([g.head(per_cohort) for _, g in dev.groupby('cohort', sort=True)])
    extra = dev.merge(drops[['cohort', 'player_id']].drop_duplicates(), on=['cohort', 'player_id'])
    extra = extra[~extra.key.isin(chosen.key)].head(with_drops)
    return pd.concat([chosen, extra]).sort_values(['cohort', 'key']).reset_index(drop=True)


def to_s3(frame, keymap, parts):
    out = frame.drop(columns=['cohort', 'player_id', 'part']).merge(
        keymap.rename(columns={'game_id': 'key_game'}), left_on=['game_id', 'color'],
        right_on=['raw_game_id', 'color'], validate='one_to_one')
    out = out.drop(columns=['game_id', 'raw_game_id']).rename(columns={'key_game': 'game_id'})
    return out.merge(parts, on=KEYS, validate='one_to_one')


def run(args):
    start = time.monotonic()
    live.check_frozen()
    registry = pd.read_csv(args.s3 / 'feature_registry.csv')
    model = live.validated(dict(bands=live.BANDS), joblib.load(args.bundle), registry)
    if live.sha256_file(args.bundle) != live.BUNDLE_SHA:
        raise ValueError('Not the adopted M-v3 bundle')
    headers = split.load_headers(args.old_root, args.new_root, args.s2)
    manifest = pd.read_parquet(args.s3 / 'dev_split_manifest.parquet', columns=KEYS + ['part'])
    drops = pd.read_csv(args.s3 / 'excluded_incomplete_moves.csv')
    players = choose(manifest, drops, args.per_cohort, args.with_drops)
    wanted = players[['cohort', 'player_id']]
    refs = {name: pd.read_parquet(args.s3 / name).merge(wanted, on=['cohort', 'player_id'])
            for name in ('labels_dev.parquet', 'features_pre.parquet', 'features_p20.parquet')}
    predictions = pd.read_parquet(args.s4 / 'predictions.parquet', columns=KEYS + SCORES).merge(
        wanted, on=['cohort', 'player_id'])
    out = dict(players={c: int(n) for c, n in players.cohort.value_counts().sort_index().items()},
               header_rows=0, targets=0, rows={k: 0 for k in (*refs, 'scores', 'drops')},
               samples=dict(called=0, scored=0, skipped_incomplete=0, fast_shown=0, signs_shown=0,
                            rule_label_match=0, rule_context_match=0, pending_e7=0),
               max_abs_diff=0.0)
    got = {name: [] for name in refs}
    got_scores, got_drops = [], []
    for row in players.itertuples():
        root = args.old_root if row.cohort == 'old' else args.new_root
        h = headers[headers.cohort.eq(row.cohort) & headers.player_id.eq(row.player_id)]
        player = h.player.unique()
        if len(player) != 1:
            raise ValueError('Ambiguous player name')
        games = live.headers(root, player[0])
        joined = games.merge(h, on=['raw_game_id', 'color'], suffixes=('', '_s3'), validate='one_to_one')
        if len(joined) != len(games) or len(joined) != len(h):
            raise ValueError('Live header row set differs from split_v3.load_headers')
        for c in HEADER_COMPARED:
            a, b = joined[c], joined[c + '_s3']
            if not a.isna().equals(b.isna()) or not a[b.notna()].eq(b[b.notna()]).all():
                raise ValueError(f'Live header differs in {c}')
        out['header_rows'] += len(games)
        keymap = h[['raw_game_id', 'color', 'game_id', 'player_id', 'cohort']]
        tg = manifest[manifest.cohort.eq(row.cohort) & manifest.player_id.eq(row.player_id) &
                      manifest.part.isin(split.PARTS)]
        tg = tg.merge(keymap[['raw_game_id', 'color', 'game_id']], on=['game_id', 'color'], validate='one_to_one')
        targets = games.merge(tg[['raw_game_id', 'color']], on=['raw_game_id', 'color'], validate='one_to_one')
        if len(targets) != len(tg):
            raise ValueError('Target rows missing from live headers')
        out['targets'] += len(targets)
        moves = live.player_moves(root, games)
        parts = tg[KEYS + ['part']]
        pre, p20 = prefix.build_player(games, moves, targets, 'features', ())
        labels = prefix.build_player(games, moves, targets, 'labels', ())
        for name, frame in (('labels_dev.parquet', labels), ('features_pre.parquet', pre),
                            ('features_p20.parquet', p20)):
            got[name].append(to_s3(frame, keymap, parts))
        plies = pre[['game_id', 'color']].merge(games[['raw_game_id', 'color', 'plies']], left_on=['game_id', 'color'],
                                                 right_on=['raw_game_id', 'color'], validate='one_to_one').plies
        s = live.scores(model, pre, p20, plies.to_numpy())
        sc = pre[prefix.IDS + ['part']].copy()
        for head in ('pre', 'p20', 'composite'):
            sc[f'M-v3::{head}::frozen'] = s[head]
        got_scores.append(to_s3(sc, keymap, parts))
        kept = set(zip(pre.game_id, pre.color))
        dropped = targets[[(g, c) not in kept for g, c in zip(targets.raw_game_id, targets.color)]]
        got_drops.append(to_s3(dropped.assign(game_id=dropped.raw_game_id)[prefix.IDS + ['part']],
                               keymap, parts)[KEYS])
        # Per-game worker path on a fixed sample: first short, first P-20, last target.
        sample = [targets[targets.plies.lt(20)].head(1), targets[targets.plies.ge(20)].head(1), targets.tail(1)]
        sample = pd.concat(sample).drop_duplicates(['raw_game_id', 'color'])
        dropped_keys = set(zip(dropped.raw_game_id, dropped.color))
        if len(dropped):
            sample = pd.concat([sample, dropped.head(1)]).drop_duplicates(['raw_game_id', 'color'])
        lab = to_s3(labels, keymap, parts)
        sc3 = got_scores[-1]
        for t in sample.itertuples():
            out['samples']['called'] += 1
            response, prob = live.evaluate(model, root, player[0], t.raw_game_id)
            key = keymap[keymap.raw_game_id.eq(t.raw_game_id) & keymap.color.eq(t.color)].game_id.iloc[0]
            if (t.raw_game_id, t.color) in dropped_keys:
                if response != dict(skip='incomplete'):
                    raise ValueError('Incomplete target was not skipped')
                out['samples']['skipped_incomplete'] += 1
                continue
            expected = sc3[sc3.game_id.eq(key) & sc3.color.eq(t.color)]['M-v3::composite::frozen'].iloc[0]
            if prob != expected:
                raise ValueError('Per-game composite differs from batch')
            pred = response['pred']
            if pred['head'] != ('p20' if t.plies >= 20 else 'pre') or pred['level'] != live.level(prob):
                raise ValueError('Head or level mismatch')
            ref_label = lab[lab.game_id.eq(key) & lab.color.eq(t.color)].iloc[0]
            out['samples']['scored'] += 1
            out['samples']['rule_label_match'] += int(pred['rules']['label'] == ref_label.label)
            out['samples']['rule_context_match'] += int(pred['rules']['context'] == ref_label.level)
            out['samples']['pending_e7'] += int('E7' in pred['rules']['pending'])
            out['samples']['fast_shown'] += int('fast' in pred)
            out['samples']['signs_shown'] += len(pred['signs'])
    for name, frames in got.items():
        out['rows'][name] = same(pd.concat(frames, ignore_index=True), refs[name], name)
    pred_ref = predictions.merge(pd.concat(got_scores)[KEYS], on=KEYS, validate='one_to_one')
    if len(pred_ref) != sum(map(len, got_scores)):
        raise ValueError('Scored rows missing from S4 predictions')
    out['rows']['scores'] = same(pd.concat(got_scores, ignore_index=True)[KEYS + SCORES],
                                 pred_ref[KEYS + SCORES], 'scores')
    exp_drops = drops.merge(wanted, on=['cohort', 'player_id'])[KEYS]
    out['rows']['drops'] = same(pd.concat(got_drops, ignore_index=True), exp_drops, 'drops') if len(exp_drops) else 0
    if out['samples']['rule_label_match'] != out['samples']['scored'] or \
            out['samples']['rule_context_match'] != out['samples']['scored']:
        raise ValueError('Per-game rule check differs from labels_dev')
    out.update(passed=True, seconds=round(time.monotonic() - start, 1),
               code_sha256={Path(m.__file__).name: live.sha256_file(m.__file__) for m in (live, prefix, split)},
               parity_module_sha256=live.sha256_file(__file__), bundle_sha256=live.BUNDLE_SHA)
    return out


def one_colour(root):
    """Count-only: P3-B-root games >= 20 plies whose first 20 plies hold one colour."""
    root = Path(root)
    raw = split.raw_games(root)[['game_id', 'plies']]
    moves = pd.read_parquet(root / 'features/moves.parquet', columns=['game_id', 'ply', 'color'])
    m = moves[moves.ply.between(1, 20)].groupby('game_id').agg(n=('ply', 'nunique'), colours=('color', 'nunique'))
    rows = raw[raw.plies.ge(20)].merge(m, left_on='game_id', right_index=True, how='left')
    return dict(games_ge20=len(rows), one_colour=int((rows.colours.eq(1)).sum()),
                no_moves=int(rows.n.isna().sum()), complete=int((rows.n.eq(20) & rows.colours.eq(2)).sum()))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('old-root', 'new-root', 's2', 's3', 's4', 'bundle', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--per-cohort', type=int, default=12)
    parser.add_argument('--with-drops', type=int, default=2)
    parser.add_argument('--live-root', type=Path, help='worker P3-B data root/processed for the one-colour count')
    args = parser.parse_args(argv)
    if args.out.exists():
        raise FileExistsError('Parity output exists')
    result = run(args)
    if args.live_root:
        result['live_one_colour'] = one_colour(args.live_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(dict(passed=result['passed'], players=result['players'], targets=result['targets'],
                          rows=result['rows'], samples=result['samples'], seconds=result['seconds']), sort_keys=True))


if __name__ == '__main__':
    main()
