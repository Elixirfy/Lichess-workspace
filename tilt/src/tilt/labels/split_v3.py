"""Immutable S3 development assignment. All source roots are read-only.

Raw identifiers are confined to memory; published keys are pseudonyms. The old
export is read only through its metadata columns, never its weak labels.
"""
import hashlib
import hmac
import json
import math
from pathlib import Path
import sqlite3

import pandas as pd

from .rules_v3 import BRIDGE
from ..data.cohort_v3 import public_id, PUBLIC

PREREG_SHA = '827890324bdd0e17cef555b770920c972ba10d6bbc9552e830b4f1b7b06c665e'
HOLDOUT_SHA = 'd21e5b02dbaf07c6fee3a7c608973c9f5608f8f62a9aa9cd97120c517a89ff3d'
MANIFEST_SHA = '1ea2383b730329b9f3301263a42aaa788b9ff0ae961df03d921cd1bbc16ec000'
PARTS = ('train', 'V_A', 'V_B')
KEYS = ['cohort', 'player_id', 'game_id', 'color']


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def raw_games(root):
    root = Path(root).resolve()
    with sqlite3.connect(f'file:{root}/index.sqlite?mode=ro', uri=True) as db:
        batches = {r[0] for r in db.execute('SELECT batch FROM batches')}
    files = [p for p in sorted((root / 'normalized/games').glob('*.parquet')) if p.stem in batches]
    if not files:
        raise ValueError('No committed normalized games')
    return pd.read_parquet(files, columns=['game_id', 'status', 'plies', 'rated',
                                          'initial_seconds', 'increment_seconds',
                                          'white_rating', 'black_rating'])


def load_headers(old_root, new_root, s2):
    """Portable cohort discovery, including the old 196 without an aligned-dir dependency."""
    s2 = Path(s2)
    if sha(s2 / 'holdout_manifest.parquet') != HOLDOUT_SHA:
        raise ValueError('Holdout hash mismatch')
    hold = pd.read_parquet(s2 / 'holdout_manifest.parquet')
    metadata = json.loads((s2 / 'assignment_metadata.json').read_text())
    scheme = metadata['pseudonym']
    if sha(s2 / 'excluded_sides.csv') != metadata['excluded_sides_sha256']:
        raise ValueError('Excluded-sides hash mismatch')
    excluded = pd.read_csv(s2 / 'excluded_sides.csv', usecols=['game_id', 'player_id'])
    def hold_id(value, namespace=''):
        if scheme == 'HMAC-SHA256 keyed by public assignment string':
            return hmac.new(PUBLIC.encode(), (namespace + value).encode(), hashlib.sha256).hexdigest()
        if scheme == 'pipeline HMAC from environment':
            return public_id(value, namespace)
        raise ValueError('Unknown S2 pseudonym scheme')
    # S2's recorded pseudonym scheme must be reproduced without opening a salt file.
    old_meta = pd.read_parquet(Path(old_root) / 'out/weak_by_player.parquet',
                              columns=BRIDGE + ['game_id', 'player_id'])
    result = []
    for cohort, root in [('old', old_root), ('new', new_root)]:
        root = Path(root)
        if sha(root / 'features/manifest.json') != MANIFEST_SHA:
            raise ValueError('Features parameter manifest mismatch')
        cols = list(dict.fromkeys(['player', 'game_id', 'color', 'session_id', 'start_ms',
            'end_ms', 'end_upper_ms', 'rating', 'opponent_rating', 'result_score', 'speed',
            'rematch_streak_before', 'losing_streak_before', 'rest_gap_seconds', 'recent_form']))
        g = pd.read_parquet(root / 'features/games.parquet', columns=cols)
        if cohort == 'old':
            bridge = old_meta.rename(columns={'game_id': 'export_id'}).merge(
                g, on=BRIDGE, validate='one_to_one')
            if len(bridge) != len(old_meta) or bridge.player.nunique() != 196:
                raise ValueError('Old cohort metadata bridge is incomplete')
            g = bridge
            if len(g) != int(pd.read_parquet(root / 'features/games.parquet',
                                            columns=['player']).player.isin(g.player).sum()):
                raise ValueError('Old player history is incomplete')
        else:
            users = set(pd.read_csv(s2 / 'cohort.csv').username)
            g = g[g.player.isin(users)].copy()
            g['player_id'] = g.player.map(hold_id)
            g['export_id'] = g.game_id.map(lambda x: hold_id(x, 'game:'))
        g['cohort'] = cohort
        g['physical_id'] = g.game_id.map(lambda x: digest('label-v3-physical:' + x))
        g['split_key'] = g.player.map(lambda x: digest('label-v3-dev-split-1:' + x))
        g['hold_player'] = g.player.map(hold_id)
        g['hold_game'] = g.game_id.map(lambda x: hold_id(x, 'game:'))
        membership = hold[hold.cohort.eq(cohort)].rename(
            columns={'player_id': 'hold_player', 'game_id': 'hold_game'})
        g = g.merge(membership[['hold_player', 'hold_game', 'color', 'assignment']],
                    on=['hold_player', 'hold_game', 'color'], how='left', validate='one_to_one')
        expected = int(hold.cohort.eq(cohort).sum())
        if int(g.assignment.notna().sum()) != expected:
            raise ValueError('S2 pseudonym join mismatch; preserve the assignment environment')
        if cohort == 'old':
            g['assignment'] = g.assignment.fillna('development')
        else:
            # Incidental sides absent from S2 membership are history only.
            g['assignment'] = g.assignment.fillna('history_only')
            target_keys = set(map(tuple, g.loc[g.assignment.eq('development'), ['hold_game', 'hold_player']].to_numpy()))
            if target_keys & set(map(tuple, excluded[['game_id', 'player_id']].to_numpy())):
                raise ValueError('Excluded short side entered target pool')
        raw = raw_games(root).rename(columns={'game_id': 'raw_game_id'})
        g = g.rename(columns={'game_id': 'raw_game_id', 'export_id': 'game_id'})
        g = g.merge(raw, on='raw_game_id', how='left', validate='many_to_one')
        if g[['start_ms', 'session_id', 'plies']].isna().any().any():
            raise ValueError('Incomplete required headers')
        if not g.rating.eq(g.white_rating.where(g.color.eq('white'), g.black_rating)).all():
            raise ValueError('Pre-game rating mismatch')
        result.append(g)
    return pd.concat(result, ignore_index=True)


