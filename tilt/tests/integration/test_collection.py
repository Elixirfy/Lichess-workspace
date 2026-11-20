from copy import deepcopy
import gzip
import io
import json
from pathlib import Path

import chess.pgn
import pytest
import zstandard

from tilt.data import storage
from tilt.data.collect import collect_api, collect_dump, normalize_api, sample_players, usernames
from tilt.data.normalize import api_game, pgn_game

FIXTURES = Path(__file__).parents[1] / 'fixtures'


def test_normalize_shared_schema_and_clock_semantics(api_raw):
    game, moves = api_game(api_raw)
    pgn = chess.pgn.read_game(io.StringIO((FIXTURES / 'tiny.pgn').read_text()))
    other, plies = pgn_game(pgn)
    assert set(game) == set(other) == set(storage.GAME_SCHEMA.names)
    assert set(moves[0]) == set(plies[0]) == set(storage.MOVE_SCHEMA.names)
    assert game['game_id'] == 'api00001'
    assert other['game_id'] == 'fixture1'
    assert moves[2]['clock_seconds'] == plies[2]['clock_seconds'] == 178
    assert moves[0]['cp'] == plies[0]['cp'] == 20
    assert moves[5]['mate'] == plies[5]['mate'] == 1
    assert moves[6]['mate'] == plies[6]['mate'] == 0
    assert not moves[-1]['increment_applied']
    assert not moves[0]['increment_applied'] and not moves[1]['increment_applied']
    assert game['end_upper_ms'] >= game['end_ms']


def test_extra_stopped_clock_is_not_a_ply(api_raw):
    raw = deepcopy(api_raw)
    raw.update(moves='e4 e5 Nf3 Nc6', status='resign', clocks=[18000,18000,17900,17950,17700])
    game, moves = api_game(raw, observed_ms=999999)
    assert len(moves) == 4
    assert moves[-1]['increment_applied']
    assert game['end_ms'] == raw['lastMoveAt'] + 2000
    assert game['end_upper_ms'] >= game['end_ms'] + 40


def test_missing_end_dump_is_unknown():
    handle = io.StringIO((FIXTURES / 'tiny.pgn').read_text())
    chess.pgn.read_game(handle)
    g, _ = pgn_game(chess.pgn.read_game(handle))
    assert g['end_ms'] is None and g['end_upper_ms'] is None
    assert g['speed'] == 'rapid'


def test_zstd_stream_filters_min_games_and_sampling(tmp_path):
    dump = tmp_path / 'tiny.pgn.zst'
    dump.write_bytes(zstandard.ZstdCompressor().compress((FIXTURES / 'tiny.pgn').read_bytes()))
    result = collect_dump(tmp_path / 'data', str(dump), users={'alice'}, speeds={'blitz'}, min_games=2)
    assert result['imported'] == 2
    assert storage.read(tmp_path / 'data', 'games').shape[0] == 2
    assert collect_dump(tmp_path / 'data', str(dump), min_games=1, limit=10)['imported'] == 1
    assert not list((tmp_path / 'data' / 'external' / 'staging').iterdir())
    selected = tmp_path / 'sample.csv'
    stats = sample_players(tmp_path / 'sample-data', str(dump), selected, min_games=2, per_stratum=1)
    assert stats['sampled_player_contexts'] == 1
    assert usernames(selected) == {'alice'}
    expected = selected.read_bytes()
    sample_players(tmp_path / 'sample-data', str(dump), selected, min_games=2, per_stratum=1)
    assert selected.read_bytes() == expected
    assert collect_dump(tmp_path / 'limited', str(dump), min_games=2, limit=1)['imported'] == 0


class Response:
    def __init__(self, body=b'', status=200):
        self.body, self.status_code, self.closed = body, status, False
    def close(self):
        self.closed = True
    def raise_for_status(self):
        if self.status_code >= 400:
            raise ValueError('bad status')
    def iter_content(self, chunk_size):
        # Break across JSON lines and across unicode characters.
        for i in range(0, len(self.body), 7):
            yield self.body[i:i+7]


