"""S4 whole-game comparator only. Private keys stay in memory and output tables.

The projection below follows score.run: stored per-game aggregates, normalized
time controls and score.dynamics on own moves. Unlike enrich, it opens SQLite
read-only and filters out holdouts before reading any feature values.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import hmac
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import numpy as np
import pandas as pd

from ..service import deployment, score
from ..features import prefix_v3 as prefix
from ..labels import rules_v3 as rules, split_v3 as split
from . import phase3

CURRENT_SHA = '851858bca40d46ff6ee76a1b62bcab19e89581b03f59e9193e43eca1f072204f'
DEPLOYED_SHA = 'cbd7a3f9d4adfd00f8d3eaffbe87139e8d2992f45aaae1ad2ef1c66940c8613f'
INPUTS = {
    'labels_dev.parquet': '5070069a7a4dedae5cea4c1a92cd0d1cc4548e66ea58f277cb233adadc427af4',
    'features_pre.parquet': '07c542f14d8ec708aab53afed1e2baf019153991f1ef634e664744f5b8edb730',
    'features_p20.parquet': '78691dfd9fe1df9c5a844c4ed33b995f0d0b685afaa6af04fae20012bc2d987f',
    'dev_split_manifest.parquet': 'f0677cb8f63c73d91cf98f6d40bb26a85c58631b8642ae90f3e98b0b6789cccb',
    'excluded_incomplete_moves.csv': 'e3f1bf17e551f7d01c4ba587c67d2464ab01d6aa3c531096b6cddea5387bad1e',
    's3_gate.json': '5169cb67cc8074a6ca80c6da24c22229be0d712b845eaa5e983d47fb06e9f375',
}
FROZEN = {
    'labels/split_v3.py': 'f426e79254167d3f998f1b075f720b3b89098d52b37930f4bf975bd3fb6fa4ff',
    'features/prefix_v3.py': '92c6d27777142b862f70d4c042da4d6618f935a59991827d96b1662758060f42',
    'labels/rules_v3.py': '86fcd9c1eb10d67f3e90735ecdb772fda336ffa191c3683f1c43b2e3828059f6',
}
KEYS = split.KEYS
FEATURES = tuple(phase3.VARIANTS['P3-B'])
WHOLE_ONLY = frozenset(FEATURES) - {
    'initial_seconds', 'increment_seconds', 'rematch_streak_before', 'baseline_risk_rate_games'}


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def verify_locks(args):
    current, snapshot = Path(args.prereg).read_bytes(), Path(args.snapshot).read_bytes()
    if (hashlib.sha256(current).hexdigest() != CURRENT_SHA or
            Path(args.lock).read_text().split()[0] != CURRENT_SHA):
        raise ValueError('Current pre-registration lock mismatch')
    if (hashlib.sha256(snapshot).hexdigest() != split.PREREG_SHA or
            Path(args.snapshot_lock).read_text().split()[0] != split.PREREG_SHA):
        raise ValueError('S3 snapshot lock mismatch')
    if not current.startswith(snapshot):
        raise ValueError('Pre-registration is not append-only')


def code_hashes():
    base = Path(__file__).resolve().parents[1]
    names = [*FROZEN, 'evaluation/v3_p3b.py', 'training/v3_train.py',
             'evaluation/phase5.py', 'evaluation/phase1.py', 'evaluation/phase3.py',
             'training/train.py', 'service/score.py', 'service/deployment.py',
             'features/behavior.py', 'features/model_features.py', 'data/cohort_v3.py']
    result = {name: split.sha(base / name) for name in sorted(names)}
    project = base.parents[1]
    for name in ('test_v3_p3b.py', 'test_v3_train.py', 'test_prefix_v3.py', 'test_split_v3.py'):
        result['tests/unit/' + name] = split.sha(project / 'tests/unit' / name)
    return dict(sorted(result.items()))


def verify_inputs(args):
    verify_locks(args)
    for name, expected in INPUTS.items():
        if split.sha(Path(args.s3) / name) != expected:
            raise ValueError('Frozen S3 input mismatch: ' + name)
    for name, expected in FROZEN.items():
        if code_hashes()[name] != expected:
            raise ValueError('Frozen S3 code mismatch: ' + name)
    # Frozen code receives its own era's document, never the S4 lock.
    old_args = SimpleNamespace(**vars(args))
    old_args.prereg, old_args.lock = args.snapshot, args.snapshot_lock
    prefix.verify_sources(old_args)
    gate = json.loads((Path(args.s3) / 's3_gate.json').read_text())
    if not gate['passed'] or not all(gate['checks'].values()):
        raise ValueError('S3 gate failed')


def verify_destination(path, args):
    resolved = Path(path).resolve()
    protected = [args.s1, args.s2, args.s3, args.old_root, args.new_root,
                 Path(__file__).resolve().parents[3]]
    if any(resolved.is_relative_to(Path(root).resolve()) for root in protected):
        raise ValueError('Output must be outside code and read-only input roots')


def refuse(frame):
    prefix.targets_only(frame)
    for col in ('assignment', 'status'):
        if col in frame and frame[col].astype(str).str.startswith(('A_prime', 'B_prime', 'drop_', 'history_only')).any():
            raise ValueError('Forbidden holdout or dropped target')


def keyset(frame):
    return set(map(tuple, frame[KEYS].to_numpy()))


def targets(s3):
    manifest = pd.read_parquet(Path(s3) / 'dev_split_manifest.parquet')
    wanted = manifest[manifest.part.isin(split.PARTS)].copy()
    excluded = pd.read_csv(Path(s3) / 'excluded_incomplete_moves.csv')
    wanted = wanted.loc[~wanted[KEYS].apply(tuple, axis=1).isin(keyset(excluded))]
    refuse(wanted)
    return wanted.sort_values(KEYS).reset_index(drop=True)


def raw_projection(root, physical, columns):
    """Read committed shards without storage.read's database writes or holdout rows."""
    root = Path(root).resolve()
    with sqlite3.connect(f'file:{root}/index.sqlite?mode=ro', uri=True) as db:
        batches = {r[0] for r in db.execute('SELECT batch FROM batches')}
    files = [p for p in sorted((root / 'normalized/games').glob('*.parquet')) if p.stem in batches]
    if not files:
        raise ValueError('Missing committed normalized games')
    return pd.read_parquet(files, columns=['game_id', *columns],
                           filters=[('game_id', 'in', list(physical))], use_threads=False)


