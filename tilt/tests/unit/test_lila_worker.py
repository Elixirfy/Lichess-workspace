"""lila tilt_queue worker with an in-memory collection; no MongoDB, HTTP or Stockfish."""
import datetime
import json

import pytest

from tilt.service import lila_worker


class FakeCursor(list):
    def sort(self, key, direction):
        return FakeCursor(sorted(self, key=lambda d: d[key], reverse=direction < 0))

    def limit(self, n):
        return FakeCursor(self[:n])


def lookup(doc, dotted):
    for part in dotted.split('.'):
        if not isinstance(doc, dict) or part not in doc:
            return KeyError
        doc = doc[part]
    return doc


def matches(doc, query):
    for key, want in query.items():
        value = lookup(doc, key)
        if isinstance(want, dict) and '$exists' in want:
            if (value is not KeyError) != want['$exists']:
                return False
        elif not (value == want or (isinstance(value, list) and want in value)):
            return False
    return True


class FakeColl:
    def __init__(self, docs):
        self.docs = {d['_id']: d for d in docs}
        self.queries = []

    def find(self, query):
        self.queries.append(query)
        return FakeCursor(d for d in self.docs.values() if matches(d, query))

    def update_one(self, query, update):
        doc = self.docs[query['_id']]
        for key, value in update['$set'].items():
            *path, last = key.split('.')
            target = doc
            for part in path:
                target = target[part]
            target[last] = value


def doc(game, user='alice', seconds_ago=600, speed=None):
    queued = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=seconds_ago)
    out = {'_id': game + 'w', 'gameId': game, 'userId': user, 'color': True, 'queuedAt': queued}
    if speed:
        out['speed'] = speed
    return out


@pytest.fixture
def models(tmp_path):
    (tmp_path / 'processed' / 'features').mkdir(parents=True)
    (tmp_path / 'processed/features/manifest.json').write_text(json.dumps(dict(
        window_plies=12, min_prior_games=5, session_gap_minutes=30, max_history_games=200,
        engine=dict(hash_mb=32, budget=dict(nodes=5000)))))
    return tmp_path


@pytest.fixture
def pipeline(monkeypatch):
    calls = dict(collect=[], analyze=[], compute=[])
    monkeypatch.setattr(lila_worker.collect, 'collect_api',
                        lambda data, users, max_games, base_url: calls['collect'].append((users, max_games, base_url)))
    monkeypatch.setattr(lila_worker, 'analyze', lambda *a, **k: calls['analyze'].append(k))
    monkeypatch.setattr(lila_worker, 'compute', lambda *a: calls['compute'].append(a[1:]))
    return calls


def scored(data, player, game_id, models):
    if game_id == 'missing1':
        raise ValueError('No matching local game for this player')
    return {'games': [dict(weak_model_tilt_score=73.6, weak_model_tilt_flag=True,
                           top_factors=[dict(feature='attack_rate', score_delta=4.0),
                                        dict(feature='defensive_rate', score_delta=-2.0)])]}


def test_scores_written_back_with_training_settings(tmp_path, models, pipeline, monkeypatch):
    monkeypatch.setattr(lila_worker.score, 'run', scored)
    coll = FakeColl([doc('gameaaaa'), doc('gamebbbb', user='bob')])
    assert lila_worker.answer(coll, lila_worker.pending(coll), tmp_path / 'lila', models,
                              'http://localhost:9663', '/usr/games/stockfish') == 2
    response = coll.docs['gameaaaaw']['response']
    assert response['pred'] == dict(score=74, flag=True, factors=['attack_rate', 'defensive_rate'])
    assert set(response) == {'at', 'pred'} and response['at'].tzinfo is not None
    assert [c[0] for c in pipeline['collect']] == [{'alice'}, {'bob'}]
    assert pipeline['collect'][0][1:] == (200, 'http://localhost:9663')
    assert pipeline['analyze'] == [dict(nodes=5000, depth=None, processes=1, hash_mb=32)]
    assert pipeline['compute'] == [(12, 5, 30, 200)]
    assert lila_worker.pending(coll) == []


