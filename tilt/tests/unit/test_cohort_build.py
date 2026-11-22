"""Synthetic S2 tests; HTTP is mocked, real data and engines are never used."""
from contextlib import closing
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import pandas as pd
import pytest
import requests
import zstandard
from tilt.data import cohort_build as v, collect, storage


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    def deny(*args, **kwargs):
        raise AssertionError('Unmocked HTTP')
    monkeypatch.setattr(requests.sessions.Session, 'request', deny)
    monkeypatch.setattr(storage, 'DEFAULT_DATA', tmp_path / 'old')


def candidates(rows):
    return pd.DataFrame(rows, columns=v.CANDIDATE_COLUMNS)


def test_band_order_exclusion():
    names = [f'fixture_{i}' for i in range(45)]
    result = v.pick_candidates([(u, 'blitz', 900, 12) for u in names] +
        [('too_low', 'blitz', 399, 99), ('too_high', 'blitz', 3000, 99),
         ('too_few', 'blitz', 900, 11), ('rapid_only', 'rapid', 900, 20)], {'fixture_0'})
    expected = sorted(names[1:], key=lambda u: (v.digest(f'43:{u}:blitz'), u))[:30]
    assert result.username.tolist() == expected
    assert result.band.unique().tolist() == [800]
    assert result.role.tolist() == ['primary'] * 16 + ['reserve'] * 14
    assert result['rank'].tolist() == list(range(1, 31))


@pytest.mark.parametrize('account,reason', [(None, 'closed_or_missing'), ({}, ''),
    ({'tosViolation': True}, 'tosViolation'), ({'disabled': True}, 'disabled'),
    ({'title': 'BOT'}, 'BOT'), ({'closed': True}, 'closed'),
    ({'tosViolation': True, 'disabled': True, 'title': 'BOT'}, 'tosViolation;disabled;BOT')])
def test_screen_reasons(account, reason):
    assert v.screening_reason(account) == reason


class Response:
    def __init__(self, payload=None, status=200, raw=None):
        self.payload, self.status_code, self.raw, self.closed = payload, status, raw, False
    def raise_for_status(self):
        if self.status_code >= 400: raise requests.HTTPError('fake')
    def close(self): self.closed = True
    def json(self): return self.payload
    def iter_content(self, chunk_size): yield self.payload


def test_screen_post_chunks_429_missing(tmp_path, monkeypatch):
    v.write_csv(tmp_path / 'candidates.csv', candidates([(800, i+1, 'primary', f'fixture_{i}') for i in range(305)]))
    calls, replies, sleeps = [], [], []
    def post(url, **kwargs):
        calls.append((url, kwargs))
        response = Response(status=429) if len(calls) == 1 else Response([
            {'id': u, 'disabled': u == 'fixture_1'} for u in kwargs['data'].split(',') if u != 'fixture_2'])
        replies.append(response)
        return response
    monkeypatch.setattr(requests, 'post', post)
    monkeypatch.setattr(collect.time, 'sleep', sleeps.append)
    assert v.screen(tmp_path) == {'screened': 305, 'dropped': 2}
    assert sleeps == [60] and all(r.closed for r in replies)
    assert [len(k['data'].split(',')) for _, k in calls] == [300, 300, 5]
    assert all(k['headers']['User-Agent'] == 'tilt-research-dataset/0.1' for _, k in calls)
    screened = pd.read_csv(tmp_path / 'screened.csv').set_index('username')
    assert screened.loc['fixture_1', 'reason'] == 'disabled'
    assert screened.loc['fixture_2', 'reason'] == 'closed_or_missing'


