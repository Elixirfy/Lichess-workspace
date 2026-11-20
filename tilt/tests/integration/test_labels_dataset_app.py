import json
import re
import sqlite3

from fastapi.testclient import TestClient
import pandas as pd
import pytest

from tilt.api.app import create_app
from tilt.data.dataset import build_dataset, _split_player
from tilt.features.features import compute
from tilt.labels.labels import (CONSENT_VERSION, database, insert_label, pseudonym, private_id)


def human_label(conn, user, game_id=None, session_id=None, scope='game', low=None, high=None, score=7, source='self_report'):
    pid = pseudonym(user)
    conn.execute('INSERT OR IGNORE INTO consents VALUES (?,?,?)', (pid, CONSENT_VERSION, 1))
    return insert_label(conn, dict(player_id=pid, game_id=game_id, session_id=session_id,
        scope=scope, ply_start=low, ply_end=high, tilt_score=score,
        questionnaire={'frustration': 4, 'focus': 2}, source=source,
        annotator_id='human-annotator-01', consent_version=CONSENT_VERSION), game_end_ms=160000, report_ms=2000000)


def test_schema_constraints_consent_questionnaire_and_salt(tmp_path, monkeypatch):
    with database(tmp_path) as conn:
        label_id = human_label(conn,'alice','game0001')
        label = dict(conn.execute('SELECT * FROM labels WHERE label_id=?', (label_id,)).fetchone())
        assert label['player_id'] == pseudonym('ALICE')
        assert label['delay_seconds'] == 1840
        assert label['source'] == 'self_report'
        assert label['tilt_score'] == 7
        with pytest.raises(ValueError):
            human_label(conn,'alice','game0001',score=11)
        with pytest.raises(sqlite3.IntegrityError):
            human_label(conn,'alice','game0001',scope='moment')
    monkeypatch.setenv('TILT_SALT','a-different-private-test-salt')
    with pytest.raises(ValueError, match='differs'):
        database(tmp_path)


def test_only_human_labels_are_output_and_empty_case(corpus):
    data, add = corpus
    add(1,error=True)
    result = build_dataset(data)
    assert result['examples'] == 0  # A serious chess error cannot manufacture a tilt label.
    assert pd.read_parquet(data/'processed/out/labelled.parquet').empty
    assert (data/'processed/out/DATACARD.md').exists()
    with database(data) as conn:
        human_label(conn,'alice','game0001',score=0)
    result = build_dataset(data)
    assert result['examples'] == 1
    df = pd.read_parquet(data/'processed/out/labelled.parquet')
    assert df.target_tilt.tolist() == [0]
    assert df.player_id.iloc[0] == pseudonym('alice')
    assert not any('questionnaire' in c or 'frustration' in c for c in df)
    assert 'alice' not in df.to_json() and 'human-annotator-01' not in df.to_json()
    manifest = json.loads((data/'processed/out/manifest.json').read_text())
    assert 'target_tilt' not in manifest['predictor_columns']
    assert 'label_id' not in manifest['predictor_columns']


def test_moment_join_cannot_see_moves_after_the_range_and_session_join(corpus):
    data, add = corpus
    add(1)
    add(2)
    compute(data,min_prior_games=1)
    games = pd.read_parquet(data/'processed/features/games.parquet')
    sid = games[games.player=='alice'].iloc[0].session_id
    with database(data) as conn:
        human_label(conn,'alice','game0001',scope='moment',low=1,high=3,score=4)
        human_label(conn,'alice',session_id=sid,scope='session',score=5)
        human_label(conn,'alice','notfound',score=9)
    result = build_dataset(data)
    assert result['examples'] == 2 and result['unmatched_labels'] == 1
    frame = pd.read_parquet(data/'processed/out/labelled.parquet')
    moment = frame[frame.scope=='moment'].iloc[0]
    moves = pd.read_parquet(data/'processed/features/moves.parquet')
    expected = moves[(moves.player=='alice') & (moves.game_id=='game0001') & (moves.ply<=3)].cpl.mean()
    assert moment.mean_cpl == expected
    assert 'result_score' not in frame
    assert not any(c.startswith('post_event') for c in frame)
    assert frame[frame.scope=='session'].iloc[0].game_count == 2


