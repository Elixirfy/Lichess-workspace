"""S4 comparator provenance, parity, membership and read-only projection."""
import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from tilt.evaluation import v3_p3b as p
from tilt.features import prefix_v3
from tilt.labels import split_v3


def sample(n=3):
    frame = pd.DataFrame(dict(cohort='old', player_id='synthetic-player',
        game_id=[f'synthetic-game-{i}' for i in range(n)], color='white', part='train'))
    for i, c in enumerate(p.FEATURES):
        frame[c] = np.arange(n, dtype=float) + i
    frame.loc[0, p.FEATURES[-1]] = np.nan
    return frame


def reference(tmp_path, frame):
    aligned, behavior = tmp_path / 'aligned.parquet', tmp_path / 'behavior.parquet'
    frame[['player_id', 'game_id', *p.FEATURES[:8]]].to_parquet(aligned, index=False)
    frame[['player_id', 'game_id', *p.phase3.B]].to_parquet(behavior, index=False)
    return aligned, behavior


def test_parity_all_eleven_nulls_and_absolute_tolerance(tmp_path):
    f = sample()
    paths = reference(tmp_path, f)
    assert p.parity(f, *paths)['passed']
    f.loc[1, 'risk_rate'] += 5e-10
    assert p.parity(f, *paths)['passed']
    f.loc[1, 'risk_rate'] += 2e-9
    assert not p.parity(f, *paths)['passed']
    f = sample()
    f.loc[0, p.FEATURES[-1]] = 0.
    assert not p.parity(f, *paths)['passed']


def test_parity_requires_complete_old_coverage(tmp_path):
    f = sample()
    paths = reference(tmp_path, f.iloc[:2])
    with pytest.raises(ValueError, match='coverage'):
        p.parity(f, *paths)


@pytest.mark.parametrize('part', ['A_prime', 'B_prime', 'drop_shared_split',
                                'drop_shared_development', 'drop_incomplete_moves'])
def test_refuse_every_forbidden_part_at_parity_and_worker(tmp_path, part):
    f = sample()
    f['part'] = part
    with pytest.raises(ValueError):
        p.parity(f, tmp_path/'missing', tmp_path/'missing')
    with pytest.raises(ValueError):
        p.build_player((tmp_path, f.rename(columns={'game_id': 'export_id'})))


@pytest.mark.parametrize('assignment', ['A_prime', 'B_prime', 'drop_shared_development',
                                      'drop_shared_split', 'drop_incomplete_moves'])
def test_refuse_disguised_assignment(assignment):
    with pytest.raises(ValueError):
        p.refuse(sample().assign(assignment=assignment))


def test_readonly_builder_matches_scorer_dynamics_and_stored_columns(tmp_path):
    root = tmp_path / 'root'
    (root/'features').mkdir(parents=True)
    (root/'normalized/games').mkdir(parents=True)
    with sqlite3.connect(root/'index.sqlite') as db:
        db.execute('create table batches(batch text primary key)')
        db.execute("insert into batches values ('synthetic')")
    f = sample(2)
    raw = ['raw-synthetic-0', 'raw-synthetic-1']
    bridge = f[p.KEYS+['part']].rename(columns={'game_id': 'export_id'})
    bridge['player'], bridge['raw_game_id'] = 'synthetic-player', raw
    stored = f.drop(columns=['initial_seconds', 'increment_seconds', *p.phase3.B]).copy()
    stored['player'], stored['game_id'] = 'synthetic-player', raw
    stored.to_parquet(root/'features/games.parquet', index=False)
    pd.DataFrame(dict(game_id=raw, initial_seconds=[180., 180.], increment_seconds=[2., 2.])).to_parquet(
        root/'normalized/games/synthetic.parquet', index=False)
    # A synthetic uncommitted shard must never enter the projection.
    pd.DataFrame(dict(game_id=raw, initial_seconds=[999., 999.], increment_seconds=[99., 99.])).to_parquet(
        root/'normalized/games/orphan.parquet', index=False)
    moves = pd.DataFrame([dict(player='synthetic-player', game_id=g, ply=i,
        **{flag: float(i % 3 == j % 3) for j, flag in enumerate(p.score.FLAGS)})
        for g in raw for i in range(1, 20, 2)])
    moves.to_parquet(root/'features/moves.parquet', index=False)
    before = p.split.sha(root/'index.sqlite')
    actual = p.build_player((root, bridge))
    assert actual.initial_seconds.tolist() == [180., 180.]
    dynamics = p.score.dynamics(moves).set_index('game_id')
    for c in p.phase3.B:
        np.testing.assert_equal(actual[c].to_numpy(), dynamics.loc[raw,c].to_numpy())
    assert set(actual) == set(p.KEYS + ['part', *p.FEATURES])
    assert p.split.sha(root/'index.sqlite') == before


