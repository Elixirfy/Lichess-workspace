"""Loopback-only, server-rendered local annotation app with consent and CSRF."""
import base64
import hashlib
import html
import json
import re
from pathlib import Path
import secrets
import time
from urllib.parse import urlencode

import requests

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from ..data import storage
from ..features.features import valid
from ..labels.labels import CONSENT_VERSION, QUESTIONNAIRE, TILT_ITEM, database, insert_label, pseudonym


def chart(rows, field, title, lower, upper):
    points = []
    total = max((r['ply'] for r in rows), default=1)
    for r in rows:
        value = r.get(field)
        if valid(value):
            x, y = 20 + 460 * r['ply'] / total, 90 - 70 * (max(lower, min(upper, value)) - lower) / (upper - lower)
            points.append(f'{x:.1f},{y:.1f}')
    # Only numeric coordinates enter the trusted SVG; title is escaped separately.
    return Markup(f'<svg viewBox="0 0 500 110" role="img" aria-label="{html.escape(title)}">'
        f'<text x="20" y="14">{html.escape(title)}</text><path d="M20 20V90H480" stroke="#aaa" fill="none"/>'
        f'<polyline points="{" ".join(points)}" stroke="#2471a3" stroke-width="2" fill="none"/>'
        '<text x="430" y="105">ply →</text></svg>')