def test_dump_http_sampler(tmp_path, monkeypatch):
    pgn = ''.join(f'''[Event "Rated Blitz game"]
[Site "https://lichess.org/fixture{i:02d}"]
[UTCDate "2026.10.01"]
[UTCTime "00:00:00"]
[White "Fixture_White"]
[Black "Fixture_Black"]
[WhiteElo "900"]
[BlackElo "1100"]
[Result "1-0"]
[TimeControl "180+0"]

1. e4 1-0

''' for i in range(12))
    calls = []
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response(raw=io.BytesIO(zstandard.ZstdCompressor().compress(pgn.encode())))
    monkeypatch.setattr(requests, 'get', get)
    with collect.staged_dump(tmp_path, v.SOURCE, speeds={'blitz'}, limit=12,
                             headers_only=True, max_staging_gb=.01) as (conn, stats):
        picked = v.pick_candidates(conn.execute('SELECT username,speed,AVG(rating),COUNT(*) FROM players GROUP BY username,speed'), {'fixture_white'})
    assert picked.username.tolist() == ['fixture_black']
    assert stats['candidates'] == 12 and calls[0][0] == v.SOURCE
    assert not list((tmp_path / 'external/staging').glob('*.sqlite'))


def test_replacement_order():
    rows = candidates([(1000, 17, 'reserve', 'same_later'), (1000, 16, 'reserve', 'same_first'),
        (800, 17, 'reserve', 'lower'), (1200, 17, 'reserve', 'upper'),
        (600, 17, 'reserve', 'far'), (1000, 18, 'reserve', 'disabled_one')])
    rows['eligible'] = [True] * 5 + [False]
    assert v.replacement_order(rows, 1000) == ['same_first', 'same_later', 'lower', 'upper', 'far']


def api_obj(gid, created):
    return dict(id=gid, createdAt=created, lastMoveAt=created+10000, rated=True,
        speed='blitz', variant='standard', status='resign', winner='white', moves='e4 e5',
        clock={'initial': 180, 'increment': 0}, clocks=[17900, 17800],
        players={'white': {'user': {'id': 'fixture_white', 'name': 'Fixture_White'}, 'rating': 900},
                 'black': {'user': {'id': 'fixture_black', 'name': 'Fixture_Black'}, 'rating': 1100}})


def test_download_http_resume_params(tmp_path, monkeypatch):
    calls = []
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response(payload=(json.dumps(api_obj('fixture_game', v.UNTIL-1000))+'\n').encode())
    monkeypatch.setattr(requests, 'get', get)
    monkeypatch.setenv('LICHESS_TOKEN', 'synthetic_test_token')
    first = v.download_player(tmp_path / 'new', tmp_path, 'fixture_white')
    assert v.download_player(tmp_path / 'new', tmp_path, 'fixture_white') == first
    assert first['games'] == 1 and len(calls) == 1
    params = calls[0][1]['params']
    assert params['max'] == 150 and params['until'] == v.UNTIL and params['perfType'] == 'blitz'
    assert params['clocks'] == params['evals'] == params['accuracy'] == 'true'
    assert 'since' not in params and params['sort'] == 'dateDesc'
    assert calls[0][1]['headers']['Authorization'] == 'Bearer synthetic_test_token'


def test_interrupted_download(tmp_path, monkeypatch):
    calls = []
    class Interrupted(Response):
        def iter_content(self, chunk_size):
            yield (json.dumps(api_obj('fixture_partial', v.UNTIL-1000))+'\n').encode()
            raise requests.ConnectionError('interrupted')
    def get(url, **kwargs):
        calls.append(kwargs['params'])
        return Interrupted() if len(calls) == 1 else Response(payload=(json.dumps(api_obj('fixture_partial', v.UNTIL-1000))+'\n').encode())
    monkeypatch.setattr(requests, 'get', get)
    with pytest.raises(requests.ConnectionError): v.download_player(tmp_path/'new', tmp_path, 'fixture_white')
    assert v.download_player(tmp_path/'new', tmp_path, 'fixture_white')['games'] == 1
    assert all('since' not in p and p['max'] == 150 for p in calls)