def target_bridge(root, cohort, wanted, s2):
    """Discover raw keys using membership metadata only, then project target values."""
    refuse(wanted)
    root = Path(root)
    if cohort == 'old':
        meta = pd.read_parquet(root / 'out/weak_by_player.parquet',
            columns=['player_id', 'game_id', *rules.BRIDGE],
            filters=[('player_id', 'in', wanted.player_id.unique().tolist())])
        meta = wanted[KEYS + ['part']].merge(meta, on=['player_id', 'game_id', 'color'], validate='one_to_one')
        cols = list(dict.fromkeys(['player', 'game_id', *rules.BRIDGE]))
        raw = pd.read_parquet(root / 'features/games.parquet', columns=cols,
            filters=[('start_ms', 'in', meta.start_ms.unique().tolist())], use_threads=False)
        bridge = meta.rename(columns={'game_id': 'export_id'}).merge(
            raw.rename(columns={'game_id': 'raw_game_id'}), on=rules.BRIDGE, validate='one_to_one')
    else:
        spec = json.loads((Path(s2) / 'assignment_metadata.json').read_text())
        if spec['pseudonym'] != 'HMAC-SHA256 keyed by public assignment string':
            raise ValueError('Portable bridge requires the recorded public S2 scheme')
        from ..data.cohort_v3 import PUBLIC
        def public(value, namespace=''):
            return hmac.new(PUBLIC.encode(), (namespace + value).encode(), hashlib.sha256).hexdigest()
        # Only keys are scanned. No holdout header or feature value is read.
        keys = pd.read_parquet(root / 'features/games.parquet', columns=['player', 'game_id', 'color'])
        keys['player_id'] = keys.player.map(public)
        keys['export_id'] = keys.game_id.map(lambda v: public(v, 'game:'))
        bridge = wanted[KEYS + ['part']].rename(columns={'game_id': 'export_id'}).merge(
            keys.rename(columns={'game_id': 'raw_game_id'}), on=['player_id', 'export_id', 'color'], validate='one_to_one')
    if len(bridge) != len(wanted):
        raise ValueError('Incomplete target metadata bridge')
    return bridge[KEYS[:2] + ['export_id', 'color', 'part', 'player', 'raw_game_id']]


def build_player(task):
    root, bridge = task
    wanted = bridge.rename(columns={'export_id': 'game_id'})
    refuse(wanted)
    raw_ids = bridge.raw_game_id.unique().tolist()
    stored = [c for c in FEATURES if c not in (*phase3.B, 'initial_seconds', 'increment_seconds')]
    games = pd.read_parquet(Path(root) / 'features/games.parquet',
        columns=['player', 'game_id', *stored], filters=[('player', '==', bridge.player.iloc[0]),
            ('game_id', 'in', raw_ids)], use_threads=False)
    games = bridge.merge(games.rename(columns={'game_id': 'raw_game_id'}),
                         on=['player', 'raw_game_id'], validate='one_to_one')
    normalized = raw_projection(root, raw_ids, ['initial_seconds', 'increment_seconds'])
    games = games.merge(normalized.rename(columns={'game_id': 'raw_game_id'}),
                        on='raw_game_id', validate='many_to_one')
    own = pd.read_parquet(Path(root) / 'features/moves.parquet',
        columns=['player', 'game_id', 'ply', *score.FLAGS],
        filters=[('player', '==', bridge.player.iloc[0]), ('game_id', 'in', raw_ids)], use_threads=False)
    dynamics = score.dynamics(own)[['game_id', *phase3.B]].rename(columns={'game_id': 'raw_game_id'})
    games = games.merge(dynamics, on='raw_game_id', how='left', validate='one_to_one')
    result = games.rename(columns={'export_id': 'game_id'})[KEYS + ['part', *FEATURES]]
    if len(result) != len(bridge):
        raise ValueError('Whole-game targets missing')
    refuse(result)
    return result