def test_api_raw_byte_preservation_429_resume_and_dedup(tmp_path, api_raw, monkeypatch):
    body = ('\n' + json.dumps(api_raw, ensure_ascii=False) + '\n\n').encode()
    responses = [Response(status=429), Response(body), Response(b'')]
    calls, sleeps = [], []
    def get(url, **kwargs):
        assert not calls or calls[-1][1].closed
        response = responses.pop(0)
        calls.append((kwargs, response))
        return response
    monkeypatch.setattr('requests.get', get)
    monkeypatch.setattr('time.sleep', sleeps.append)
    monkeypatch.setenv('LICHESS_TOKEN', 'token-must-never-appear-in-raw-files')
    assert collect_api(tmp_path, ['Alice'], max_games=20) == 1
    assert sleeps == [60]
    assert calls[0][0]['headers']['User-Agent'] == 'tilt-research-dataset/0.1'
    file = next((tmp_path / 'raw/api/alice').glob('*.ndjson.gz'))
    assert gzip.open(file).read() == body
    assert collect_api(tmp_path, ['alice'], max_games=20) == 0
    assert calls[-1][0]['params']['since'] == api_raw['createdAt'] + 1
    assert calls[-1][0]['params']['sort'] == 'dateAsc'
    assert normalize_api(tmp_path) == 0
    assert storage.read(tmp_path, 'moves').shape[0] == 7
    assert 'token-must' not in ''.join(p.read_text() for p in tmp_path.rglob('*.json'))


def test_failed_stream_never_advances_cursor(tmp_path, api_raw, monkeypatch):
    class Broken(Response):
        def iter_content(self, chunk_size):
            yield (json.dumps(api_raw)+'\n').encode()
            raise OSError('disconnect')
    monkeypatch.setattr('requests.get', lambda *a, **k: Broken())
    with pytest.raises(OSError):
        collect_api(tmp_path, ['alice'])
    assert not list(tmp_path.rglob('cursor-*.json'))
    assert normalize_api(tmp_path) == 1


def test_perf_filtered_resume_uses_strict_search_boundary(tmp_path, api_raw, monkeypatch):
    calls=[]
    def get(url, **kwargs):
        calls.append(kwargs)
        return Response((json.dumps(api_raw)+'\n').encode() if len(calls)==1 else b'')
    monkeypatch.setattr('requests.get',get)
    collect_api(tmp_path,['alice'],perf='blitz')
    collect_api(tmp_path,['alice'],perf='blitz')
    assert calls[-1]['params']['since'] == api_raw['createdAt']


def test_uncommitted_parquet_shard_is_invisible(corpus):
    data, add=corpus
    add(1)
    file=next((data/'processed/normalized/games').glob('*.parquet'))
    orphan=file.with_name('orphan.parquet')
    orphan.write_bytes(file.read_bytes())
    assert len(storage.read(data,'games')) == 1


def test_dump_claim_draw_increment_is_not_guessed():
    pgn=chess.pgn.read_game(io.StringIO('''[White "alice"]
[Black "bob"]
[TimeControl "180+2"]
[Result "1/2-1/2"]

1. Nf3 Nf6 2. Ng1 Ng8 3. Nf3 Nf6 4. Ng1 Ng8 1/2-1/2'''))
    _,moves=pgn_game(pgn)
    assert moves[-1]['increment_applied'] is None


def test_first_source_wins_even_with_duplicate_ids_in_one_batch(tmp_path,api_raw):
    first, moves=api_game(api_raw)
    changed=deepcopy(api_raw)
    changed['players']['white']['rating']=9999
    changed['analysis'][0]['eval']=9999
    second, later=api_game(changed)
    assert storage.append(tmp_path,[first,second],moves+later)==1
    assert storage.read(tmp_path,'games').iloc[0].white_rating==1200
    assert storage.read(tmp_path,'moves').iloc[0].cp==20


@pytest.mark.parametrize('perf', [None, 'blitz'])
def test_api_backfill_strict_until_oldest_watermark_and_exhaustion(tmp_path, api_raw, monkeypatch, capsys, perf):
    newest = deepcopy(api_raw)
    newest.update(id='newest01', createdAt=300000)
    middle = deepcopy(api_raw)
    middle.update(id='middle01', createdAt=200000)
    older = deepcopy(api_raw)
    older.update(id='older001', createdAt=199999)  # exactly 1 ms before oldest
    oldest = deepcopy(api_raw)
    oldest.update(id='oldest01', createdAt=100000)
    batches = [[newest, middle], [older], [oldest], [], []]
    calls = []
    def get(url, **kwargs):
        calls.append(kwargs['params'])
        return Response(('\n'.join(json.dumps(o) for o in batches.pop(0)) + '\n').encode())
    monkeypatch.setattr('requests.get', get)
    assert collect_api(tmp_path, ['alice'], max_games=2, perf=perf) == 2
    assert collect_api(tmp_path, ['alice'], max_games=1, perf=perf, backfill=True) == 1
    assert calls[-1]['until'] == 200000
    assert calls[-1]['sort'] == 'dateDesc' and calls[-1]['max'] == 1
    assert 'since' not in calls[-1]
    assert collect_api(tmp_path, ['alice'], perf=perf, backfill=True) == 1
    assert calls[-1]['until'] == 199999
    assert collect_api(tmp_path, ['alice'], perf=perf, backfill=True) == 0
    assert 'No older games remain' in capsys.readouterr().err
    state = json.loads(next(tmp_path.rglob('cursor-*.json')).read_text())
    assert state['created_at'] == 300000 and state['oldest_created_at'] == 100000
    assert state['older_exhausted']
    collect_api(tmp_path, ['alice'], perf=perf)
    assert calls[-1]['since'] == 300000 + (0 if perf else 1)


