"""S5 one-shot evaluation. Frozen computations; append-only locks; no fitting.

Only the operator runs the holdout phases. --players is development-only and
selects at most five old players, whose full histories contain no holdout side.
All published tables have canonical key order, independent of worker count.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import hmac
import json
import multiprocessing
from pathlib import Path
from types import SimpleNamespace

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score
from threadpoolctl import threadpool_limits

from ..data import cohort_v3
from ..features import prefix_v3 as prefix
from ..labels import rules_v3 as rules, split_v3 as split
from . import v3_p3b as whole
from ..training import v3_train as train

KEYS = split.KEYS
PARTS = ('A_prime', 'B_prime')
TARGET_COUNTS = dict(A_prime=9658, B_prime=4989)
DROP_COUNTS = dict(A_prime=7, B_prime=0)
CURRENT_SHA = '7ec4570b50b374c95280d4d15159007b1ebc238a5ec6ffaf2d51f2e8fa241f47'
PRE_E8_SHA = '2225bed059dc14728023414a4da01c5cf29b29737d7dda8f19f3e07e1e08d49b'
S4_RECORDS = {
    'bundles.sha256': 'bb4f051c615d8f945eb6fedb02013ad4a24fbe1b3fedc8fd98db335b2c84d423',
    'code_hash.txt': '75e917d30e49b907a89ac4e19d1933a1a54301095713b0815be679beffd80029',
    'training_provenance.json': '8619be63b7b4859a6290d0f9e6c3ed170767c97d3a6180916d1b4992be59fc0b',
    'features_p3b_whole.parquet': '578ad8250176af18ae11d1de12a1da1bd50aa4a2259929327dd02d5f83a459d6',
    'predictions.parquet': '3e216168e8d39b41fb1b80796dc9f72b073d95dbaa320c419b78c02d13b632c2',
}
BUILD_FILES = ('labels_holdout.parquet', 'features_pre_holdout.parquet',
               'features_p20_holdout.parquet', 'features_p3b_whole_holdout.parquet',
               'excluded_incomplete_moves_holdout.csv')
METRIC_FILES = ('metrics_holdout.json', 'bootstrap_holdout.json', 'length_auc_holdout.json')
RUN_FILES = ('verify.json', 'equivalence.json', *BUILD_FILES, 'predictions_holdout.parquet', *METRIC_FILES)
DESELECT = 'tests/unit/test_v3_p3b.py::test_frozen_s3_files_and_real_document_are_unchanged'
write_json = whole.write_json


def require(ok, message):
    if not ok:
        raise ValueError('S5 section 8 stop: ' + message)


def read_json(path):
    return json.loads(Path(path).read_text())


def records(path):
    return {name: sha for sha, name in (line.split() for line in Path(path).read_text().splitlines())}


def verify_locks(args):
    current = args.prereg.read_bytes()
    s4, s3 = args.s4_snapshot.read_bytes(), args.s3_snapshot.read_bytes()
    for data, lock, expected in ((current, args.lock, CURRENT_SHA),
                               (s4, args.s4_snapshot_lock, whole.CURRENT_SHA),
                               (s3, args.s3_snapshot_lock, split.PREREG_SHA)):
        require(hashlib.sha256(data).hexdigest() == expected == lock.read_text().split()[0],
                'pre-registration or snapshot hash mismatch')
    require(current.startswith(s4) and s4.startswith(s3), 'pre-registration is not append-only')


def verify_inputs(args):
    """Read bytes/hashes and metadata only; no holdout row values or statistics."""
    verify_locks(args)
    old = SimpleNamespace(**vars(args))
    old.prereg, old.lock = args.s4_snapshot, args.s4_snapshot_lock
    old.snapshot, old.snapshot_lock = args.s3_snapshot, args.s3_snapshot_lock
    whole.verify_inputs(old)
    for name, expected in S4_RECORDS.items():
        require(split.sha(args.s4 / name) == expected, 'S4 input hash mismatch: ' + name)
    require(whole.code_hashes() == records(args.s4 / 'code_hash.txt'), 'frozen code hash mismatch')
    require(split.sha(args.s2 / 'excluded_sides.csv') ==
            '0ce5efcd753c9831b6bf540dcedaa2b1387e3cc698e980883bed34c4b8e35dea', 'excluded sides hash')
    provenance = read_json(args.s4 / 'training_provenance.json')
    require(provenance['prereg_sha256'] == whole.CURRENT_SHA, 'S4 provenance lock')
    require(records(args.s4 / 'bundles.sha256') == {
        'bundles/' + p.name: split.sha(p) for p in sorted(args.bundles.glob('*.joblib'))}, 'bundle hashes or inventory')
    whole.load_deployed(args.deployment_pointer, args.deployed_bundle)
    inputs = {'prereg': split.sha(args.prereg), 'S5 code': split.sha(__file__),
              'deployed pointer': split.sha(args.deployment_pointer), 'deployed bundle': split.sha(args.deployed_bundle)}
    for name, root, names in (
        ('S1', args.s1, ('design_hash.txt',)),
        ('S2', args.s2, ('holdout_manifest.parquet', 'excluded_sides.csv', 'assignment_metadata.json', 'cohort.csv')),
        ('S3', args.s3, (*whole.INPUTS, 'feature_registry.csv', 'dev_split_manifest.sha256',
                        'features_content_old.sha256', 'features_content_new.sha256')),
        ('S4', args.s4, tuple(S4_RECORDS))):
        inputs.update({name + '/' + n: split.sha(root / n) for n in names})
    inputs.update({'bundle/' + p.name: split.sha(p) for p in sorted(args.bundles.glob('*.joblib'))})
    return dict(passed=True, prereg_sha256=CURRENT_SHA, inputs=inputs,
                frozen_code=whole.code_hashes(), artifacts={},
                s5_module_sha256=dict(before=PRE_E8_SHA, after=split.sha(__file__)))


def destination(args):
    out = args.out.resolve()
    protected = [args.old_root, args.new_root, args.s1, args.s2, args.s3, args.s4,
                 args.bundles, args.deployed_bundle.parent, Path(__file__).resolve().parents[3]]
    require(not any(out.is_relative_to(p.resolve()) for p in protected), 'output inside protected inputs/code')


def fresh(out, names):
    if any((out / n).exists() for n in names):
        raise FileExistsError('S5 output exists; preserve it and use fresh directories')


def witness(args, prerequisite=None):
    now = verify_inputs(args)
    saved = read_json(args.out / 'verify.json')
    require({k: v for k, v in saved.items() if k not in ('artifacts', 'build_audit')} == {k: v for k, v in now.items() if k != 'artifacts'},
            'inputs changed since verify')
    for name, expected in saved['artifacts'].items():
        require(split.sha(args.out / name) == expected, 'phase artifact changed: ' + name)
    if prerequisite:
        require(prerequisite in saved['artifacts'], 'missing prerequisite phase: ' + prerequisite)
    return saved


def seal(args, names, audit=None):
    value = read_json(args.out / 'verify.json')
    value['artifacts'].update({n: split.sha(args.out / n) for n in names})
    if audit is not None:
        value['build_audit'] = audit
    write_json(args.out / 'verify.json', value)


def canonical(frame):
    return frame.sort_values(KEYS).reset_index(drop=True)


def exact(actual, expected):
    require(set(actual.columns) == set(expected.columns), 'equivalence column inventory differs')
    a, b = canonical(actual)[expected.columns], canonical(expected)
    require(len(a) == len(b) and not a.duplicated(KEYS).any() and not b.duplicated(KEYS).any(),
            'equivalence row inventory differs')
    differences = {}
    for c in b:
        require(a[c].isna().equals(b[c].isna()), 'equivalence null mismatch: ' + c)
        good = b[c].notna()
        require(a.loc[good, c].eq(b.loc[good, c]).all(), 'equivalence value mismatch: ' + c)
        differences[c] = 0.0
    return dict(rows=len(a), max_abs_diff=0.0, compared_columns=list(b), columns=differences)


def prediction_scope(columns):
    """Exhaustive E7.1 inventory; unknown heads/kinds/metadata are stops."""
    compared = KEYS + ['part', 'label', 'plies', 'result_score']
    excluded = []
    for candidate in train.FITTED:
        for head in (('whole', 'composite') if candidate == 'P3-B/v3' else ('pre', 'p20', 'composite')):
            compared += [f'{candidate}::{head}::{kind}' for kind in ('raw', 'frozen')]
            excluded.append(f'{candidate}::{head}::calibrated')
    compared += [f'{c}::composite::calibrated' for c in train.UNFITTED]
    require(set(columns) == set(compared + excluded) and len(columns) == len(compared + excluded),
            'prediction column neither compared nor excluded, or a required column missing')
    return compared, excluded


def adapt(frame):
    """Plain-target transport only. Restore real part outside frozen functions."""
    result = frame.copy()
    result['part'] = 'train'
    if 'assignment' in result:
        result['assignment'] = 'development'
    return result


def restore(frame, targets):
    return frame.drop(columns='part').merge(targets[KEYS + ['part']], on=KEYS, validate='one_to_one')


def select_targets(headers, holdout):
    if holdout:
        out = headers[headers.assignment.isin(PARTS)].copy()
        out['part'] = out.assignment
    else:
        out = headers[headers.part.isin(split.PARTS)].copy()
        require(out.assignment.eq('development').all(), 'non-development equivalence target')
    require(not out.empty and not out.duplicated(KEYS).any(), 'empty/duplicate target set')
    return out


def player_tables(games, moves, targets, holdout=False, excluded=()):
    """Every label/feature calculation occurs in the unchanged frozen functions."""
    require(targets.assignment.isin(PARTS if holdout else ['development']).all(), 'wrong phase target assignment')
    g, t = (adapt(x) for x in (games, targets)) if holdout else (games, targets)
    labels = prefix.build_player(g, moves, t, 'labels', excluded)
    audit = {}
    pre, p20 = prefix.build_player(g, moves, t, 'features', excluded, audit)
    drops = pd.DataFrame(audit['exclusions'], columns=prefix.EXCLUSION_COLS)
    if holdout:
        labels, pre, p20 = (restore(x, targets) for x in (labels, pre, p20))
        drops = restore(drops, targets) if len(drops) else drops
    # E3.2 known-end and upper-bound diagnostics, before metrics.
    true, upper = 0, 0
    retained = whole.keyset(pre)
    for row in targets.to_dict('records'):
        if tuple(row[k] for k in KEYS) not in retained:
            continue
        prior = games[games.session_id.eq(row['session_id']) & games.start_ms.lt(row['start_ms'])]
        true += int(prior.end_ms.ge(row['start_ms']).any())
        upper += int(prior.end_upper_ms.ge(row['start_ms']).any())
    return labels, pre, p20, drops, dict(targets=len(pre), true_overlap=true, upper_overlap=upper)


def public(value, namespace=''):
    return hmac.new(cohort_v3.PUBLIC.encode(), (namespace + value).encode(), hashlib.sha256).hexdigest()


RAW_KEYS = ['player', 'game_id', 'color']


def side_set(frame, columns=RAW_KEYS):
    return set(frame[columns].itertuples(index=False, name=None))


def header_plan(args, wanted):
    """Only stored keys and manifest keys/assignments; E2 sides have no stored row."""
    hold = pd.read_parquet(args.s2 / 'holdout_manifest.parquet', columns=KEYS + ['assignment'])
    require(not hold.duplicated(KEYS).any(), 'header plan: duplicate manifest keys')
    plans = {}
    for cohort, subset in wanted.groupby('cohort', sort=True):
        root = args.old_root if cohort == 'old' else args.new_root
        keys = pd.read_parquet(root / 'features/games.parquet', columns=RAW_KEYS, use_threads=False)
        require(not keys.duplicated(RAW_KEYS).any(), 'header plan: duplicate stored keys')
        keys['cohort'] = cohort
        keys['hold_player'] = keys.player.map(public)
        keys['hold_game'] = keys.game_id.map(lambda v: public(v, 'game:'))
        member = hold[hold.cohort.eq(cohort)].rename(columns={'player_id': 'hold_player', 'game_id': 'hold_game'})
        keys = keys.merge(member.drop(columns='cohort'), on=['hold_player', 'hold_game', 'color'],
                          how='left', validate='one_to_one')
        keys['assignment'] = keys.assignment.fillna('development' if cohort == 'old' else 'history_only')
        if cohort == 'new':
            keys = keys[keys.hold_player.isin(subset.player_id)]
        else:
            # S3's split_key is a deterministic player identity key; old export
            # player_id uses a different pseudonym from S2. Never read headers
            # to bridge these identities.
            require('split_key' in subset, 'old key plan requires S3 player split keys')
            keys = keys[keys.player.map(lambda v: split.digest('label-v3-dev-split-1:' + v)).isin(subset.split_key)]
            require(keys.player.nunique() == subset.player_id.nunique(), 'old key-plan player inventory')
        keys = keys.copy()
        values = keys[~keys.assignment.isin(PARTS)].copy()
        boundary = keys[keys.assignment.eq('B_prime')].copy()
        require(not values.assignment.isin(PARTS).any(), 'header plan: holdout in value read')
        require(side_set(boundary) == side_set(keys[keys.assignment.eq('B_prime')]),
                'header plan: boundary differs from own B_prime sides')
        plans[cohort] = (root, keys, values, boundary)
    return plans


def read_sides(root, sides, columns, boundary=False):
    """One processed player at a time; exact colour/game predicates before projection."""
    frames = []
    for player, own in sides.groupby('player', sort=True):
        filters = [[('player', '==', player), ('color', '==', color), ('game_id', 'in', group.game_id.tolist())]
                   for color, group in own.groupby('color', sort=True)]
        frame = pd.read_parquet(root / 'features/games.parquet', columns=columns,
                                filters=filters, use_threads=False)
        require(not frame.duplicated(RAW_KEYS).any(), 'headers: duplicate side keys before merge')
        require(side_set(frame) == side_set(own) and frame.player.eq(player).all(),
                'boundary read: another player or unexpected side' if boundary else 'value read: unexpected side set')
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=columns)


def assert_headers(headers, expected, boundary):
    """The four E8.4 loader assertions, before any header/target merge."""
    require(not headers.duplicated(KEYS).any(), 'headers: duplicate side keys before merge')
    require(not headers.assignment.eq('A_prime').any(), 'headers: A_prime side in equivalence')
    edges = headers[headers.assignment.eq('B_prime')]
    allowed = KEYS + ['player', 'raw_game_id', 'start_ms', 'session_id', 'assignment']
    require(whole.keyset(edges) == whole.keyset(boundary) and
            edges[[c for c in headers if c not in allowed]].isna().all().all(),
            'headers: B_prime is not boundary-only metadata')
    require(whole.keyset(headers[~headers.assignment.isin(PARTS)]) == whole.keyset(expected),
            'headers: non-holdout side set differs from key plan')
    return dict(unique_keys=True, no_A_prime=True, B_prime_boundary_only=True, non_holdout_set_exact=True)


def development_headers(args, wanted):
    frames, expected_frames, boundaries = [], [], []
    cols = list(dict.fromkeys([*RAW_KEYS, *rules.BRIDGE, 'session_id', 'end_ms', 'speed', *prefix.HISTORY]))
    plans = header_plan(args, wanted)
    shared = 0
    for cohort, (root, keys, readable, boundary) in plans.items():
        require(not args.players or not keys.assignment.isin(PARTS).any(), 'smoke player has holdout history')
        games = read_sides(root, readable, cols)
        games = games.merge(readable[RAW_KEYS + ['assignment']], on=RAW_KEYS, validate='one_to_one')
        if cohort == 'old':
            subset = wanted[wanted.cohort.eq(cohort)]
            meta = pd.read_parquet(root / 'out/weak_by_player.parquet', columns=['player_id', 'game_id', *rules.BRIDGE],
                                  filters=[('player_id', 'in', subset.player_id.unique().tolist())])
            require(not meta.duplicated(['player_id', 'game_id', 'color']).any(), 'headers: duplicate old export keys')
            games = meta.rename(columns={'game_id': 'export_id'}).merge(games, on=rules.BRIDGE, validate='one_to_one')
            require(len(games) == len(readable), 'headers: incomplete old export bridge')
        else:
            games['player_id'] = games.player.map(public)
            games['export_id'] = games.game_id.map(lambda v: public(v, 'game:'))
        raw = whole.raw_projection(root, games.game_id.unique().tolist(),
                                   ['status', 'plies', 'rated', 'initial_seconds', 'increment_seconds', 'white_rating', 'black_rating'])
        games = games.merge(raw, on='game_id', validate='many_to_one')
        games = games.rename(columns={'game_id': 'raw_game_id', 'export_id': 'game_id'})
        games['cohort'] = cohort
        expected_frames.append(games[KEYS].copy())
        # Assert against the independent raw-key plan as well as exported keys.
        require(side_set(games.rename(columns={'game_id': 'export_id', 'raw_game_id': 'game_id'})) == side_set(readable),
                'headers: non-holdout side set differs from key plan')
        edges = read_sides(root, boundary, RAW_KEYS + ['start_ms', 'session_id'], boundary=True)
        edges = edges.merge(keys[RAW_KEYS + ['assignment']], on=RAW_KEYS, validate='one_to_one')
        require(edges.assignment.eq('B_prime').all() and set(edges.player) <= set(readable.player),
                'boundary read: assignment is not B_prime or player is not a development player')
        edges['player_id'] = edges.player.map(public)
        edges['raw_game_id'] = edges.game_id
        edges['game_id'] = edges.game_id.map(lambda v: public(v, 'game:'))
        edges['cohort'] = cohort
        edges = edges[KEYS + ['player', 'raw_game_id', 'start_ms', 'session_id', 'assignment']]
        boundaries.append(edges)
        frames.extend([games, edges])
        shared += int(keys.groupby('game_id').size().gt(1).sum())
    headers = pd.concat(frames, ignore_index=True)
    checks = assert_headers(headers, pd.concat(expected_frames), pd.concat(boundaries))
    headers = headers.merge(wanted[KEYS + ['part']], on=KEYS, how='left', validate='one_to_one')
    require(headers.loc[~headers.assignment.isin(PARTS), ['start_ms', 'session_id', 'plies']].notna().all().all(),
            'missing required development headers')
    headers.attrs['audit'] = dict(sides_per_assignment={str(k): int(v) for k, v in headers.assignment.value_counts().items()},
                                 boundary_rows=sum(map(len, boundaries)), shared_games=shared, assertions=checks)
    return headers


def check_header_plan(args):
    """Standalone keys-only CLI phase; writes counts only, never header values."""
    manifest = pd.read_parquet(args.s3 / 'dev_split_manifest.parquet', columns=KEYS + ['part', 'split_key'])
    require(not manifest.duplicated(KEYS).any(), 'header plan: duplicate development manifest keys')
    plans = header_plan(args, manifest[manifest.part.isin(split.PARTS)])
    counts, deviation = {}, 0
    for cohort, (_, keys, values, boundary) in plans.items():
        old_cross = keys[keys.player.isin(values.player) & keys.game_id.isin(values.game_id)]
        deviation += int(old_cross.assignment.eq('B_prime').sum())
        counts[cohort] = dict(development_players=int(keys.player.nunique()), stored_sides=len(keys),
            value_sides=len(values), boundary_sides=len(boundary),
            sides_per_assignment={str(k): int(v) for k, v in keys.assignment.value_counts().items()},
            shared_games=int(keys.groupby('game_id').size().gt(1).sum()))
    return dict(passed=True, cohorts=counts, E8_3_B_prime_sides_in_old_value_read=deviation,
                assertions=dict(unique_keys=True, no_holdout_in_value_read=True, boundary_equals_own_B_prime=True),
                value_columns_read=0)



def build_targets(args, headers, manifest):
    """E8.4 pre-computation guards; prefix presence uses the frozen E4 audit."""
    require(not headers.duplicated(KEYS).any(), 'build: duplicate header keys before computation')
    wanted = select_targets(headers, True)
    expected = manifest[manifest.assignment.isin(PARTS)]
    require(not expected.duplicated(KEYS).any() and whole.keyset(wanted) == whole.keyset(expected),
            'build: target set differs from manifest before computation')
    inventory = []
    for cohort, own in wanted.groupby('cohort', sort=True):
        root = args.old_root if cohort == 'old' else args.new_root
        moves = pd.read_parquet(root / 'features/moves.parquet', columns=['game_id', 'ply', 'color'],
                               filters=[('game_id', 'in', own.raw_game_id.unique().tolist())], use_threads=False)
        inventory.append(prefix.move_inventory(own, moves))
    drops = prefix.incomplete_targets(wanted, pd.concat(inventory, ignore_index=True))
    prefix.check_incomplete_count(drops, DROP_COUNTS)
    retained = wanted.loc[~wanted[KEYS].apply(tuple, axis=1).isin(whole.keyset(drops))]
    require(whole.keyset(retained) == whole.keyset(expected) - whole.keyset(drops),
            'build: retained targets differ from manifest minus incomplete-prefix drops before computation')
    # The frozen path still sees incomplete targets to enforce the E4 own-colour
    # label stop; it drops their feature rows itself, exactly as in S3.
    return wanted

def worker(task):
    root, games, targets, holdout, excluded = task
    readable = games if holdout else games[~games.assignment.isin(PARTS)]
    moves = pd.read_parquet(root / 'features/moves.parquet', columns=prefix.MOVE_COLS,
        filters=[('game_id', 'in', readable.raw_game_id.unique().tolist())], use_threads=False)
    require(not moves.duplicated(['game_id', 'ply']).any(), 'duplicate physical moves')
    labels, pre, p20, drops, audit = player_tables(games, moves, targets, holdout, excluded)
    bridge = pre[KEYS + ['part']].merge(games[KEYS + ['player', 'raw_game_id']], on=KEYS, validate='one_to_one')
    bridge = bridge.rename(columns={'game_id': 'export_id'})
    if holdout:
        table = restore(whole.build_player((root, adapt(bridge))), pre)
    else:
        table = whole.build_player((root, bridge))
    return labels, pre, p20, table, drops, audit


def rebuild(args, headers, wanted, holdout):
    reg = pd.read_csv(args.s3 / 'feature_registry.csv')
    excluded = tuple(c for c in prefix.HISTORY if c not in set(reg.column))
    tasks = []
    for (cohort, player), targets in wanted.groupby(['cohort', 'player_id'], sort=True):
        games = headers[headers.cohort.eq(cohort) & headers.player_id.eq(player)]
        tasks.append((args.old_root if cohort == 'old' else args.new_root, games, targets, holdout, excluded))
    frames = [[] for _ in range(5)]
    audit = dict(targets=0, true_overlap=0, upper_overlap=0)
    def collect(results):
        for result in results:
            for dest, frame in zip(frames, result[:5]):
                dest.append(frame)
            for k in audit:
                audit[k] += result[5][k]
    if args.processes == 1:
        collect(map(worker, tasks))
    else:
        with ProcessPoolExecutor(max_workers=args.processes, mp_context=multiprocessing.get_context('spawn')) as pool:
            # Bounded batches preserve order and limit worker result buffers.
            for start in range(0, len(tasks), args.processes):
                collect(pool.map(worker, tasks[start:start + args.processes]))
    return (*[canonical(pd.concat(f, ignore_index=True)) for f in frames], audit)


def score_tables(labels, pre, p20, whole_table, registry, bundles, deployed):
    """Frozen all-validation inference only. Whole-game values stay separate."""
    meta = canonical(labels.merge(pre[KEYS], on=KEYS, validate='one_to_one'))
    pre, p20, whole_table = (train.ordered(frame, pop) for frame, pop in
                            ((pre, meta), (p20, meta[meta.plies.ge(20)]), (whole_table, meta)))
    # Frozen validation/matrix guards see plain targets, never patched code.
    train.validate_tables(adapt(meta), adapt(pre), adapt(p20), registry, adapt(whole_table))
    combined = adapt(pre).merge(adapt(p20), on=KEYS + ['part'], validate='one_to_one')
    result = meta[KEYS + ['part', 'label', 'plies', 'result_score']].copy()
    with threadpool_limits(limits=2):
        for candidate in train.FITTED:
            heads = ('whole',) if candidate == 'P3-B/v3' else ('pre', 'p20')
            require(set(bundles[candidate]['heads']) == set(heads), 'bundle head inventory')
            for head in heads:
                index = np.flatnonzero(meta.plies.ge(20)) if head == 'p20' else np.arange(len(meta))
                frame = whole_table[list(whole.FEATURES)] if head == 'whole' else train.matrix(
                    combined if head == 'p20' else adapt(pre), head, candidate, registry)
                bundle = bundles[candidate]['heads'][head]
                require(list(frame) == list(bundle['features']), 'frozen matrix column order')
                if len(frame):
                    frozen, _, raw = train.predict_bundle(bundle, frame)
                else:
                    frozen = raw = np.array([], float)
                for kind, values in (('raw', raw), ('frozen', frozen)):
                    vector = np.full(len(meta), np.nan)
                    vector[index] = values
                    result[f'{candidate}::{head}::{kind}'] = vector
            for kind in ('raw', 'frozen'):
                result[f'{candidate}::composite::{kind}'] = result[f'{candidate}::whole::{kind}'] if heads == ('whole',) else train.composite(
                    meta.plies, result[f'{candidate}::pre::{kind}'], result[f'{candidate}::p20::{kind}'])
        result['P3-B frozen::composite::calibrated'] = train.predict_bundle(deployed, whole_table)[0]
        cut = train.matrix(combined, 'p20', 'P3-B@20/v3', registry).rename(
            columns={c: c.removeprefix('p20_') for c in combined if c.startswith('p20_')})
        vector = np.full(len(meta), np.nan)
        if len(cut):
            vector[meta.plies.ge(20)] = train.predict_bundle(deployed, cut)[0]
        result['P3-B@20 frozen::composite::calibrated'] = vector
    for name, values in (('R-pre', prefix.r_pre(pre)), ('B-streak', pre.losing_streak_before),
                         ('B-length', meta.plies), ('B-result', 1 - meta.result_score.fillna(.5))):
        require(np.isfinite(values).all(), 'missing unfitted score')
        result[f'{name}::composite::calibrated'] = np.asarray(values, float)
    return result


def load_scores(args, tables):
    bundles = {c: joblib.load(args.bundles / (c.replace('/', '_').replace('@', 'at') + '.joblib')) for c in train.FITTED}
    for c, bundle in bundles.items():
        require(bundle['candidate'] == c and bundle['prereg_sha256'] == whole.CURRENT_SHA and
                bundle['code_sha256'] == records(args.s4 / 'code_hash.txt'), 'bundle provenance')
    return score_tables(*tables, pd.read_csv(args.s3 / 'feature_registry.csv'), bundles,
                        whole.load_deployed(args.deployment_pointer, args.deployed_bundle))


def premetric(tables, audit, manifest=None):
    labels, pre, p20, whole_table, drops = tables
    prefix.check_incomplete_count(drops, DROP_COUNTS)
    require(pre.groupby('part').size().to_dict() == TARGET_COUNTS, 'holdout target counts')
    require(audit['targets'] == sum(TARGET_COUNTS.values()) and
            audit['true_overlap'] / audit['targets'] <= .005, 'known-end overlap exceeds 0.5%')
    require(set(labels.part) <= set(PARTS) and labels.label.isin(['TILT', 'NOT', 'ABSTAIN']).all(), 'label/part inventory')
    for frame in tables:
        require(not frame.duplicated(KEYS).any(), 'duplicate holdout side')
    require(whole.keyset(labels) == whole.keyset(pre) == whole.keyset(whole_table), 'missing label/pre/whole row')
    require(whole.keyset(p20) == whole.keyset(labels[labels.plies.ge(20)]), 'missing P-20 feature row')
    for frame in (pre, p20, whole_table):
        joined = labels[KEYS + ['part']].merge(frame[KEYS + ['part']], on=KEYS, suffixes=('_a', '_b'), validate='one_to_one')
        require(joined.part_a.eq(joined.part_b).all(), 'part changed across tables')
    require(drops.status.eq(prefix.DROP_INCOMPLETE).all() and drops.color_present.isin(['white', 'black']).all(), 'incomplete pattern')
    if manifest is not None:
        targets = manifest[manifest.assignment.isin(PARTS)]
        require(not (whole.keyset(labels) & whole.keyset(drops)) and
                whole.keyset(labels) | whole.keyset(drops) == whole.keyset(targets), 'holdout manifest universe')
        check = targets[KEYS + ['assignment']].merge(labels[KEYS + ['part']], on=KEYS, validate='one_to_one')
        require(check.assignment.eq(check.part).all(), 'holdout assignment changed')


def metric_columns(predictions):
    return [c for c in predictions if (c.endswith('::frozen') or
            (c.endswith('::calibrated') and c.split('::')[0] in train.UNFITTED))]


def reports(predictions):
    require(predictions.part.isin(PARTS).all() and predictions.label.isin(['TILT', 'NOT', 'ABSTAIN']).all(), 'invalid predictions')
    labelled = predictions[predictions.label.isin(['TILT', 'NOT'])].reset_index(drop=True)
    metrics = dict(parts={}, counts={}, score_kind='frozen all-validation Platt',
                   ece_bins='10 quantile bins; duplicate edges collapse; phase1.calibration_bins unchanged')
    boot, lengths = {}, {}
    for part in (*PARTS, 'pooled'):
        all_rows = predictions if part == 'pooled' else predictions[predictions.part.eq(part)]
        data = labelled if part == 'pooled' else labelled[labelled.part.eq(part)]
        metrics['counts'][part] = dict(rows=len(all_rows), by_label={k: int(all_rows.label.eq(k).sum()) for k in ('TILT', 'NOT', 'ABSTAIN')}, strata={})
        metrics['parts'][part], boot[part], lengths[part] = {}, {}, {}
        for stratum in train.STRATA:
            f = data.loc[train.stratum(data, stratum)]
            total = all_rows.loc[train.stratum(all_rows, stratum)]
            metrics['counts'][part]['strata'][stratum] = dict(rows=len(total), labelled=len(f), tilt=int(f.label.eq('TILT').sum()))
            y = f.label.eq('TILT').to_numpy(float)
            cells, groups, paired = {}, {}, {}
            main = f['M-v3::composite::frozen'].to_numpy(float)
            for col in metric_columns(predictions):
                candidate, head, _ = col.split('::')
                key = candidate + '::' + head
                values = f[col].to_numpy(float)
                valid = np.isfinite(values)
                cells[key] = train.metric(y, values, candidate in train.FITTED)
                group = groups.setdefault(valid.tobytes(), dict(valid=valid, scores={}))
                group['scores'][key] = values[valid]
            # A shared draw stream per available population gives the same
            # clustered CIs as separate calls, while ranking each score once.
            for group in groups.values():
                valid, available = group['valid'], group['scores']
                yy = y[valid]
                keys = list(available)
                main_key = 'M-v3::composite'
                pairs = [(main_key, key) for key in keys if key.endswith('::composite') and key != main_key]
                if pairs:
                    available[main_key] = main[valid]
                sub = train.bootstrap(f.loc[valid, 'player_id'].to_numpy(), yy, available, pairs)
                for key in keys:
                    cells[key].update(pr_auc_ci95=sub['ci'][key], bootstrap_skipped=sub['skipped'])
                for _, key in pairs:
                    candidate = key.split('::')[0]
                    values = available[key]
                    point = float(average_precision_score(yy, main[valid]) - average_precision_score(yy, values)) if len(np.unique(yy)) == 2 else None
                    interval = sub['paired'][f'{main_key}-{key}']
                    paired[candidate] = dict(point_delta=point, ci=interval['ci'] if interval else None,
                        repetitions=1000, skipped=sub['skipped'], no_positive=sub['no_positive'], one_class=sub['one_class'],
                        rows=int(valid.sum()), tilt=int(yy.sum()))
            metrics['parts'][part][stratum] = cells
            boot[part][stratum] = paired
        for candidate in (*train.FITTED, *train.UNFITTED):
            col = f'{candidate}::composite::' + ('frozen' if candidate in train.FITTED else 'calibrated')
            values = data[col].to_numpy(float)
            valid = np.isfinite(values)
            lengths[part][candidate] = {}
            for threshold in (20, 40):
                y = data.plies.to_numpy()[valid] < threshold
                auc = float(roc_auc_score(y, values[valid])) if len(np.unique(y)) == 2 else None
                lengths[part][candidate][f'lt{threshold}'] = dict(n=int(valid.sum()), roc_auc=auc,
                    symmetric_auc=max(auc, 1-auc) if auc is not None else None)
    return metrics, boot, lengths


def adoption(metrics, boot):
    cells, calibration = [], []
    for part in PARTS:
        for stratum in ('ge40', 'lt40'):
            for comparator in train.ADOPTION:
                cell = boot[part][stratum][comparator]
                ci = cell['ci']
                reasons = []
                if cell['tilt'] < 30:
                    reasons.append('fewer than 30 TILT rows')
                if cell['skipped'] > .1 * cell['repetitions']:
                    reasons.append('more than 10% bootstrap draws skipped')
                if ci is None or ci[0] <= 0:
                    reasons.append('CI lower bound is not greater than zero')
                cells.append(dict(part=part, stratum=stratum, comparator=comparator,
                                  **cell, met=not reasons, reasons=reasons))
        ece = metrics['parts'][part]['all']['M-v3::composite']['ece']
        calibration.append(dict(part=part, ece=ece, met=ece is not None and ece <= .05))
    adopted = all(c['met'] for c in cells + calibration)
    return dict(adopted=adopted, verdict='adopted in principle' if adopted else 'not adopted',
                deciding_cells=cells, calibration=calibration,
                failed_cells=[c for c in cells if not c['met']],
                deployment_changed=False, notice='Predicts the v3 rule early; does not measure emotion.')


def run_phase(args):
    destination(args)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.phase == 'verify':
        fresh(args.out, RUN_FILES)
        write_json(args.out / 'verify.json', verify_inputs(args))
        return
    prerequisites = {'equivalence': None, 'build': 'equivalence.json',
                     'score': BUILD_FILES[-1], 'evaluate': 'predictions_holdout.parquet'}
    saved = witness(args, prerequisites[args.phase])
    if args.phase == 'equivalence':
        fresh(args.out, ['equivalence.json'])
        manifest = pd.read_parquet(args.s3 / 'dev_split_manifest.parquet')
        wanted = manifest[manifest.part.isin(split.PARTS)].copy()
        if args.players:
            players = sorted(wanted.loc[wanted.cohort.eq('old'), 'player_id'].unique())[:args.players]
            wanted = wanted[wanted.cohort.eq('old') & wanted.player_id.isin(players)]
        headers = development_headers(args, wanted)
        wanted = select_targets(headers, False)
        labels, pre, p20, table, drops, audit = rebuild(args, headers, wanted, False)
        players = wanted[['cohort', 'player_id']].drop_duplicates()
        checks = {}
        for name, actual, root in (('labels_dev.parquet', labels, args.s3), ('features_pre.parquet', pre, args.s3),
                ('features_p20.parquet', p20, args.s3), ('features_p3b_whole.parquet', table, args.s4)):
            reference = pd.read_parquet(root / name).merge(players, on=['cohort', 'player_id'], validate='many_to_one')
            checks[name] = exact(actual, reference)
        exp_drops = pd.read_csv(args.s3 / 'excluded_incomplete_moves.csv').merge(players, on=['cohort', 'player_id'], validate='many_to_one')
        checks['excluded_incomplete_moves.csv'] = exact(drops, exp_drops)
        predictions = load_scores(args, (labels, pre, p20, table))
        # Inspect schema, then project ONLY compared columns: excluded values never loaded.
        import pyarrow.parquet as pq
        compared, excluded = prediction_scope(pq.ParquetFile(args.s4 / 'predictions.parquet').schema.names)
        reference = pd.read_parquet(args.s4 / 'predictions.parquet', columns=compared).merge(players, on=['cohort', 'player_id'], validate='many_to_one')
        checks['predictions.parquet'] = exact(predictions, reference)
        result = dict(passed=True, complete=not bool(args.players), players=len(players),
            rows=len(pre), label_rows=len(labels), max_abs_diff=0.0, tables=checks,
            compared_columns=compared, excluded_columns=excluded, headers=headers.attrs['audit'])
        witness(args)
        write_json(args.out / 'equivalence.json', result)
        seal(args, ['equivalence.json'])
        return
    equivalence = read_json(args.out / 'equivalence.json')
    require(equivalence['passed'] and equivalence['complete'], 'full equivalence required before holdout phases')
    if args.phase == 'build':
        fresh(args.out, BUILD_FILES)
        headers = split.load_headers(args.old_root, args.new_root, args.s2)
        manifest = pd.read_parquet(args.s2 / 'holdout_manifest.parquet', columns=KEYS + ['assignment'])
        wanted = build_targets(args, headers, manifest)
        labels, pre, p20, table, drops, audit = rebuild(args, headers, wanted, True)
        labels = labels.merge(pre[KEYS], on=KEYS, validate='one_to_one')
        tables = (labels, pre, p20, table, drops)
        premetric(tables, audit, pd.read_parquet(args.s2 / 'holdout_manifest.parquet', columns=KEYS + ['assignment']))
        witness(args, 'equivalence.json')
        for name, frame in zip(BUILD_FILES, tables):
            if name.endswith('.csv'):
                frame.to_csv(args.out / name, index=False)
            else:
                frame.to_parquet(args.out / name, index=False)
        seal(args, BUILD_FILES, audit)
        return
    tables = tuple(pd.read_csv(args.out / n) if n.endswith('.csv') else pd.read_parquet(args.out / n) for n in BUILD_FILES)
    premetric(tables, saved['build_audit'], pd.read_parquet(args.s2 / 'holdout_manifest.parquet', columns=KEYS + ['assignment']))
    if args.phase == 'score':
        fresh(args.out, ['predictions_holdout.parquet'])
        predictions = load_scores(args, tables[:4])
        witness(args, BUILD_FILES[-1])
        predictions.to_parquet(args.out / 'predictions_holdout.parquet', index=False)
        seal(args, ['predictions_holdout.parquet'])
    elif args.phase == 'evaluate':
        fresh(args.out, METRIC_FILES)
        predictions = pd.read_parquet(args.out / 'predictions_holdout.parquet')
        exact(predictions[KEYS + ['part', 'label', 'plies', 'result_score']],
              canonical(tables[0])[KEYS + ['part', 'label', 'plies', 'result_score']])
        # All section 8 premetric checks precede the first computed metric.
        require(set(predictions.columns) == set(prediction_scope([
            *predictions.columns, *[f'{c}::{h}::calibrated' for c in train.FITTED
                for h in (('whole', 'composite') if c == 'P3-B/v3' else ('pre', 'p20', 'composite'))]])[0]), 'prediction inventory')
        for col in metric_columns(predictions):
            eligible = predictions.plies.ge(20) if '::p20::' in col or col.startswith('P3-B@20 frozen::') else np.ones(len(predictions), bool)
            require(np.isfinite(predictions.loc[eligible, col]).all(), 'missing required holdout score')
        outputs = reports(predictions)
        outputs[0]['incomplete_prefix_drops'] = {part: int(tables[4].part.eq(part).sum()) for part in PARTS}
        witness(args, 'predictions_holdout.parquet')
        for name, value in zip(METRIC_FILES, outputs):
            write_json(args.out / name, value)
        seal(args, METRIC_FILES)


def compare(run1, run2, determinism, decision):
    fresh(determinism.parent, [determinism.name])
    fresh(decision.parent, [decision.name])
    files = {}
    for run in (run1, run2):
        require({p.name for p in run.iterdir()} == set(RUN_FILES), 'run output inventory differs')
        saved = read_json(run / 'verify.json')
        require(set(saved['artifacts']) == set(RUN_FILES) - {'verify.json'}, 'incomplete phase evidence')
        for name, expected in saved['artifacts'].items():
            require(split.sha(run / name) == expected, 'changed run artifact')
        eq = read_json(run / 'equivalence.json')
        require(eq['passed'] and eq['complete'], 'full equivalence missing')
    for name in RUN_FILES:
        a, b = split.sha(run1 / name), split.sha(run2 / name)
        files[name] = dict(run1=a, run2=b, identical=a == b)
    passed = all(v['identical'] for v in files.values())
    write_json(determinism, dict(passed=passed, files=files))
    require(passed, 'two runs differ; adoption withheld')
    first = adoption(read_json(run1 / METRIC_FILES[0]), read_json(run1 / METRIC_FILES[1]))
    second = adoption(read_json(run2 / METRIC_FILES[0]), read_json(run2 / METRIC_FILES[1]))
    require(first == second, 'two decisions differ')
    write_json(decision, first)
    return first


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['verify', 'equivalence', 'build', 'score', 'evaluate', 'compare', 'header-plan'])
    for name in ('old-root', 'new-root', 's1', 's2', 's3', 's4', 'prereg', 'lock', 's3-snapshot',
                 's3-snapshot-lock', 's4-snapshot', 's4-snapshot-lock', 'bundles',
                 'deployment-pointer', 'deployed-bundle', 'out'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--players', type=int, default=0)
    parser.add_argument('--processes', type=int, default=1)
    for name in ('run1', 'run2', 'determinism', 'adoption'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args(argv)
    require(args.processes >= 1 and 0 <= args.players <= 5, 'processes/players bounds')
    require(not args.players or args.phase == 'equivalence', '--players is equivalence-only')
    if args.phase == 'header-plan':
        destination(args)
        args.out.mkdir(parents=True, exist_ok=True)
        fresh(args.out, ['header_plan.json'])
        write_json(args.out / 'header_plan.json', check_header_plan(args))
    elif args.phase == 'compare':
        require(all((args.run1, args.run2, args.determinism, args.adoption)), 'compare paths required')
        require(len({args.run1.resolve(), args.run2.resolve(), args.determinism.resolve(), args.adoption.resolve()}) == 4,
                'compare paths must be distinct')
        verify_inputs(args)
        for run in (args.run1, args.run2):
            witness(SimpleNamespace(**{**vars(args), 'out': run}), METRIC_FILES[-1])
        for out in (args.run1, args.run2, args.determinism.parent, args.adoption.parent):
            destination(SimpleNamespace(**{**vars(args), 'out': out}))
        compare(args.run1, args.run2, args.determinism, args.adoption)
        verify_inputs(args)
    else:
        run_phase(args)


if __name__ == '__main__':
    main()