def test_player_split_disjoint_and_shared_games_purged(corpus):
    data, add = corpus
    target = next(f'u{i}' for i in range(100) if _split_player(pseudonym(f'u{i}')) == 'test')
    train = next(f'u{i}' for i in range(100) if _split_player(pseudonym(f'u{i}')) == 'train')
    # The helper targets Alice; use her opponent with the desired bucket.
    game = add(1,opponent=target)
    with database(data) as conn:
        human_label(conn,'alice',game['game_id'])
        human_label(conn,target,game['game_id'])
    build_dataset(data)
    frame = pd.read_parquet(data/'processed/out/by_player.parquet')
    for partition in ('train','validation','test'):
        ids = set(frame[frame.split==partition].player_id)
        for other in ('train','validation','test'):
            if other != partition:
                assert ids.isdisjoint(frame[frame.split==other].player_id)
    if _split_player(pseudonym('alice')) != 'test':
        assert frame[frame.player_id==pseudonym('alice')].iloc[0].split == 'purged_shared_game'


def test_time_split_purges_crossing_games_and_stays_chronological(corpus):
    data, add = corpus
    for i,(start,end) in enumerate(((100000,160000),(200000,280000),(300000,360000),(400000,460000)),1):
        add(i,start=start,end=end)
    with database(data) as conn:
        for i in range(1,5):
            human_label(conn,'alice',f'game{i:04d}')
    build_dataset(data,time_validation_ms=250000,time_test_ms=390000)
    frame = pd.read_parquet(data/'processed/out/by_time.parquet').set_index('game_id')
    assert frame.loc[private_id('game:game0001'),'split'] == 'train'
    assert frame.loc[private_id('game:game0002'),'split'] == 'purged_crossing_cutoff'
    assert frame.loc[private_id('game:game0003'),'split'] == 'validation'
    assert frame.loc[private_id('game:game0004'),'split'] == 'test'
    assert frame[frame.split=='train'].end_upper_ms.max() < frame[frame.split=='validation'].start_ms.min()


def csrf(html):
    return re.search(r'name="csrf" value="([^"]+)"',html)[1]


def login(client, user, mode='self_report', annotator=''):
    from urllib.parse import parse_qs, urlparse
    token = csrf(client.get('/identity').text)
    response = client.post('/oauth/login', data={'csrf': token, 'mode': mode}, follow_redirects=False)
    query = parse_qs(urlparse(response.headers['location']).query)
    response = client.get('/oauth/callback', params={'code': user, 'state': query['state'][0]})
    token = csrf(response.text)
    if mode == 'self_report':
        response = client.post('/consent', data={'csrf': token, 'agree': 'yes', 'username': 'ignored-forged-user'})
    else:
        response = client.post('/identity', data={'csrf': token, 'player': 'alice', 'annotator': annotator})
    return token, response


def test_app_consent_self_report_game_moment_session_and_expert(corpus, oauth_mock):
    data,add = corpus
    add(1)
    compute(data,min_prior_games=1)
    client = TestClient(create_app(data))
    assert client.post('/consent',data={'agree':'yes'}).status_code == 403
    token,response = login(client,'alice')
    assert response.status_code == 200 and '<svg' in response.text
    assert 'Bản nháp' in response.text
    common = {'csrf':token,'game_id':'game0001','tilt_score':'6','frustration':'4'}
    assert client.post('/rate',data={**common,'scope':'game'}).status_code == 200
    assert client.post('/rate',data={**common,'scope':'moment','ply_start':'3','ply_end':'5'}).status_code == 200
    assert client.post('/rate',data={**common,'scope':'moment','ply_start':'3','ply_end':'999'}).status_code == 400
    sid = pd.read_parquet(data/'processed/features/sessions.parquet').query("player=='alice'").iloc[0].session_id
    assert client.post('/rate',data={'csrf':token,'scope':'session','session_id':sid,'tilt_score':'3'}).status_code == 200
    assert client.post('/rate',data={**common,'scope':'game','game_id':'someoneelse'}).status_code == 400
    token,response = login(client,'expert-owner',mode='expert',annotator='forged-annotator')
    assert response.status_code == 200
    assert client.post('/rate',data={**common,'csrf':token,'scope':'game'}).status_code == 200
    with database(data) as conn:
        rows = conn.execute('SELECT * FROM labels ORDER BY label_id').fetchall()
        assert len(rows) == 4
        assert {r['scope'] for r in rows} == {'game','moment','session'}
        assert rows[-1]['source'] == 'expert'
        assert rows[-1]['annotator_id'] == pseudonym('expert-owner')
        assert all(r['player_id']==pseudonym('alice') for r in rows)