def test_cohort_resume_replacements(tmp_path, monkeypatch):
    out, data = tmp_path/'out', tmp_path/'new'
    out.mkdir()
    rows = candidates([(800, 1, 'primary', 'fixture_white'), (800, 17, 'reserve', 'fixture_short'),
                       (600, 17, 'reserve', 'fixture_lower'), (1000, 17, 'reserve', 'fixture_upper')])
    v.write_csv(out/'candidates.csv', rows)
    rows['eligible'], rows['reason'] = True, ''
    v.write_csv(out/'screened.csv', rows)
    v.write_json(out/'screen_manifest.json', {'candidates_sha256': v.sha(out/'candidates.csv')})
    calls = []
    def download(data, out, user):
        calls.append(user)
        return {'games': 60 if user == 'fixture_lower' else 10, 'game_ids': [], 'start_ms': 1, 'end_ms': 2}
    monkeypatch.setattr(v, 'download_player', download)
    monkeypatch.setattr(storage, 'read', lambda *a: pd.DataFrame(columns=['game_id']))
    monkeypatch.setattr(collect, 'normalize_api', lambda *a: 0)
    v.collect_cohort(data, out); v.collect_cohort(data, out)
    assert calls == ['fixture_white', 'fixture_short', 'fixture_lower']
    cohort = pd.read_csv(out/'cohort.csv')
    assert cohort.username.tolist() == ['fixture_lower']
    assert cohort.band.tolist() == [600] and cohort.slot_band.tolist() == [800]
    assert len(json.loads(cohort.replacement_history.iloc[0])) == 2


def cache_payload(fen, value=42):
    return json.dumps({'fen': fen, 'cp': value, 'mate': None, 'second_cp': value-2,
        'second_mate': None, 'engine_version': 'fixture', 'actual_nodes': 5000,
        'settings': {'binary_sha256': v.BINARY}}, separators=(',', ':'))


def test_cache_subset_identical_readonly(tmp_path, monkeypatch):
    old, data, out = tmp_path/'old', tmp_path/'new', tmp_path/'out'
    out.mkdir()
    source = old/'processed/engine/cache.sqlite'
    rows = [(f'fixture_fen_{i}', v.KEY, cache_payload(f'fixture_fen_{i}', i)) for i in range(510)]
    rows.append(('fixture_fen_1', 'wrong_settings', 'different bytes'))
    v.copy_positions(source, rows)
    v.write_json(old/'processed/features/manifest.json', {'engine': {'settings_key': v.KEY}})
    before = v.sha(source)
    monkeypatch.setattr(v, 'read_normalized', lambda *a: pd.DataFrame({'fen_before': ['fixture_fen_1', 'missing'], 'fen_after': ['fixture_fen_2', 'fixture_fen_1']}))
    result = v.cache_subset(data, out, old)
    assert result['cache_hits'] == 2 and result['remaining'] == 1 and v.sha(source) == before
    with closing(v.readonly(data/'processed/engine/cache.sqlite')) as conn:
        assert list(conn.execute('SELECT fen,settings_key,payload FROM positions ORDER BY fen')) == [rows[1], rows[2]]
    with closing(v.readonly(out/'agreement_sample.sqlite')) as conn:
        assert conn.execute('SELECT COUNT(*) FROM positions').fetchone()[0] == 500
    with closing(v.readonly(source)) as conn, pytest.raises(sqlite3.OperationalError): conn.execute('DELETE FROM positions')


@pytest.mark.parametrize('n,expected', [(1,0), (2,1), (5,2), (15,5), (16,5), (30,9)])
def test_a_rounding(n, expected, monkeypatch):
    monkeypatch.delenv('TILT_SALT', raising=False)
    names = [f'fixture_{i}' for i in range(n)]
    cohort = pd.DataFrame({'username': names, 'band': [800]*n})
    games = pd.DataFrame([dict(game_id=f'fixture_game_{i}', player=u, session_id=f'session_{i}', start_ms=i, color='white') for i,u in enumerate(names)])
    result = v.assign_frame(cohort, games, pd.DataFrame(columns=['game_id']), set())
    assert result.assignment.eq('A_prime').sum() == expected
    selected = sorted(names, key=lambda u: v.digest(v.PUBLIC+u))[:expected]
    assert set(result.loc[result.assignment == 'A_prime', 'player_id']) == {v.public_id(u) for u in selected}
    assert 'player' not in result and not result.astype(str).apply(lambda s:s.str.contains('fixture')).any().any()