def test_unexported_game_waits_then_fails(tmp_path, models, pipeline, monkeypatch):
    monkeypatch.setattr(lila_worker.score, 'run', scored)
    coll = FakeColl([doc('missing1', seconds_ago=5)])
    assert lila_worker.answer(coll, lila_worker.pending(coll), tmp_path, models, 'u', 'e') == 0
    assert 'response' not in coll.docs['missing1w']
    coll.docs['missing1w']['queuedAt'] -= datetime.timedelta(seconds=lila_worker.EXPORT_GRACE_SECONDS)
    assert lila_worker.answer(coll, lila_worker.pending(coll), tmp_path, models, 'u', 'e') == 1
    assert coll.docs['missing1w']['response']['err'] == 'game not available'
    assert 'pred' not in coll.docs['missing1w']['response']


def test_export_failure_answers_only_that_user(tmp_path, models, pipeline, monkeypatch):
    def collect_api(data, users, max_games, base_url):
        if users == {'gone'}:
            raise RuntimeError('404')
    monkeypatch.setattr(lila_worker.collect, 'collect_api', collect_api)
    monkeypatch.setattr(lila_worker.score, 'run', scored)
    coll = FakeColl([doc('gameaaaa'), doc('gamecccc', user='gone')])
    assert lila_worker.answer(coll, lila_worker.pending(coll), tmp_path, models, 'u', 'e') == 2
    assert coll.docs['gamecccc' + 'w']['response']['err'] == 'export failed: RuntimeError'
    assert coll.docs['gameaaaaw']['response']['pred']['score'] == 74


def test_unreachable_site_keeps_docs_queued(tmp_path, models, pipeline, monkeypatch):
    def collect_api(data, users, max_games, base_url):
        raise lila_worker.requests.ConnectionError('refused')
    monkeypatch.setattr(lila_worker.collect, 'collect_api', collect_api)
    coll = FakeColl([doc('gameaaaa')])
    assert lila_worker.answer(coll, lila_worker.pending(coll), tmp_path, models, 'u', 'e') == 0
    assert 'response' not in coll.docs['gameaaaaw'] and pipeline['analyze'] == []


def test_cli_wires_worker(monkeypatch, tmp_path):
    from tilt import __main__ as cli
    seen = {}

    def serve(*a, **k):
        seen.update(args=a, kwargs=k)
        return {'answered': 0}
    monkeypatch.setattr(lila_worker, 'serve', serve)
    cli.main(['--data', str(tmp_path), 'lila-worker', '--once', '--lila-url', 'http://x'])
    mongo, db, lila_data, models, url, engine, interval, once = seen['args']
    assert (mongo, db, url, once) == ('mongodb://127.0.0.1:27017', 'lichess', 'http://x', True)
    assert models == tmp_path and lila_data.name == 'lila' and seen['kwargs'] == dict(data_v3=None)
    cli.main(['--data', str(tmp_path), 'lila-worker', '--once', '--lila-data-v3', str(tmp_path / 'v3')])
    assert seen['kwargs'] == dict(data_v3=tmp_path / 'v3')


# M-v3 mode (reports/label_v3_deployment.md): live_scoring is faked; its own tests cover scoring.

class FakeV3:
    def __init__(self, shadow):
        self.shadow = shadow

    def shadow_on(self):
        return self.shadow


V3_PRED = dict(score=41, flag=True, factors=['session'], v=3, prob=.4123, level='high', head='p20',
               signs=[dict(family='session', share=.5)],
               rules=dict(label='TILT', context='strong', fired=['C1', 'E1', 'E2'], missing=[], pending=['E7'],
                          reason=None))