def create_app(data=storage.DEFAULT_DATA, port=8000):
    data = Path(data)
    with database(data):
        pass
    app = FastAPI(title='Tilt research — local human labels')
    if not 1 <= port <= 65535:
        raise ValueError('Invalid local port')
    redirect_uri = f'http://127.0.0.1:{port}/oauth/callback'
    client_id = 'tilt-research-local'
    # Cookie contains only an opaque random id. In particular, PKCE verifier and
    # OAuth state are server-side, never in Starlette's readable signed cookie.
    sessions = {}

    @app.middleware('http')
    async def server_session(request, call_next):
        now = time.monotonic()
        for key in [key for key, (_, expiry) in sessions.items() if expiry <= now]:
            del sessions[key]
        sid = request.cookies.get('tilt_session')
        if sid not in sessions:
            sid = secrets.token_urlsafe(32)
            sessions[sid] = ({}, now + 8 * 3600)
        request.scope['session'] = sessions[sid][0]
        response = await call_next(request)
        response.set_cookie('tilt_session', sid, httponly=True, samesite='lax', max_age=8 * 3600)
        return response
    templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[3] / 'templates'))

    def page(request, name, **context):
        return templates.TemplateResponse(request=request, name=name,
            context={'request': request, 'csrf': request.session.setdefault('csrf', secrets.token_hex(24)),
                'questionnaire': QUESTIONNAIRE, 'tilt_item': TILT_ITEM, **context})

    def csrf(request, form):
        if not secrets.compare_digest(str(form.get('csrf', '')).encode(), request.session.get('csrf', 'invalid').encode()):
            raise HTTPException(403, 'Invalid form token')

    def imported(user):
        games = storage.read(data, 'games')
        return games[(games.white == user) | (games.black == user)].sort_values('start_ms', ascending=False).head(30)

    def consented_players():
        with database(data) as conn:
            ids = {r[0] for r in conn.execute('SELECT player_id FROM consents WHERE consent_version=?', (CONSENT_VERSION,))}
        games = storage.read(data, 'games')
        return sorted(u for u in set(games.white) | set(games.black)
                      if u and u != '?' and pseudonym(u) in ids)

    @app.get('/', response_class=HTMLResponse)
    def consent(request: Request):
        if not request.session.get('account'):
            return RedirectResponse('/identity', status_code=303)
        if request.session.get('mode') == 'expert':
            return RedirectResponse('/identity', status_code=303)
        return page(request, 'consent.html', version=CONSENT_VERSION, account=request.session['account'])

    @app.post('/consent')
    async def accept(request: Request):
        form = await request.form()
        csrf(request, form)
        account = request.session.get('account')
        if not account or request.session.get('mode') != 'self_report':
            raise HTTPException(403, 'Đăng nhập Lichess trước khi đồng ý tham gia.')
        if form.get('agree') != 'yes':
            raise HTTPException(400, 'Cần sự đồng ý tham gia.')
        with database(data) as conn:
            conn.execute('INSERT OR IGNORE INTO consents VALUES (?,?,?)',
                         (pseudonym(account), CONSENT_VERSION, int(time.time() * 1000)))
        request.session.update(consent=CONSENT_VERSION, user=account)
        return RedirectResponse('/games', status_code=303)

    @app.get('/identity', response_class=HTMLResponse)
    def identity(request: Request):
        expert = request.session.get('account') and request.session.get('mode') == 'expert'
        return page(request, 'identity.html', account=request.session.get('account'),
                    players=consented_players() if expert else None)

    @app.post('/oauth/login')
    async def oauth_login(request: Request):
        form = await request.form()
        csrf(request, form)
        mode = str(form.get('mode', 'self_report'))
        if mode not in ('self_report', 'expert'):
            raise HTTPException(400, 'Vai trò không hợp lệ.')
        verifier = secrets.token_urlsafe(64)
        state = secrets.token_urlsafe(32)
        request.session.clear()
        request.session['oauth'] = dict(verifier=verifier, state=state, mode=mode, expires=time.monotonic() + 600)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        return RedirectResponse('https://lichess.org/oauth?' + urlencode(dict(
            response_type='code', client_id=client_id, redirect_uri=redirect_uri, scope='',
            state=state, code_challenge=challenge, code_challenge_method='S256')), status_code=303)

    @app.get('/oauth/callback')
    def oauth_callback(request: Request):
        pending = request.session.pop('oauth', None)  # single use, including failures
        if (not pending or pending['expires'] < time.monotonic() or
                not secrets.compare_digest(request.query_params.get('state', '').encode(), pending['state'].encode())):
            raise HTTPException(403, 'OAuth state không hợp lệ hoặc hết hạn.')
        code = request.query_params.get('code')
        if not code or request.query_params.get('error'):
            raise HTTPException(400, 'Đăng nhập Lichess bị hủy hoặc thiếu mã.')
        # Do not persist token, response bodies or provider errors in sessions,
        # files, logs or client responses. Revoke even if account lookup fails.
        try:
            with requests.post('https://lichess.org/api/token', data=dict(
                    grant_type='authorization_code', code=code, code_verifier=pending['verifier'],
                    redirect_uri=redirect_uri, client_id=client_id), timeout=20) as response:
                response.raise_for_status()
                token = response.json()['access_token']
            if not isinstance(token, str) or not token:
                raise ValueError('Missing token')
            try:
                with requests.get('https://lichess.org/api/account',
                        headers={'Authorization': f'Bearer {token}'}, timeout=20) as response:
                    response.raise_for_status()
                    account = response.json()['id']
            finally:
                try:
                    with requests.delete('https://lichess.org/api/token',
                            headers={'Authorization': f'Bearer {token}'}, timeout=20) as response:
                        response.raise_for_status()
                finally:
                    token = None
            if not isinstance(account, str) or not re.fullmatch(r'[a-z0-9_-]{2,30}', account):
                raise ValueError('Invalid account')
        except (requests.RequestException, KeyError, ValueError, TypeError):
            raise HTTPException(502, 'Không thể xác minh hoặc thu hồi đăng nhập Lichess.') from None
        request.session.update(account=account, mode=pending['mode'], annotator=pseudonym(account))
        return RedirectResponse('/identity' if pending['mode'] == 'expert' else '/', status_code=303)

    @app.post('/identity')
    async def set_identity(request: Request):
        form = await request.form()
        csrf(request, form)
        if not request.session.get('account') or request.session.get('mode') != 'expert':
            raise HTTPException(403, 'Cần đăng nhập chuyên gia bằng Lichess.')
        user = str(form.get('player', ''))
        if user not in consented_players():
            raise HTTPException(400, 'Chỉ chấm người chơi đã đồng ý tham gia.')
        request.session.update(user=user)
        return RedirectResponse('/games', status_code=303)

    @app.get('/games', response_class=HTMLResponse)
    def games_page(request: Request):
        user = request.session.get('user')
        if not user or not request.session.get('account'):
            return RedirectResponse('/', status_code=303)
        games = storage.records(imported(user))
        moves = storage.read(data, 'moves')
        for game in games:
            own_color = 'white' if game['white'] == user else 'black'
            game['opponent'] = game['black' if own_color == 'white' else 'white']
            rows = storage.records(moves[moves.game_id == game['game_id']].sort_values('ply'))
            max_clock = max([r['clock_seconds'] for r in rows if r['clock_seconds'] is not None] or [1])
            game['eval_chart'] = chart(rows, 'cp', 'Đánh giá: cp, góc nhìn Trắng (giới hạn ±1000)', -1000, 1000)
            game['clock_charts'] = [chart([r for r in rows if r['color'] == c], 'clock_seconds',
                f'Đồng hồ {c}: giây còn lại', 0, max(1, max_clock)) for c in ('white', 'black')]
        path = data / 'processed' / 'features' / 'sessions.parquet'
        sessions = []
        if path.exists():
            import pandas as pd
            frame = pd.read_parquet(path)
            sessions = storage.records(frame[frame.player == user])
        return page(request, 'games.html', games=games, sessions=sessions, user=user,
                    mode=request.session['mode'], saved=request.query_params.get('saved'))

    @app.post('/rate')
    async def rate(request: Request):
        form = await request.form()
        csrf(request, form)
        user = request.session.get('user')
        account = request.session.get('account')
        mode = request.session.get('mode')
        if not user or not account or mode not in ('self_report', 'expert') or (mode == 'self_report' and user != account):
            raise HTTPException(403, 'Verified identity required')
        try:
            scope = str(form['scope'])
            game_id, session_id, end_ms = None, None, None
            low = high = None
            if scope in ('game', 'moment'):
                game_id = str(form['game_id'])
                match = imported(user)
                match = match[match.game_id == game_id]
                if match.empty:
                    raise ValueError('Game does not belong to this player')
                game = storage.records(match)[0]
                end_ms = game['end_ms']
                if scope == 'moment':
                    low, high = int(form['ply_start']), int(form['ply_end'])
                    if not 1 <= low <= high <= game['plies']:
                        raise ValueError('Ply range is outside the game')
            elif scope == 'session':
                import pandas as pd
                frame = pd.read_parquet(data / 'processed' / 'features' / 'sessions.parquet')
                session_id = str(form['session_id'])
                match = frame[(frame.player == user) & (frame.session_id == session_id)]
                if match.empty:
                    raise ValueError('Session does not belong to this player')
                game_ids = json.loads(match.iloc[0].game_ids)
                all_games = storage.read(data, 'games')
                ends = all_games[all_games.game_id.isin(game_ids)].end_ms
                end_ms = int(ends.max()) if ends.notna().all() else None
            else:
                raise ValueError('Unknown scope')
            answers = {key: int(form[key]) for key in QUESTIONNAIRE if form.get(key)}
            with database(data) as conn:
                insert_label(conn, dict(player_id=pseudonym(user), game_id=game_id, session_id=session_id,
                    scope=scope, ply_start=low, ply_end=high, tilt_score=float(form['tilt_score']),
                    questionnaire=answers, source=request.session['mode'],
                    annotator_id=request.session['annotator'], consent_version=CONSENT_VERSION), game_end_ms=end_ms)
        except (ValueError, KeyError, FileNotFoundError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return RedirectResponse('/games?saved=1', status_code=303)

    return app