def test_backfill_failure_preserves_both_watermarks(tmp_path, api_raw, monkeypatch):
    monkeypatch.setattr('requests.get', lambda *a, **k: Response((json.dumps(api_raw) + '\n').encode()))
    collect_api(tmp_path, ['alice'])
    cursor = next(tmp_path.rglob('cursor-*.json'))
    before = cursor.read_bytes()
    class Broken(Response):
        def iter_content(self, chunk_size):
            obj = {**api_raw, 'createdAt': api_raw['createdAt'] - 1}
            yield (json.dumps(obj) + '\n').encode()
            raise OSError('disconnect')
    monkeypatch.setattr('requests.get', lambda *a, **k: Broken())
    with pytest.raises(OSError):
        collect_api(tmp_path, ['alice'], backfill=True)
    assert cursor.read_bytes() == before


def test_trailing_ndjson_line_uses_same_observation_time(tmp_path, api_raw, monkeypatch):
    from tilt.data import collect
    second = {**api_raw, 'id': 'trailing'}
    monkeypatch.setattr('requests.get', lambda *a, **k: Response((json.dumps(api_raw) + '\n' + json.dumps(second)).encode()))
    original = collect.api_game
    monkeypatch.setattr(collect.time, 'time', lambda: 12345.678)
    observed = []
    def parse(obj, observed_ms=None):
        assert observed_ms is not None
        observed.append(observed_ms)
        return original(obj, observed_ms)
    monkeypatch.setattr(collect, 'api_game', parse)
    assert collect_api(tmp_path, ['alice']) == 2
    assert observed == [12345678, 12345678]


def test_keep_perf_filters_on_the_client_and_in_raw_files(tmp_path, api_raw, monkeypatch):
    # A local lila answers perfType exports from lila-search: keep_perf asks for every perf and filters here.
    import hashlib
    blitz = {**api_raw, 'perf': 'blitz'}
    rapid = {**api_raw, 'id': 'rapid001', 'perf': 'rapid', 'speed': 'rapid', 'createdAt': api_raw['createdAt'] + 5}
    trailing = {**api_raw, 'id': 'blitz002', 'perf': 'blitz', 'createdAt': api_raw['createdAt'] + 9}
    body = (json.dumps(blitz) + '\n' + json.dumps(rapid) + '\n' + json.dumps(trailing)).encode()
    calls = []
    def get(url, **kwargs):
        calls.append(kwargs['params'])
        return Response(body if len(calls) == 1 else b'')
    monkeypatch.setattr('requests.get', get)
    assert collect_api(tmp_path, ['alice'], keep_perf='blitz') == 2
    assert 'perfType' not in calls[0]
    raw = gzip.open(next((tmp_path / 'raw/api/alice').glob('*.ndjson.gz'))).read()
    assert [json.loads(line)['id'] for line in raw.splitlines() if line.strip()] == ['api00001', 'blitz002']
    assert sorted(storage.read(tmp_path, 'games').game_id) == ['api00001', 'blitz002']
    # the newest game of any perf moves the cursor; the Mongo path resumes at since = cursor + 1
    collect_api(tmp_path, ['alice'], keep_perf='blitz')
    assert calls[-1]['since'] == trailing['createdAt'] + 1 and 'perfType' not in calls[-1]
    # recovering from the raw files keeps the root blitz-only
    assert normalize_api(tmp_path) == 0
    assert sorted(storage.read(tmp_path, 'games').game_id) == ['api00001', 'blitz002']
    # a separate cursor from the unfiltered and the server-filtered requests
    cursors = [p.name for p in (tmp_path / 'raw/api/alice').glob('cursor-*.json')]
    default = hashlib.sha256(json.dumps([None, None, None]).encode()).hexdigest()[:12]
    server = hashlib.sha256(json.dumps([None, None, 'blitz']).encode()).hexdigest()[:12]
    assert len(cursors) == 1 and cursors[0] not in (f'cursor-{default}.json', f'cursor-{server}.json')
    with pytest.raises(ValueError, match='exclusive'):
        collect_api(tmp_path, ['alice'], perf='blitz', keep_perf='blitz')


