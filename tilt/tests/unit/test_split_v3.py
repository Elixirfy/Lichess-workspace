"""S3.1 assignment, immutable publication, and all integrity checks."""
from pathlib import Path
import pandas as pd
import pytest

from tilt.labels import split_v3 as s


def pool(n=10, games=20):
    rows = []
    for cohort in ('old', 'new'):
        for p in range(n):
            for g in range(games):
                rows.append(dict(cohort=cohort, player_id=f'{cohort}-p{p:02}', game_id=f'{cohort}-p{p:02}-g{g:02}',
                    raw_game_id=f'{cohort}-p{p:02}-g{g:02}', physical_id=f'{cohort}-p{p:02}-g{g:02}',
                    color='white', player=f'fixture{p}', session_id=f's{g // 4}', start_ms=g * 1000,
                    split_key=s.digest('label-v3-dev-split-1:' + f'{cohort}{p}'), assignment='development'))
    return pd.DataFrame(rows)


@pytest.mark.parametrize('n', [1, 2, 3, 4, 5, 7, 10, 13])
def test_va_half_up_by_cohort_and_time_session_cut(n):
    frame = pool(n)
    out = s.assign(frame)
    assert s.integrity(out, frame)
    for cohort, g in out.groupby('cohort'):
        expected = frame[frame.cohort.eq(cohort)][['player_id', 'split_key']].drop_duplicates().sort_values('split_key')
        held = set(expected.head((2 * n + 5) // 10).player_id)
        assert set(g[g.part.eq('V_A')].player_id) == held
        for _, p in g[~g.player_id.isin(held)].groupby('player_id'):
            # ceil(.85*20)=17, anchor index 16, session 4 starts at index 16.
            assert p.loc[p.part.eq('V_B'), 'start_ms'].min() == 16000
            assert p.loc[p.part.eq('train'), 'start_ms'].max() == 15000
    assert len(out) == len(frame)


def test_ties_order_by_raw_game_id_and_existing_session():
    frame = pool(3, 7)
    frame.start_ms = 100
    frame.session_id = 'one-existing-session'
    out = s.assign(frame)
    assert not out.part.eq('train').any()
    pd.testing.assert_frame_equal(s.assign(frame.sample(frac=1, random_state=5)).sort_values(s.KEYS).reset_index(drop=True),
                                  out.sort_values(s.KEYS).reset_index(drop=True))


def test_shared_train_side_dropped_validation_sides_kept():
    frame = pool()
    first = s.assign(frame)
    train = first[first.part.eq('train')].index[0]
    valid = first[first.part.eq('V_A')].index[0]
    frame.loc[train, 'physical_id'] = frame.loc[valid, 'physical_id']
    out = s.assign(frame)
    assert out.loc[train, 'part'] == 'drop_shared_split'
    assert out.loc[valid, 'part'] == 'V_A'
    assert s.integrity(out, frame)


@pytest.mark.parametrize('kind', ['duplicate', 'missing', 'universe', 'player', 'session', 'physical', 'holdout', 'unknown'])
def test_integrity_rejects_every_violation(kind):
    frame = pool()
    out = s.assign(frame)
    expected = frame
    if kind == 'duplicate':
        out = pd.concat([out, out.iloc[[0]]])
    elif kind == 'missing':
        out.loc[out.index[0], 'part'] = None
    elif kind == 'universe':
        expected = frame.iloc[1:]
    elif kind == 'player':
        idx = out[out.part.eq('V_A')].index[0]
        out.loc[idx, 'part'] = 'train'
    elif kind == 'session':
        idx = out[out.part.eq('train')].index[0]
        out.loc[idx, 'part'] = 'V_B'
    elif kind == 'physical':
        idx = out[out.part.eq('train')].index[0]
        out.loc[idx, 'physical_id'] = out.loc[out.part.eq('V_A'), 'physical_id'].iloc[0]
    elif kind == 'holdout':
        out.loc[out.index[0], 'assignment'] = 'A_prime'
    else:
        out.loc[out.index[0], 'part'] = 'unknown'
    with pytest.raises(ValueError):
        s.integrity(out, expected)


def test_manifest_write_once_and_holdout_hash(tmp_path, monkeypatch):
    frame = s.assign(pool())
    hold = tmp_path / 'holdout.parquet'
    hold.write_bytes(b'fixture')
    monkeypatch.setattr(s, 'HOLDOUT_SHA', s.sha(hold))
    out = tmp_path / 'out'
    saved = s.write_once(frame, out, hold)
    assert s.integrity(saved, frame)
    assert s.sha(out / 'dev_split_manifest.parquet') == (out / 'dev_split_manifest.sha256').read_text().split()[0]
    assert 'player' not in saved and 'raw_game_id' not in saved
    with pytest.raises(FileExistsError):
        s.write_once(frame, out, hold)
    hold.write_bytes(b'changed')
    with pytest.raises(ValueError, match='Holdout'):
        s.write_once(frame, tmp_path / 'other', hold)


@pytest.mark.parametrize('existing', ['split.once', 'dev_split_manifest.parquet', 'dev_split_manifest.sha256'])
def test_partial_publication_refuses_regeneration(tmp_path, existing):
    (tmp_path / existing).touch()
    with pytest.raises(FileExistsError):
        s.write_once(s.assign(pool()), tmp_path, tmp_path / 'unused')