def test_session_report_does_not_absorb_later_games(corpus):
    data,add=corpus
    add(1,start=100000,end=300000)
    compute(data,min_prior_games=1)
    sid=pd.read_parquet(data/'processed/features/sessions.parquet').query("player=='alice'").iloc[0].session_id
    with database(data) as conn:
        human_label(conn,'alice',session_id=sid,scope='session')  # report_ms=2,000,000
    build_dataset(data)
    before=pd.read_parquet(data/'processed/out/labelled.parquet')
    assert before.iloc[0].game_count==1
    # 31 seconds after report, but less than 29 minutes after the old game ended: same session.
    add(2,start=2031000,end=2091000,error=True)
    build_dataset(data)
    after=pd.read_parquet(data/'processed/out/labelled.parquet')
    assert after.iloc[0].game_count==1
    assert after.iloc[0].mean_cpl==before.iloc[0].mean_cpl


def oauth_start(client, mode='self_report'):
    from urllib.parse import parse_qs, urlparse
    response = client.post('/oauth/login', data={'csrf': csrf(client.get('/identity').text), 'mode': mode}, follow_redirects=False)
    assert response.status_code == 303
    url = urlparse(response.headers['location'])
    assert (url.scheme, url.netloc, url.path) == ('https', 'lichess.org', '/oauth')
    return parse_qs(url.query, keep_blank_values=True)


def test_oauth_pkce_server_side_state_single_use_and_no_secret_persistence(corpus, oauth_mock, caplog):
    import base64
    import hashlib
    data, add = corpus
    add(1)
    client = TestClient(create_app(data, port=8765))
    assert 'name="username"' not in client.get('/identity').text
    query = oauth_start(client)
    assert query['redirect_uri'] == ['http://127.0.0.1:8765/oauth/callback']
    assert query['client_id'] == ['tilt-research-local'] and query['scope'] == ['']
    assert query['response_type'] == ['code'] and query['code_challenge_method'] == ['S256']
    cookie = client.cookies.get('tilt_session')
    assert query['state'][0] not in cookie
    assert client.get('/oauth/callback', params={'state': 'forged', 'code': 'alice'}).status_code == 403
    assert not oauth_mock
    assert client.get('/oauth/callback', params={'state': query['state'][0], 'code': 'alice'}).status_code == 403
    query = oauth_start(client)
    callback = client.get('/oauth/callback', params={'state': query['state'][0], 'code': 'alice'})
    assert callback.status_code == 200
    assert [c[0] for c in oauth_mock] == ['token', 'account', 'revoke']
    posted = oauth_mock[0][1]['data']
    assert posted['grant_type'] == 'authorization_code'
    assert posted['redirect_uri'] == query['redirect_uri'][0]
    assert posted['client_id'] == query['client_id'][0] and 'client_secret' not in posted
    verifier = posted['code_verifier']
    assert 43 <= len(verifier) <= 128 and verifier not in cookie
    assert base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode() == query['code_challenge'][0]
    assert oauth_mock[1][1]['headers'] == oauth_mock[2][1]['headers']
    assert client.get('/oauth/callback', params={'state': query['state'][0], 'code': 'alice'}).status_code == 403
    # Forged identity fields cannot grant Bob's consent or create a self-report.
    token = csrf(client.get('/').text)
    assert client.post('/identity', data={'csrf': token, 'username': 'bob', 'mode': 'self_report'}).status_code == 403
    assert client.post('/consent', data={'csrf': token, 'agree': 'yes', 'username': 'bob'}).status_code == 200
    with database(data) as conn:
        assert [r[0] for r in conn.execute('SELECT player_id FROM consents')] == [pseudonym('alice')]
    secrets_to_check = [verifier, 'never-persist-this-token-alice']
    content = callback.text + repr(dict(client.cookies)) + caplog.text
    for file in data.rglob('*'):
        if file.is_file():
            content += file.read_bytes().decode(errors='ignore')
    assert all(secret not in content for secret in secrets_to_check)