def parity(actual, aligned, behavior):
    refuse(actual)
    old = actual[actual.cohort.eq('old')]
    if old.empty:
        raise ValueError('Parity requires old development targets')
    players = old.player_id.unique().tolist()
    reference = pd.read_parquet(aligned, columns=['player_id', 'game_id', *FEATURES[:8]],
                               filters=[('player_id', 'in', players)])
    extra = pd.read_parquet(behavior, columns=['player_id', 'game_id', *phase3.B],
                           filters=[('player_id', 'in', players)])
    reference = reference.merge(extra, on=['player_id', 'game_id'], validate='one_to_one')
    joined = old.merge(reference, on=['player_id', 'game_id'], suffixes=('_actual', '_phase5'), validate='one_to_one')
    if len(joined) != len(old):
        raise ValueError('Phase 5 parity coverage incomplete')
    differences = {}
    for c in FEATURES:
        a, b = (joined[c + suffix].to_numpy(float) for suffix in ('_actual', '_phase5'))
        ok = np.isclose(a, b, atol=1e-9, rtol=0, equal_nan=True)
        finite = np.isfinite(a) & np.isfinite(b)
        differences[c] = dict(mismatches=int((~ok).sum()),
            max_abs=float(np.max(np.abs(a[finite] - b[finite]))) if finite.any() else 0.)
    return dict(passed=not any(v['mismatches'] for v in differences.values()),
                rows=len(joined), players=len(players), tolerance=1e-9, columns=differences)


def load_deployed(pointer, bundle):
    spec = json.loads(Path(pointer).read_text())
    if spec['bundle_sha256'] != DEPLOYED_SHA or split.sha(bundle) != DEPLOYED_SHA:
        raise ValueError('Frozen deployed bundle hash mismatch')
    import joblib
    result = joblib.load(bundle)
    if spec['variant'] != 'P3-B' or list(result['features']) != list(FEATURES) or spec['features'] != list(FEATURES):
        raise ValueError('Deployed P3-B configuration mismatch')
    result['format'] = 'phase5'
    return result


def run(args):
    verify_inputs(args)
    verify_destination(args.out, args)
    load_deployed(args.deployment_pointer, args.deployed_bundle)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if (out / 'features_p3b_whole.parquet').exists() or (out / 'p3b_parity.json').exists():
        raise FileExistsError('P3-B output already exists')
    wanted = targets(args.s3)
    if args.max_players:
        if args.max_players > 5:
            raise ValueError('Sample limit is five old players')
        players = sorted(wanted.loc[wanted.cohort.eq('old'), 'player_id'].unique())[:args.max_players]
        wanted = wanted[wanted.cohort.eq('old') & wanted.player_id.isin(players)]
    tasks = []
    for cohort, subset in wanted.groupby('cohort', sort=True):
        root = args.old_root if cohort == 'old' else args.new_root
        bridge = target_bridge(root, cohort, subset, args.s2)
        tasks.extend((root, b) for _, b in bridge.groupby('player_id', sort=True))
    if args.processes == 1:
        frames = list(map(build_player, tasks))
    else:
        with ProcessPoolExecutor(max_workers=args.processes) as pool:
            frames = list(pool.map(build_player, tasks))
    table = pd.concat(frames, ignore_index=True).sort_values(KEYS).reset_index(drop=True)
    check = parity(table, args.phase5_aligned, args.phase5_behavior)
    check['sample'] = bool(args.max_players)
    check['code_sha256'] = code_hashes()
    check['prereg_sha256'] = CURRENT_SHA
    if not check['passed']:
        write_json(out / 'p3b_parity.json', check)
        raise ValueError('Phase 5 parity failed; stop under section 8')
    verify_inputs(args)
    table.to_parquet(out / 'features_p3b_whole.parquet', index=False)
    check['table_sha256'] = split.sha(out / 'features_p3b_whole.parquet')
    write_json(out / 'p3b_parity.json', check)
    return check


def common(parser):
    for name in ('prereg', 'lock', 'snapshot', 'snapshot-lock', 's1', 's2', 's3', 'old-root', 'new-root'):
        parser.add_argument('--' + name, required=True, type=Path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    common(parser)
    for name in ('deployment-pointer', 'deployed-bundle', 'phase5-aligned', 'phase5-behavior', 'out'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--processes', type=int, default=1)
    parser.add_argument('--max-players', type=int, default=0)
    args = parser.parse_args(argv)
    if args.processes < 1 or args.max_players < 0:
        parser.error('processes must be positive; max-players nonnegative')
    run(args)
    verify_inputs(args)


if __name__ == '__main__':
    main()