@pytest.fixture
def v3(monkeypatch, tmp_path):
    calls = dict(collect=[], analyze=[], compute=[], assess=[], refresh=[], shadow=True,
                 key=lila_worker.TRAINED_SETTINGS_KEY)
    monkeypatch.setattr(lila_worker.live_scoring, 'load', lambda models: FakeV3(calls['shadow']))
    monkeypatch.setattr(lila_worker.collect, 'collect_api',
                        lambda data, users, **k: calls['collect'].append((data.name, users, k)))

    def analyze(root, engine, **k):
        calls['analyze'].append(root.name)
        return dict(settings_key=calls['key'])
    monkeypatch.setattr(lila_worker, 'analyze', analyze)
    monkeypatch.setattr(lila_worker, 'compute', lambda root, *a: calls['compute'].append(root.name))

    def assess(model, root, player, game_id):
        calls['assess'].append((root, player, game_id))
        if game_id.startswith('missing'):
            raise ValueError('No matching local game for this player')
        if game_id.startswith('guest'):
            return dict(skip='incomplete')
        return dict(pred=json.loads(json.dumps(V3_PRED)))
    monkeypatch.setattr(lila_worker.live_scoring, 'assess', assess)

    def refresh_rules(root, player, game_id):
        calls['refresh'].append(game_id)
        return dict(V3_PRED['rules'], pending=[], fired=['C1', 'E1', 'E2', 'E7'])
    monkeypatch.setattr(lila_worker.live_scoring, 'refresh_rules', refresh_rules)
    monkeypatch.setattr(lila_worker.score, 'run', scored)
    return calls


def run_v3(coll, tmp_path, models):
    return lila_worker.answer(coll, lila_worker.pending(coll), tmp_path / 'lila', models, 'http://x', 'e',
                              data_v3=tmp_path / 'lila-v3')


def test_v3_scores_blitz_skips_other_speeds_and_keeps_the_shadow(tmp_path, models, v3):
    coll = FakeColl([doc('gameaaaa', speed='blitz'), doc('gamebbbb', user='bob', speed='bullet'),
                     doc('gamecccc', user='carol', speed='rapid'), doc('guest111', user='dave')])
    assert run_v3(coll, tmp_path, models) == 4
    assert coll.docs['gamebbbbw']['response'].keys() == {'at', 'skip'}
    assert coll.docs['gamebbbbw']['response']['skip'] == coll.docs['gameccccw']['response']['skip'] == 'speed'
    response = coll.docs['gameaaaaw']['response']
    assert response['pred'] == V3_PRED and set(response) == {'at', 'pred', 'shadow'}
    assert response['shadow'] == dict(model='P3-B', score=74, flag=True, factors=['attack_rate', 'defensive_rate'])
    assert coll.docs['guest111w']['response'].keys() == {'at', 'skip'}
    assert coll.docs['guest111w']['response']['skip'] == 'incomplete'
    # Skipped speeds cost no export; the v3 root only receives blitz.
    assert ('lila-v3', {'alice'}, dict(max_games=200, base_url='http://x', keep_perf='blitz')) in v3['collect']
    assert ('lila', {'alice'}, dict(max_games=200, base_url='http://x')) in v3['collect']
    assert sorted((name, sorted(users)) for name, users, _ in v3['collect']) == \
        [('lila', ['alice']), ('lila', ['dave']), ('lila-v3', ['alice']), ('lila-v3', ['dave'])]
    assert v3['analyze'] == ['lila', 'lila-v3'] and v3['compute'] == ['lila', 'lila-v3']
    assert all(root == tmp_path / 'lila-v3' / 'processed' for root, _, _ in v3['assess'])