@pytest.mark.parametrize('failure', ['account', 'revoke'])
def test_oauth_failure_revokes_and_never_authenticates(corpus, oauth_mock, monkeypatch, failure):
    import requests
    data, add = corpus
    add(1)
    client = TestClient(create_app(data))
    query = oauth_start(client)
    def fail(*a, **kw):
        oauth_mock.append((failure + '_failed', kw))
        raise requests.RequestException('provider error containing never-persist-this-token-alice')
    monkeypatch.setattr(requests, 'get' if failure == 'account' else 'delete', fail)
    response = client.get('/oauth/callback', params={'state': query['state'][0], 'code': 'alice'})
    assert response.status_code == 502
    assert any(c[0].startswith('revoke') for c in oauth_mock)
    assert 'never-persist' not in response.text
    token = csrf(client.get('/identity').text)
    assert client.post('/consent', data={'csrf': token, 'agree': 'yes'}).status_code == 403
    assert client.post('/rate', data={'csrf': token, 'scope': 'game', 'game_id': 'game0001', 'tilt_score': 6}).status_code == 403


def test_oauth_requires_state_session_code_and_accepts_denial_safely(corpus, oauth_mock):
    data, _ = corpus
    client = TestClient(create_app(data))
    query = oauth_start(client)
    other = TestClient(create_app(data))
    assert other.get('/oauth/callback', params={'state': query['state'][0], 'code': 'alice'}).status_code == 403
    assert client.get('/oauth/callback', params={'state': query['state'][0], 'error': 'access_denied'}).status_code == 400
    query = oauth_start(client)
    assert client.get('/oauth/callback', params={'code': 'alice'}).status_code == 403
    assert not oauth_mock


def test_expert_selects_only_consented_players_and_uses_verified_annotator(corpus, oauth_mock):
    data, add = corpus
    add(1)
    with database(data) as conn:
        conn.execute('INSERT INTO consents VALUES (?,?,?)', (pseudonym('alice'), 'draft-research-v1', 1))
    expert = TestClient(create_app(data))
    token, response = login(expert, 'verified-expert', mode='expert')
    assert response.status_code == 400  # legacy unverified consent is insufficient
    token = csrf(expert.get('/identity').text)
    assert expert.post('/consent', data={'csrf': token, 'agree': 'yes'}).status_code == 403
    for user in ('alice', 'bob'):
        participant = TestClient(create_app(data))
        assert login(participant, user)[1].status_code == 200
    page = expert.get('/identity')
    assert '<option value="alice">' in page.text and '<option value="bob">' in page.text
    assert 'verified-expert</option>' not in page.text
    token = csrf(page.text)
    assert expert.post('/identity', data={'csrf': token, 'player': 'unconsented'}).status_code == 400
    for user in ('alice', 'bob'):
        assert expert.post('/identity', data={'csrf': token, 'player': user, 'annotator': 'forged'}).status_code == 200
        assert expert.post('/rate', data={'csrf': token, 'scope': 'game', 'game_id': 'game0001', 'tilt_score': 5}).status_code == 200
    # Consent is rechecked at submission, not just when choosing the target.
    with database(data) as conn:
        conn.execute('DELETE FROM consents WHERE player_id=?', (pseudonym('bob'),))
    assert expert.post('/rate', data={'csrf': token, 'scope': 'game', 'game_id': 'game0001', 'tilt_score': 5}).status_code == 400
    with database(data) as conn:
        rows = conn.execute('SELECT player_id,annotator_id FROM labels').fetchall()
        assert {r[0] for r in rows} == {pseudonym('alice'), pseudonym('bob')}
        assert {r[1] for r in rows} == {pseudonym('verified-expert')}