def test_collect_dump_requires_target_users_or_limit(tmp_path):
    with pytest.raises(ValueError, match='requires --users'):
        collect_dump(tmp_path, str(FIXTURES / 'tiny.pgn'), speeds={'blitz'})


@pytest.mark.parametrize('command', ['collect', 'sample'])
def test_staging_guard_cleans_files_and_checks_free_disk(tmp_path, monkeypatch, command):
    from types import SimpleNamespace
    from tilt.data import collect
    source = str(FIXTURES / 'tiny.pgn')
    def run(budget):
        if command == 'collect':
            return collect_dump(tmp_path, source, limit=3, max_staging_gb=budget)
        return sample_players(tmp_path, source, tmp_path / 'sample.csv', min_games=1, max_staging_gb=budget)
    monkeypatch.setattr(collect.shutil, 'disk_usage', lambda p: SimpleNamespace(free=0))
    with pytest.raises(ValueError, match='free disk'):
        run(5)
    assert not list((tmp_path / 'external' / 'staging').iterdir())
    monkeypatch.setattr(collect.shutil, 'disk_usage', lambda p: SimpleNamespace(free=10 * 1024**3))
    with pytest.raises(ValueError, match='Staging exceeded'):
        run(1 / 1024**3)  # 1 byte; includes SQLite pages not yet flushed
    assert not list((tmp_path / 'external' / 'staging').iterdir())
    assert not (tmp_path / 'sample.csv').exists()
    for invalid in (0, -1, float('nan'), float('inf')):
        with pytest.raises(ValueError, match='positive and finite'):
            run(invalid)


@pytest.mark.parametrize('command', ['collect', 'sample'])
def test_staging_guard_aborts_after_spool_grows(tmp_path, monkeypatch, command):
    from tilt.data import collect
    parsed = []
    original = collect.pgn_game
    def parse(*args, **kwargs):
        parsed.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(collect, 'pgn_game', parse)
    source = str(FIXTURES / 'tiny.pgn')
    with pytest.raises(ValueError, match='Staging exceeded'):
        if command == 'collect':
            collect_dump(tmp_path, source, limit=3, max_staging_gb=24 / 1024**2)
        else:
            sample_players(tmp_path, source, tmp_path / 'sample.csv', max_staging_gb=24 / 1024**2)
    assert parsed  # exceeded during writes, not merely the initial empty schema
    assert not list((tmp_path / 'external' / 'staging').iterdir())
    assert not (tmp_path / 'processed' / 'normalized').exists()


def test_backfill_keeps_interval_bounds_and_cursor_scope(tmp_path, api_raw, monkeypatch):
    calls = []
    def get(url, **kwargs):
        calls.append(kwargs['params'])
        return Response((json.dumps(api_raw) + '\n').encode())
    monkeypatch.setattr('requests.get', get)
    collect_api(tmp_path, ['alice'], since=1, until=99999999)
    assert calls[-1]['sort'] == 'dateDesc'
    collect_api(tmp_path, ['alice'], since=1, until=99999999, backfill=True)
    assert calls[-1]['since'] == 1 and calls[-1]['until'] == api_raw['createdAt']
    collect_api(tmp_path, ['alice'], since=2, until=99999999, backfill=True)
    assert calls[-1]['until'] == 99999999  # a different interval has no oldest cursor
    assert len(list(tmp_path.rglob('cursor-*.json'))) == 2


def test_api_observation_bound_is_when_line_arrives_not_request_start(tmp_path, api_raw, monkeypatch):
    from tilt.data import collect
    clock = [100.0]
    class Delayed(Response):
        def iter_content(self, chunk_size):
            clock[0] = 200.0
            yield (json.dumps(api_raw) + '\n' + json.dumps({**api_raw, 'id': 'tail0001'})).encode()
    monkeypatch.setattr(collect.time, 'time', lambda: clock[0])
    monkeypatch.setattr('requests.get', lambda *a, **k: Delayed())
    original = collect.api_game
    observed = []
    def parse(obj, observed_ms=None):
        observed.append(observed_ms)
        return original(obj, observed_ms)
    monkeypatch.setattr(collect, 'api_game', parse)
    collect_api(tmp_path, ['alice'])
    assert observed == [200000, 200000]