def test_b_session_and_shared_drop(monkeypatch):
    monkeypatch.delenv('TILT_SALT', raising=False)
    names = [f'fixture_{i}' for i in range(3)]
    a = min(names, key=lambda u:v.digest(v.PUBLIC+u)); other = [u for u in names if u != a]
    cohort = pd.DataFrame({'username': names, 'band': [800]*3})
    games = pd.DataFrame([dict(game_id=f'game_{u}_{i}', player=u, session_id=f'{u}_{0 if i<6 else 1}', start_ms=i*100, color='white') for u in names for i in range(10)])
    shared = games.loc[(games.player == a) & (games.start_ms == 0), 'game_id'].iloc[0]
    games.loc[(games.player == other[0]) & (games.start_ms == 0), 'game_id'] = shared
    old = pd.DataFrame([dict(game_id=shared, white='fixture_old', black=a, start_ms=0)])
    result = v.assign_frame(cohort, games, old, {'fixture_old'})
    b = result[result.player_id == v.public_id(other[1])]
    assert b.loc[b.assignment == 'B_prime', 'start_ms'].tolist() == [600,700,800,900]
    assert (result.assignment == 'drop_shared_development').sum() == 2
    assert result.loc[result.cohort == 'old', 'assignment'].tolist() == ['drop_shared_development']


@pytest.mark.parametrize('artifacts', [
    ['holdout_manifest.parquet'], ['holdout_manifest.sha256'], ['excluded_sides.csv'],
    ['holdout_manifest.parquet', 'excluded_sides.csv']])
def test_refuses_manifest_regeneration(tmp_path, artifacts):
    for name in artifacts:
        (tmp_path/name).write_bytes(b'unchanged')
    with pytest.raises(ValueError, match='regenerate'): v.assign(tmp_path/'new', tmp_path, tmp_path/'old', tmp_path/'exclude')
    assert all((tmp_path/name).read_bytes() == b'unchanged' for name in artifacts)
    with pytest.raises(ValueError, match='regenerate'): v.assign(tmp_path/'new', tmp_path, tmp_path/'old', tmp_path/'exclude')


def gate_inputs():
    return [pd.DataFrame({'username': [f'fixture_{i}' for i in range(170)], 'games': [121]*170,
                         'kept_player_games': [120]*170}), set(),
        pd.DataFrame({'think_seconds': [1.]*90+[None]*10}),
        pd.DataFrame({'eval_after_cp': [1.]*97+[None]*3, 'eval_after_mate': [None]*97+[2.,None,None]}),
        {'settings_key':v.KEY, 'binary_sha256':v.BINARY, 'agreement':{'tested':500,'identical':500,'mismatches':0}}, 'same','same']


def test_gate_arithmetic():
    result = v.gate_arithmetic(*gate_inputs())
    assert result['pass'] and result['clock_coverage'] == .9 and result['eval_coverage'] == .98
    assert result['players_at_least_60'] == 170 and result['player_games'] == 20400
    assert result['kept_sides'] == 20400 and result['collected_sides'] == 20570


@pytest.mark.parametrize('failure', ['clocks','evals','size','no_overlap','old_manifest_unchanged','settings','agreement'])
def test_gate_failures(failure):
    args = gate_inputs()
    if failure == 'clocks': args[2].loc[0,'think_seconds'] = None
    if failure == 'evals': args[3].loc[0,'eval_after_cp'] = None
    if failure == 'size': args[0] = args[0].iloc[:169]
    if failure == 'no_overlap': args[1] = {'fixture_0'}
    if failure == 'old_manifest_unchanged': args[-1] = 'changed'
    if failure == 'settings': args[4]['settings_key'] = 'wrong'
    if failure == 'agreement': args[4]['agreement']['identical'] = 499
    result = v.gate_arithmetic(*args)
    assert not result['pass'] and not result['checks'][failure]