def test_current_and_snapshot_append_only_guards(tmp_path, monkeypatch):
    snapshot = b'synthetic prereg\n'
    current = snapshot + b'\nsynthetic S4\n'
    args = SimpleNamespace(prereg=tmp_path/'current', snapshot=tmp_path/'snapshot',
                           lock=tmp_path/'lock', snapshot_lock=tmp_path/'snapshot-lock')
    for path, value in [(args.prereg,current), (args.snapshot,snapshot)]:
        path.write_bytes(value)
    current_sha, snapshot_sha = (hashlib.sha256(v).hexdigest() for v in (current,snapshot))
    args.lock.write_text(current_sha+'  current\n')
    args.snapshot_lock.write_text(snapshot_sha+'  snapshot\n')
    monkeypatch.setattr(p, 'CURRENT_SHA', current_sha)
    monkeypatch.setattr(split_v3, 'PREREG_SHA', snapshot_sha)
    p.verify_locks(args)
    changed = b'x'+current
    args.prereg.write_bytes(changed)
    monkeypatch.setattr(p,'CURRENT_SHA',hashlib.sha256(changed).hexdigest())
    args.lock.write_text(p.CURRENT_SHA+'  current\n')
    with pytest.raises(ValueError, match='append-only'):
        p.verify_locks(args)
    args.snapshot_lock.write_text('wrong  snapshot\n')
    with pytest.raises(ValueError, match='snapshot'):
        p.verify_locks(args)


def test_frozen_s3_files_and_real_document_are_unchanged():
    root = Path(__file__).resolve().parents[2]
    document = (root/'reports/label_v3_preregistration.md').read_bytes()
    assert hashlib.sha256(document).hexdigest() == p.CURRENT_SHA
    snapshot = document.split(b'\n## Addendum S4', 1)[0]
    assert hashlib.sha256(snapshot).hexdigest() == split_v3.PREREG_SHA
    for name, expected in p.FROZEN.items():
        assert p.split.sha(root/'src/tilt'/name) == expected


def test_new_bridge_scans_membership_keys_only(tmp_path, monkeypatch):
    import hmac
    from tilt.data.cohort_v3 import PUBLIC
    def public(v, namespace=''):
        return hmac.new(PUBLIC.encode(), (namespace+v).encode(), hashlib.sha256).hexdigest()
    raw = pd.DataFrame(dict(player=['synthetic-development', 'synthetic-holdout'],
                            game_id=['synthetic-dev-game', 'synthetic-held-game'], color='white'))
    wanted = pd.DataFrame([dict(cohort='new',player_id=public(raw.player[0]),
        game_id=public(raw.game_id[0],'game:'),color='white',part='train')])
    (tmp_path/'assignment_metadata.json').write_text(json.dumps(
        dict(pseudonym='HMAC-SHA256 keyed by public assignment string')))
    def read(path, columns=None, **kw):
        assert columns == ['player','game_id','color']
        return raw.copy()
    monkeypatch.setattr(pd,'read_parquet',read)
    bridge=p.target_bridge(tmp_path,'new',wanted,tmp_path)
    assert bridge.raw_game_id.tolist()==['synthetic-dev-game']


def test_s2_append_only_check_uses_identified_era():
    from tilt.data import cohort_v3
    assert cohort_v3.LOCK == '0d59ce9d79e6e9e9e9992e5116b83e39440eacfc1f3a53b83772030d8b2a0b06'
    cohort_v3.check_lock()