def assign(pool):
    """S3.1 uses raw game ordering before discarding all raw identifiers."""
    if not pool.assignment.eq('development').all() or pool.duplicated(KEYS).any():
        raise ValueError('Assignment requires unique development sides only')
    out = pool.copy()
    out['part'] = 'train'
    order_game = 'raw_game_id' if 'raw_game_id' in out else 'game_id'
    for _, cohort in out.groupby('cohort', sort=True):
        players = cohort[['player_id', 'split_key']].drop_duplicates().sort_values(['split_key', 'player_id'])
        held = set(players.head((2 * len(players) + 5) // 10).player_id)
        out.loc[cohort.index[cohort.player_id.isin(held)], 'part'] = 'V_A'
        for _, group in cohort[~cohort.player_id.isin(held)].groupby('player_id', sort=True):
            ordered = group.sort_values(['start_ms', order_game])
            anchor = ordered.iloc[math.ceil(.85 * len(ordered)) - 1]
            cutoff = ordered.loc[ordered.session_id.eq(anchor.session_id), 'start_ms'].min()
            out.loc[group.index[group.start_ms.ge(cutoff)], 'part'] = 'V_B'
    validation_games = set(out.loc[out.part.isin(['V_A', 'V_B']), 'physical_id'])
    out.loc[out.part.eq('train') & out.physical_id.isin(validation_games), 'part'] = 'drop_shared_split'
    integrity(out)
    return out


def integrity(frame, expected=None):
    if frame.empty or frame.duplicated(KEYS).any() or frame.part.isna().any():
        raise ValueError('Missing or duplicate assignments')
    if not frame.part.isin([*PARTS, 'drop_shared_split']).all():
        raise ValueError('Unknown split part')
    if 'assignment' in frame and not frame.assignment.eq('development').all():
        raise ValueError('Non-development assignment')
    if expected is not None and set(map(tuple, frame[KEYS].to_numpy())) != set(map(tuple, expected[KEYS].to_numpy())):
        raise ValueError('Development row universe changed')
    va = set(frame.loc[frame.part.eq('V_A'), 'player_id'])
    other = set(frame.loc[frame.part.isin(['train', 'V_B']), 'player_id'])
    if va & other:
        raise ValueError('V_A player contamination')
    tv = frame[frame.part.isin(['train', 'V_B'])]
    if tv.groupby(['cohort', 'player_id', 'session_id']).part.nunique().gt(1).any():
        raise ValueError('Session crosses time cut')
    if set(frame.loc[frame.part.eq('train'), 'physical_id']) & set(frame.loc[frame.part.isin(['V_A', 'V_B']), 'physical_id']):
        raise ValueError('Physical game crosses split')
    return True


def write_once(frame, out, holdout):
    """An exclusive marker refuses regeneration even after an interrupted publication."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / 'dev_split_manifest.parquet'
    if any((out / n).exists() for n in ['dev_split_manifest.parquet', 'dev_split_manifest.sha256', 'split.once']):
        raise FileExistsError('Split already assigned; regeneration forbidden')
    if sha(holdout) != HOLDOUT_SHA:
        raise ValueError('Holdout hash mismatch')
    integrity(frame)
    columns = KEYS + ['physical_id', 'session_id', 'start_ms', 'part', 'split_key']
    saved = frame[columns].copy()
    saved['session_id'] = saved.session_id.map(lambda x: digest('label-v3-session:' + str(x)))
    saved = saved.sort_values(KEYS).reset_index(drop=True)
    with (out / 'split.once').open('x') as stream:
        stream.write('Immutable S3 assignment\n')
    saved.to_parquet(path, index=False, compression='zstd')
    (out / 'dev_split_manifest.sha256').write_text(f'{sha(path)}  {path.name}\n')
    (out / 'split_counts.json').write_text(json.dumps([
        dict(cohort=c, part=p, rows=len(g), players=g.player_id.nunique())
        for (c, p), g in saved.groupby(['cohort', 'part'])], indent=2) + '\n')
    return saved