def test_resample_only_short_bands_once(tmp_path, monkeypatch):
    from contextlib import contextmanager
    out, old = tmp_path/'out', tmp_path/'old'
    out.mkdir()
    v.write_json(old/'processed/features/manifest.json', {'fixture': True})
    exclude = tmp_path/'excluded.txt'
    exclude.write_text('\n'.join(f'excluded_{i}' for i in range(196)))
    original = candidates([(800, 1, 'primary', 'retained_fixture'), (1000, 1, 'primary', 'retired_fixture')])
    v.write_csv(out/'candidates.csv', original)
    v.write_csv(out/'cohort.csv', pd.DataFrame({'band': [800], 'username': ['retained_fixture']}))
    calls = []
    @contextmanager
    def staged(*args, **kwargs):
        calls.append(kwargs)
        with closing(sqlite3.connect(':memory:')) as conn:
            conn.execute('CREATE TABLE players (username TEXT,speed TEXT,rating REAL)')
            for user in ('retained_fixture', 'new_fixture'):
                conn.executemany('INSERT INTO players VALUES (?,?,?)', [(user,'blitz',1100)]*12)
            yield conn, {'candidates':24}
    monkeypatch.setattr(collect, 'staged_dump', staged)
    v.sample(tmp_path/'new', out, exclude, old, bands=[1000])
    result = pd.read_csv(out/'candidates.csv')
    assert result.username.tolist() == ['retained_fixture', 'new_fixture']
    assert calls[0]['limit'] == 2400000 and calls[0]['headers_only']
    manifest = v.read_json(out/'sample_resample.json')
    assert manifest['bands'] == [1000] and len(manifest['eligible_headers_sha256']) == 64
    with pytest.raises(ValueError, match='Only one'): v.sample(tmp_path/'new',out,exclude,old,bands=[1000])


def test_resample_rejects_sufficient_cohort(tmp_path):
    v.write_csv(tmp_path/'cohort.csv', pd.DataFrame({'band': [800]*170}))
    with pytest.raises(ValueError, match='fewer than 170'):
        v.sample(tmp_path/'new',tmp_path,tmp_path/'exclude',tmp_path/'old',bands=[1000])


def test_assignment_public_order_independent_of_salt(monkeypatch):
    from tilt.labels.labels import pseudonym
    cohort = pd.DataFrame({'band': [800]*5, 'username':[f'fixture_{i}' for i in range(5)]})
    games = pd.DataFrame([dict(game_id=f'game_{i}',player=u,session_id=f'session_{i}',start_ms=i,color='white')
                          for i,u in enumerate(cohort.username)])
    monkeypatch.setenv('TILT_SALT','synthetic-salt-for-test-only')
    result = v.assign_frame(cohort,games,pd.DataFrame(columns=['game_id']),set())
    selected = sorted(cohort.username,key=lambda u:v.digest(v.PUBLIC+u))[:2]
    assert set(result.loc[result.assignment=='A_prime','player_id']) == {pseudonym(u) for u in selected}
    assert v.public_id('fixture_0') == pseudonym('fixture_0')


def test_gate_empty_denominators():
    args = gate_inputs()
    args[2], args[3] = args[2].iloc[:0],args[3].iloc[:0]
    result = v.gate_arithmetic(*args)
    assert not result['pass'] and result['clock_coverage']==result['eval_coverage']==0