@pytest.mark.parametrize('status, queued', [(503, True), (500, True), (404, False)])
def test_v3_server_errors_keep_docs_queued(tmp_path, models, v3, monkeypatch, status, queued):
    # lila answers exports with 503 during its 20-second warm-up; a client error is final.
    def collect_api(data, users, **k):
        response = lila_worker.requests.Response()
        response.status_code = status
        if users == {'alice'}:
            raise lila_worker.requests.HTTPError(f'{status}', response=response)
    monkeypatch.setattr(lila_worker.collect, 'collect_api', collect_api)
    coll = FakeColl([doc('gameaaaa', speed='blitz'), doc('gamebbbb', user='bob', speed='blitz')])
    assert run_v3(coll, tmp_path, models) == (1 if queued else 2)
    assert coll.docs['gamebbbbw']['response']['pred'] == V3_PRED
    if queued:
        assert 'response' not in coll.docs['gameaaaaw']
    else:
        assert coll.docs['gameaaaaw']['response']['err'] == 'export failed: HTTP 404'


def test_v3_without_shadow_after_its_date(tmp_path, models, v3):
    v3['shadow'] = False
    coll = FakeColl([doc('gameaaaa', speed='blitz')])
    assert run_v3(coll, tmp_path, models) == 1
    assert set(coll.docs['gameaaaaw']['response']) == {'at', 'pred'}
    assert [c[0] for c in v3['collect']] == ['lila-v3'] and v3['analyze'] == ['lila-v3']


def test_v3_refuses_other_engine_settings(tmp_path, models, v3):
    v3['key'] = '0' * 64
    coll = FakeColl([doc('gameaaaa', speed='blitz')])
    assert run_v3(coll, tmp_path, models) == 1
    assert coll.docs['gameaaaaw']['response']['err'] == 'engine settings differ from training'
    assert v3['assess'] == []


def test_v3_unexported_game_waits_then_fails(tmp_path, models, v3):
    coll = FakeColl([doc('missing1', seconds_ago=5, speed='blitz')])
    assert run_v3(coll, tmp_path, models) == 0 and 'response' not in coll.docs['missing1w']
    coll.docs['missing1w']['queuedAt'] -= datetime.timedelta(seconds=lila_worker.EXPORT_GRACE_SECONDS)
    assert run_v3(coll, tmp_path, models) == 1
    assert coll.docs['missing1w']['response']['err'] == 'game not available'


def test_v3_docs_without_speed_use_the_shadow_root(tmp_path, models, v3, monkeypatch):
    monkeypatch.setattr(lila_worker, 'stored_speed', lambda data, game_id: 'bullet')
    coll = FakeColl([doc('missing1', seconds_ago=5)])
    assert run_v3(coll, tmp_path, models) == 1
    assert coll.docs['missing1w']['response']['skip'] == 'speed'


def test_v3_shadow_failure_never_changes_the_answer(tmp_path, models, v3, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError('old model')
    monkeypatch.setattr(lila_worker.score, 'run', broken)
    coll = FakeColl([doc('gameaaaa', speed='blitz')])
    assert run_v3(coll, tmp_path, models) == 1
    response = coll.docs['gameaaaaw']['response']
    assert response['pred'] == V3_PRED and response['shadow'] == dict(model='P3-B', err='RuntimeError')


def test_v3_next_game_updates_pending_e7(tmp_path, models, v3):
    earlier = doc('gameold1', seconds_ago=900)
    earlier['response'] = dict(at=earlier['queuedAt'], pred=json.loads(json.dumps(V3_PRED)))
    other = doc('gameold2', user='bob', seconds_ago=900)
    other['response'] = dict(at=other['queuedAt'], pred=json.loads(json.dumps(V3_PRED)))
    coll = FakeColl([earlier, other, doc('gameaaaa', speed='blitz')])
    assert run_v3(coll, tmp_path, models) == 1
    # Only the same player's earlier game; the new doc itself is not recomputed.
    assert v3['refresh'] == ['gameold1']
    assert coll.docs['gameold1w']['response']['pred']['rules']['pending'] == []
    assert 'E7' in coll.docs['gameold1w']['response']['pred']['rules']['fired']
    assert coll.docs['gameold1w']['response']['pred']['score'] == V3_PRED['score']
    assert coll.docs['gameold2w']['response']['pred']['rules']['pending'] == ['E7']
    assert coll.docs['gameaaaaw']['response']['pred']['rules']['pending'] == ['E7']