def test_legacy_salt_fingerprint_migrates_without_losing_labels(tmp_path, monkeypatch):
    import hashlib
    import hmac
    import os
    with database(tmp_path) as conn:
        human_label(conn, 'alice', 'game0001')
        legacy = hashlib.sha256(os.environ['TILT_SALT'].encode()).hexdigest()
        conn.execute("UPDATE metadata SET value=? WHERE key='salt_fingerprint'", (legacy,))
    expected = hmac.new(os.environ['TILT_SALT'].encode(), b'tilt-salt-fingerprint-v1', hashlib.sha256).hexdigest()
    with database(tmp_path) as conn:
        assert conn.execute("SELECT value FROM metadata WHERE key='salt_fingerprint'").fetchone()[0] == expected != legacy
        assert conn.execute('SELECT count(*) FROM labels').fetchone()[0] == 1
    monkeypatch.setenv('TILT_SALT', 'different-stable-test-salt')
    with pytest.raises(ValueError, match='differs'):
        database(tmp_path)


def test_every_export_file_excludes_raw_user_game_and_session_ids(corpus):
    data, add = corpus
    for i in range(1, 4):
        add(i)
    compute(data, max_history_games=2, min_prior_games=1)
    feature_games = pd.read_parquet(data / 'processed/features/games.parquet')
    raw_sessions = set(feature_games.session_id)
    sid = feature_games[feature_games.player == 'alice'].iloc[0].session_id
    with database(data) as conn:
        human_label(conn, 'alice', 'game0001')
        human_label(conn, 'alice', 'game0002', scope='moment', low=1, high=3)
        human_label(conn, 'alice', session_id=sid, scope='session')
    build_dataset(data)
    forbidden = {'alice', 'bob', 'human-annotator-01', 'game0001', 'game0002', 'game0003'} | raw_sessions
    files = list((data / 'processed' / 'out').rglob('*'))
    assert len(files) == 5
    for file in files:
        payload = file.read_bytes().decode(errors='ignore')
        if file.suffix == '.parquet':
            frame = pd.read_parquet(file)
            payload += frame.to_json()
            assert not {'previous_game_id', 'opponent', 'opponent_id', 'game_ids'} & set(frame)
        assert not any(raw in payload for raw in forbidden), file
    frame = pd.read_parquet(data / 'processed/out/labelled.parquet')
    assert frame[frame.scope == 'game'].iloc[0].game_id == private_id('game:game0001')
    assert set(frame.session_id) == {private_id('session:' + sid)}
    assert json.loads((data / 'processed/out/manifest.json').read_text())['features']['max_history_games'] == 2
    assert '2 most recent' in (data / 'processed/out/DATACARD.md').read_text()


def test_session_baseline_uses_cap_before_session_began(corpus):
    data, add = corpus
    for i in range(1, 4):
        add(i, error=(i != 1))
    add(4, start=2500000, end=2560000)
    compute(data, max_history_games=2, min_prior_games=1)
    feature_games = pd.read_parquet(data / 'processed/features/games.parquet')
    last = feature_games[(feature_games.player == 'alice') & (feature_games.game_id == 'game0004')].iloc[0]
    with database(data) as conn:
        pid = pseudonym('alice')
        conn.execute('INSERT INTO consents VALUES (?,?,?)', (pid, CONSENT_VERSION, 1))
        insert_label(conn, dict(player_id=pid, session_id=last.session_id, scope='session', tilt_score=4,
                                source='self_report', annotator_id=pid, consent_version=CONSENT_VERSION), report_ms=3000000)
    build_dataset(data)
    session = pd.read_parquet(data / 'processed/out/labelled.parquet').iloc[0]
    assert session.baseline_mean_cpl_games == 2
    recent = feature_games[(feature_games.player == 'alice') & feature_games.game_id.isin(['game0002', 'game0003'])]
    assert session.baseline_mean_cpl_median == recent.mean_cpl.median()


def test_oauth_state_expires_before_token_exchange(corpus, oauth_mock, monkeypatch):
    import time
    data, _ = corpus
    client = TestClient(create_app(data))
    query = oauth_start(client)
    monotonic = time.monotonic
    monkeypatch.setattr('tilt.api.app.time.monotonic', lambda: monotonic() + 601)
    assert client.get('/oauth/callback', params={'state': query['state'][0], 'code': 'alice'}).status_code == 403
    assert not oauth_mock


def test_non_ascii_forged_oauth_state_is_rejected(corpus, oauth_mock):
    data, _ = corpus
    client = TestClient(create_app(data))
    oauth_start(client)
    assert client.get('/oauth/callback', params={'state': 'giả-mạo', 'code': 'alice'}).status_code == 403
    assert not oauth_mock