def test_collect_materializes_only_accepted_and_resumes(tmp_path, monkeypatch):
    out, data = tmp_path/'out', tmp_path/'new'
    out.mkdir()
    rows = candidates([(800,1,'primary','fixture_white')])
    v.write_csv(out/'candidates.csv',rows)
    rows['eligible'],rows['reason']=True,''
    v.write_csv(out/'screened.csv',rows)
    v.write_json(out/'screen_manifest.json',{'candidates_sha256':v.sha(out/'candidates.csv')})
    calls=[]
    def get(url,**kwargs):
        calls.append(url)
        return Response(payload=''.join(json.dumps(api_obj(f'fixture_game_{i}',v.UNTIL-100000-i*10000))+'\n' for i in range(60)).encode())
    monkeypatch.setattr(requests,'get',get)
    result=v.collect_cohort(data,out)
    assert result['players']==1 and result['player_games']==60
    assert len(storage.read(data,'games'))==60
    assert len(pd.read_csv(out/'membership.csv'))==60
    v.collect_cohort(data,out)
    assert len(calls)==1 and len(storage.read(data,'games'))==60


def test_closed_after_screen_is_replaceable(tmp_path,monkeypatch):
    def get(*args,**kwargs):
        raise requests.HTTPError('closed',response=Response(status=404))
    monkeypatch.setattr(requests,'get',get)
    result=v.download_player(tmp_path/'new',tmp_path,'fixture_white')
    assert result['games']==0 and result['reason']=='closed_or_missing'


def test_exclusion_case_normalization(tmp_path):
    path=tmp_path/'excluded.txt';path.write_text('FIXTURE_0\n')
    result=v.pick_candidates([('FiXtUrE_0','blitz',900,12),('Fixture_1','blitz',900,12)],collect.usernames(path))
    assert result.username.tolist()==['fixture_1']


@pytest.fixture
def side_inputs(tmp_path):
    """All assignment/gate execution uses temporary synthetic roots only."""
    data, out, old = tmp_path/'new', tmp_path/'out', tmp_path/'old'
    out.mkdir()
    exclude = tmp_path/'excluded.txt'
    exclude.write_text('fixture_old\n')
    storage.connect(old).close()

    def build(kept=60, missing=(('noStart', 0, -100),), extra_player=False):
        features = pd.DataFrame([
            dict(game_id=f'fixture_kept_{i}', player='fixture_player', session_id=f'fixture_session_{i}',
                 start_ms=i*100, color='white') for i in range(kept)],
            columns=['game_id', 'player', 'session_id', 'start_ms', 'color'])
        dropped = pd.DataFrame([
            dict(player='fixture_player', game_id=f'fixture_missing_{i}', status=status,
                 plies=plies, start_ms=start) for i, (status, plies, start) in enumerate(missing)],
            columns=['player', 'game_id', 'status', 'plies', 'start_ms'])
        membership = pd.concat([features[['player', 'game_id']], dropped[['player', 'game_id']]],
                               ignore_index=True)
        cohort = pd.DataFrame([dict(username='fixture_player', band=800, games=len(membership),
                                   start_ms=-100, end_ms=100000)])
        if extra_player:
            extra = features.iloc[:60].copy()
            extra['player'] = 'fixture_other'
            features = pd.concat([features, extra], ignore_index=True)
            membership = pd.concat([membership, extra[['player', 'game_id']]], ignore_index=True)
            cohort.loc[len(cohort)] = ['fixture_other', 800, len(extra), 0, 5900]
        storage.write_frame(data/'processed/features/games.parquet', features)
        storage.append(data, dropped[['game_id', 'status', 'plies', 'start_ms']].to_dict('records'), [])
        v.write_csv(out/'membership.csv', membership)
        v.write_csv(out/'cohort.csv', cohort)
        return data, out, old, exclude, features, dropped

    return build


@pytest.mark.parametrize('plies', [2, 30, None])
def test_missing_feature_side_requires_at_most_one_ply(side_inputs, plies):
    data, out, *_ = side_inputs(missing=(('resign', plies, -100),))
    with pytest.raises(ValueError, match='Features missing'):
        v.cohort_sides(data, out)


def test_missing_normalized_game_raises(side_inputs, monkeypatch):
    data, out, *_ = side_inputs()
    monkeypatch.setattr(v, 'read_normalized', lambda *args:
                        pd.DataFrame(columns=['game_id', 'status', 'plies']))
    with pytest.raises(ValueError, match='Normalized game missing'):
        v.cohort_sides(data, out)


def test_present_feature_side_requires_session(side_inputs):
    data, out, _, _, features, _ = side_inputs(missing=())
    features.loc[0, 'session_id'] = None
    storage.write_frame(data/'processed/features/games.parquet', features)
    with pytest.raises(ValueError, match='Features missing'):
        v.cohort_sides(data, out)


@pytest.mark.parametrize('environment_salt', [False, True])
def test_assignment_excludes_short_sides_with_private_audit(side_inputs, monkeypatch, environment_salt):
    if not environment_salt:
        monkeypatch.delenv('TILT_SALT', raising=False)
    data, out, old, exclude, features, dropped = side_inputs(
        missing=(('noStart', 0, -100), ('outoftime', 1, 7000), ('resign', 1, 8000)),
        extra_player=True)
    # An existing empty flock from the operator's stopped attempt is harmless.
    (out/'assignment.lock').touch()
    result = v.assign(data, out, old, exclude)
    manifest = pd.read_parquet(out/'holdout_manifest.parquet')
    excluded = pd.read_csv(out/'excluded_sides.csv')
    metadata = v.read_json(out/'assignment_metadata.json')
    assert result['manifest_rows'] == len(features) == len(manifest) == 120
    assert excluded.columns.tolist() == ['player_id', 'game_id', 'status', 'plies']
    assert excluded.player_id.tolist() == [v.public_id('fixture_player')]*3
    assert excluded.game_id.tolist() == [v.public_id(gid, 'game:') for gid in dropped.game_id]
    assert excluded.status.tolist() == ['noStart', 'outoftime', 'resign']
    assert excluded.plies.tolist() == [0, 1, 1]
    assert not set(excluded.game_id) & set(manifest.game_id)
    assert metadata['excluded_sides_sha256'] == v.sha(out/'excluded_sides.csv')
    assert metadata['excluded_sides_by_status'] == {'noStart': 1, 'outoftime': 1, 'resign': 1}
    assert metadata['collected_sides'] == 123 and metadata['kept_sides'] == 120
    assert set(manifest.game_id) == {v.public_id(gid, 'game:') for gid in features.game_id}
    assert 'fixture_' not in (out/'excluded_sides.csv').read_text()
    assert 'fixture_' not in manifest.to_string() + (out/'assignment_metadata.json').read_text()
    before = {p.name: v.sha(p) for p in out.iterdir()}
    with pytest.raises(ValueError, match='regenerate'):
        v.assign(data, out, old, exclude)
    assert {p.name: v.sha(p) for p in out.iterdir()} == before


def test_assignment_records_empty_exclusions(side_inputs):
    data, out, old, exclude, *_ = side_inputs(missing=())
    v.assign(data, out, old, exclude)
    assert pd.read_csv(out/'excluded_sides.csv').empty
    metadata = v.read_json(out/'assignment_metadata.json')
    assert metadata['excluded_sides_by_status'] == {}
    assert metadata['collected_sides'] == metadata['kept_sides'] == 60
    assert metadata['excluded_sides_sha256'] == v.sha(out/'excluded_sides.csv')


@pytest.mark.parametrize('kept,start', [(64, -100), (60, 100000)])
def test_b_anchor_uses_only_kept_sides(side_inputs, kept, start):
    data, out, old, exclude, features, _ = side_inputs(kept=kept, missing=(('resign', 1, start),))
    v.assign(data, out, old, exclude)
    manifest = pd.read_parquet(out/'holdout_manifest.parquet')
    # One player rounds to zero A′ players; unique sessions expose the exact anchor.
    expected_start = features.start_ms.iloc[(4*kept + 4)//5 - 1]
    assert manifest.loc[manifest.assignment.eq('B_prime'), 'start_ms'].min() == expected_start
    baseline = v.assign_frame(pd.read_csv(out/'cohort.csv'), features,
                              pd.DataFrame(columns=['game_id']), set())
    pd.testing.assert_frame_equal(manifest, baseline, check_dtype=False)


@pytest.mark.parametrize('kept', [59, 0])
def test_assignment_rejects_short_player_before_any_write(side_inputs, kept):
    data, out, old, exclude, *_ = side_inputs(kept=kept,
        missing=tuple(('noStart', 0, -i-1) for i in range(60-kept)))
    before = {p.relative_to(out): v.sha(p) for p in out.rglob('*') if p.is_file()}
    with pytest.raises(ValueError, match='at least 60 kept sides'):
        v.assign(data, out, old, exclude)
    assert {p.relative_to(out): v.sha(p) for p in out.rglob('*') if p.is_file()} == before
    assert not (out/'assignment.lock').exists()


@pytest.mark.parametrize('case,passed,players,total', [
    ('boundary', True, 170, 20000), ('short_player', False, 169, 20000-59),
    ('short_total', False, 170, 19999)])
def test_gate_size_uses_kept_counts(case, passed, players, total):
    args = gate_inputs()
    args[0]['games'] = 150  # All raw collection thresholds pass in every case.
    args[0]['kept_player_games'] = [118]*110 + [117]*60
    if case == 'short_player':
        args[0].loc[0, 'kept_player_games'] = 59
    elif case == 'short_total':
        args[0].loc[0, 'kept_player_games'] -= 1
    result = v.gate_arithmetic(*args)
    assert result['checks']['size'] is passed
    assert result['players_at_least_60'] == players
    assert result['kept_sides'] == result['player_games'] == total
    assert result['collected_sides'] == 25500


def test_gate_qc_and_coverage_use_kept_sides(side_inputs):
    data, out, old, exclude, features, dropped = side_inputs()
    moves = pd.DataFrame([dict(game_id=gid, player='fixture_player', ply=1,
                              think_seconds=1. if gid in set(features.game_id) else None,
                              eval_after_cp=0. if gid in set(features.game_id) else None,
                              eval_after_mate=None)
                          for gid in [*features.game_id, *dropped.game_id]])
    storage.write_frame(data/'processed/features/moves.parquet', moves)
    v.write_json(data/'processed/features/manifest.json', {})
    v.write_json(old/'processed/features/manifest.json', {})
    v.write_json(out/'baseline.json', {'features_manifest_sha256': v.sha(old/'processed/features/manifest.json')})
    colab = gate_inputs()[4]
    colab['features_manifest_sha256'] = v.sha(data/'processed/features/manifest.json')
    v.write_json(out/'colab_result.json', colab)
    result = v.gate(data, out, old, exclude, out/'colab_result.json')
    assert result['collected_sides'] == 61 and result['kept_sides'] == 60
    assert result['players_at_least_60'] == 1 and result['unique_games'] == 60
    assert result['own_moves'] == result['plies'] == 60
    assert result['clock_coverage'] == result['eval_coverage'] == 1
    bands = pd.read_csv(out/'qc_bands.csv')
    assert bands.player_games.tolist() == [61] and bands.kept_player_games.tolist() == [60]
    assert bands.columns.get_loc('kept_player_games') == bands.columns.get_loc('player_games') + 1
    assert bands.start_ms.tolist() == [0] and bands.end_ms.tolist() == [5900]
    assert bands.own_moves.tolist() == bands.plies.tolist() == [60]
    dates = pd.read_csv(out/'qc_dates.csv')
    assert dates.kept_player_games.tolist() == [60]
    assert 'fixture_' not in (out/'qc_dates.csv').read_text() + (out/'s2_gate.json').read_text()


def test_active_preregistration_lock():
    v.check_lock()
