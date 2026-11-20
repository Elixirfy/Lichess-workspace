"""Serial public API access and bounded-memory monthly dump ingestion."""
from collections import defaultdict
from contextlib import contextmanager
import csv
import fcntl
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import time
import uuid

import chess.pgn
import requests
import zstandard

from . import storage
from .normalize import api_game, pgn_game

USER_AGENT = 'tilt-research-dataset/0.1'


def usernames(path):
    if not path:
        return set()
    result = set()
    for line in Path(path).read_text().splitlines():
        value = line.split('#', 1)[0].strip().split(',')[0].strip().lower()
        if value and value != 'username':
            if not re.fullmatch(r'[a-z0-9_-]{2,30}', value):
                raise ValueError('Invalid username in list')
            result.add(value)
    return result


@contextmanager
def serial_response(url, data, params=None, token=None):
    """Lock includes the streaming response AND full 60-second 429 cooldown."""
    Path(data).mkdir(parents=True, exist_ok=True)
    (storage.DEFAULT_DATA / 'external').mkdir(parents=True, exist_ok=True)
    with (storage.DEFAULT_DATA / 'external' / 'http.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        headers = {'User-Agent': USER_AGENT, 'Accept': 'application/x-ndjson'}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        while True:
            response = requests.get(url, params=params, headers=headers, stream=True, timeout=(15, 120))
            if response.status_code == 429:
                response.close()
                time.sleep(60)
                continue
            try:
                response.raise_for_status()
                yield response
            finally:
                response.close()
            break


def collect_api(data, users, max_games=50, since=None, until=None, perf=None, backfill=False,
                base_url='https://lichess.org', keep_perf=None):
    """`perf` filters on the server (perfType, which lila answers from its search index). `keep_perf` asks for
    every perf through the Mongo export path and keeps only games of that perf key, in the raw files too: a
    local lila without lila-search answers every perfType export with no games. `max_games` then counts the
    games of every perf."""
    if max_games < 1:
        raise ValueError('max must be positive')
    if perf and keep_perf:
        raise ValueError('perf and keep_perf are exclusive')
    data = Path(data)
    total = 0
    for user in sorted({u.lower() for u in users}):
        if not re.fullmatch(r'[a-z0-9_-]{2,30}', user):
            raise ValueError('Invalid username')
        folder = data / 'raw' / 'api' / user
        folder.mkdir(parents=True, exist_ok=True)
        # Different selection intervals/perfs have separate resume cursors.
        scope_key = [since, until, perf] + ([{'keep_perf': keep_perf}] if keep_perf else [])
        scope = hashlib.sha256(json.dumps(scope_key).encode()).hexdigest()[:12]
        state_path = folder / f'cursor-{scope}.json'
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        # Mongo path uses >= since; perf-filtered search uses strict > since.
        # See GameApiV2.inCreatedAtRange and db.dsl.dateBetween.
        cursor = state.get('created_at')
        oldest = state.get('oldest_created_at', cursor)  # legacy cursor: safely re-fetch overlap
        resume_lower = cursor + (0 if perf else 1) if cursor is not None and not backfill else 0
        lower = max(x for x in (since, resume_lower, 0) if x is not None)
        params = dict(clocks='true', evals='true', accuracy='true', opening='true',
            division='true', moves='true', finished='true', ongoing='false',
            max=max_games, sort='dateDesc' if backfill or cursor is None else 'dateAsc')
        if lower:
            params['since'] = lower
        upper = min(until, oldest) if backfill and oldest is not None and until is not None else oldest if backfill and oldest is not None else until
        if upper is not None:
            # until is EXCLUSIVE on both paths. Game.scala export config passes
            # until to GameApiV2: Mongo Query.createdBetween -> db.dsl.dateBetween
            # uses .lt(until); GameApiV2.inCreatedAtRange uses isBefore(until).
            # Therefore use oldest unchanged, never oldest-1 (which loses 1 ms).
            params['until'] = upper
        if perf:
            params['perfType'] = perf
        observed = int(time.time() * 1000)
        raw_path = folder / f'{observed}-{uuid.uuid4().hex[:8]}.ndjson.gz'
        games, moves, newest = [], [], state.get('created_at')
        seen = 0
        with serial_response(f"{base_url.rstrip('/')}/api/games/user/{user}", data, params,
                             os.environ.get('LICHESS_TOKEN')) as response:
            # iter_content preserves NDJSON bytes/newlines (HTTP transport decoding only).
            pending = b''
            with gzip.open(raw_path, 'wb') as raw:
                for chunk in response.iter_content(chunk_size=65536):
                    if not keep_perf:
                        raw.write(chunk)
                    pending += chunk
                    while b'\n' in pending:
                        line, pending = pending.split(b'\n', 1)
                        if not line.strip():
                            continue
                        obj = json.loads(line)
                        seen += 1
                        newest = max(newest, obj['createdAt']) if newest is not None else obj['createdAt']
                        oldest = min(oldest, obj['createdAt']) if oldest is not None else obj['createdAt']
                        if keep_perf:
                            if obj.get('perf') != keep_perf:
                                continue
                            raw.write(line + b'\n')
                        if obj.get('variant', 'standard') != 'standard':
                            continue
                        game, rows = api_game(obj, observed_ms=int(time.time() * 1000))
                        games.append(game)
                        moves.extend(rows)
                        if len(games) >= 100:
                            total += storage.append(data, games, moves)
                            games, moves = [], []
                if pending.strip():
                    obj = json.loads(pending)
                    seen += 1
                    newest = max(newest, obj['createdAt']) if newest is not None else obj['createdAt']
                    oldest = min(oldest, obj['createdAt']) if oldest is not None else obj['createdAt']
                    kept = not keep_perf or obj.get('perf') == keep_perf
                    if keep_perf and kept:
                        raw.write(pending + b'\n')
                    if kept and obj.get('variant', 'standard') == 'standard':
                        game, rows = api_game(obj, observed_ms=int(time.time() * 1000))
                        games.append(game)
                        moves.extend(rows)
        total += storage.append(data, games, moves)
        temp = state_path.with_suffix('.tmp')
        temp.write_text(json.dumps({'created_at': newest, 'oldest_created_at': oldest,
                                    'older_exhausted': backfill and not seen, 'params': params}, indent=2))
        temp.replace(state_path)
        if backfill and not seen:
            print(f'No older games remain for {user} in the selected interval/perf filters.', file=sys.stderr)
    return total


def normalize_api(data):
    """Recover completed raw lines after an interrupted request; never advance a cursor."""
    games, moves, count = [], [], 0
    for file in sorted((Path(data) / 'raw' / 'api').glob('*/*.ndjson.gz')):
        try:
            with gzip.open(file, 'rb') as handle:
                for line in handle:
                    try:
                        raw = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if raw.get('variant', 'standard') != 'standard':
                        continue
                    game, rows = api_game(raw, observed_ms=int(file.stat().st_mtime * 1000))
                    games.append(game)
                    moves.extend(rows)
                    if len(games) >= 100:
                        count += storage.append(data, games, moves)
                        games, moves = [], []
        except (EOFError, gzip.BadGzipFile):
            pass
    return count + storage.append(data, games, moves)


@contextmanager
def dump_stream(source, data):
    """No decompressed dump is written to disk, including for remote URLs."""
    if source.startswith(('https://', 'http://')):
        if not re.fullmatch(r'https://database\.lichess\.org/standard/lichess_db_standard_rated_\d{4}-\d{2}\.pgn\.zst', source):
            raise ValueError('Expected a standard rated monthly URL on database.lichess.org')
        with serial_response(source, data) as response:
            with zstandard.ZstdDecompressor().stream_reader(response.raw) as reader:
                with io.TextIOWrapper(reader, encoding='utf-8') as text:
                    yield text
    else:
        with Path(source).open('rb') as raw:
            if source.endswith('.zst'):
                with zstandard.ZstdDecompressor().stream_reader(raw) as reader:
                    with io.TextIOWrapper(reader, encoding='utf-8') as text:
                        yield text
            else:
                with io.TextIOWrapper(raw, encoding='utf-8') as text:
                    yield text


@contextmanager
def staged_dump(data, source, users=None, speeds=None, limit=None, since=None, until=None, headers_only=False, max_staging_gb=5):
    """Disk-backed spool permits an exact min-games filter without holding games in RAM."""
    folder = Path(data) / 'external' / 'staging'
    folder.mkdir(parents=True, exist_ok=True)
    if not math.isfinite(max_staging_gb) or max_staging_gb <= 0:
        raise ValueError('max-staging-gb must be positive and finite')
    budget = int(max_staging_gb * 1024**3)
    if shutil.disk_usage(folder).free < budget:
        raise ValueError('Insufficient free disk space for max-staging-gb')
    path = folder / f'{uuid.uuid4().hex}.sqlite'
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE candidates (id TEXT PRIMARY KEY, white TEXT, black TEXT, payload TEXT)')
    conn.execute('CREATE TABLE players (username TEXT, speed TEXT, rating REAL, game_id TEXT, PRIMARY KEY(username,game_id))')
    def check_size():
        # page_count includes dirty SQLite pages still in its cache; include
        # rollback/WAL files as well so uncommitted writes cannot evade the cap.
        logical = conn.execute('PRAGMA page_count').fetchone()[0] * conn.execute('PRAGMA page_size').fetchone()[0]
        sidecars = sum(p.stat().st_size for p in folder.glob(path.name + '*') if p != path)
        physical = path.stat().st_size
        if max(logical, physical) + sidecars > budget:
            raise ValueError('Staging exceeded max-staging-gb; temporary spool deleted')

    count = skipped = 0
    try:
        check_size()
        with dump_stream(source, data) as handle:
            while limit is None or count < limit:
                parsed = chess.pgn.read_headers(handle) if headers_only else chess.pgn.read_game(handle)
                if parsed is None:
                    break
                pgn = chess.pgn.Game(parsed) if headers_only else parsed
                try:
                    game, moves = pgn_game(pgn)
                except ValueError:
                    skipped += 1
                    continue
                if speeds and game['speed'] not in speeds:
                    continue
                if users and not ({game['white'], game['black']} & users):
                    continue
                if (since is not None and (game['start_ms'] is None or game['start_ms'] < since)) or (
                    until is not None and (game['start_ms'] is None or game['start_ms'] > until)):
                    continue
                changed = conn.execute('INSERT OR IGNORE INTO candidates VALUES (?,?,?,?)',
                    (game['game_id'], game['white'], game['black'], json.dumps([game, moves]))).rowcount
                if not changed:
                    continue
                for color in ('white', 'black'):
                    if game[color] != '?':
                        conn.execute('INSERT OR IGNORE INTO players VALUES (?,?,?,?)',
                            (game[color], game['speed'], game[f'{color}_rating'], game['game_id']))
                count += 1
                check_size()
                if count % 1000 == 0:
                    conn.commit()
        conn.commit()
        conn.execute('CREATE INDEX player_name ON players(username)')
        check_size()
        yield conn, {'candidates': count, 'skipped_invalid_or_variant': skipped}
    finally:
        conn.close()
        for file in folder.glob(path.name + '*'):
            file.unlink(missing_ok=True)


def collect_dump(data, source, users=None, speeds=None, min_games=1, limit=None, since=None, until=None, max_staging_gb=5):
    if min_games < 1 or (limit is not None and limit < 1):
        raise ValueError('min-games and limit must be positive')
    if not users and limit is None:
        raise ValueError('collect-dump requires --users / --users-file or --limit')
    with staged_dump(data, source, users, speeds, limit, since, until, max_staging_gb=max_staging_gb) as (conn, stats):
        conn.execute('CREATE TEMP TABLE eligible AS SELECT username FROM players GROUP BY username HAVING COUNT(*) >= ?', (min_games,))
        conn.execute('CREATE UNIQUE INDEX eligible_name ON eligible(username)')
        target_users = ({u for u in users if conn.execute('SELECT 1 FROM eligible WHERE username=?', (u,)).fetchone()} if users else None)
        query = '''SELECT payload FROM candidates c WHERE EXISTS
            (SELECT 1 FROM eligible e WHERE e.username=c.white OR e.username=c.black) ORDER BY id'''
        games, moves, count = [], [], 0
        for (payload,) in conn.execute(query):
            game, rows = json.loads(payload)
            if target_users is not None and not ({game['white'], game['black']} & target_users):
                continue
            games.append(game)
            moves.extend(rows)
            if len(games) >= 100:
                count += storage.append(data, games, moves)
                games, moves = [], []
        stats['imported'] = count + storage.append(data, games, moves)
        return stats


def sample_players(data, source, output, min_games=20, per_stratum=10, band_width=200,
                   seed=42, speeds=None, limit=None, since=None, until=None, max_staging_gb=5):
    if min_games < 1 or per_stratum < 1 or band_width < 1 or (limit is not None and limit < 1):
        raise ValueError('Sampling parameters must be positive')
    strata = defaultdict(list)
    with staged_dump(data, source, speeds=speeds, limit=limit, since=since, until=until, headers_only=True, max_staging_gb=max_staging_gb) as (conn, stats):
        for user, spd, rating, count in conn.execute('''SELECT username,speed,AVG(rating),COUNT(*)
                FROM players GROUP BY username,speed HAVING COUNT(*)>=? AND AVG(rating) IS NOT NULL''', (min_games,)):
            band = int(rating // band_width) * band_width
            key = hashlib.sha256(f'{seed}:{user}:{spd}'.encode()).hexdigest()
            bucket = strata[(band, spd)]
            bucket.append((key, user, spd, band, round(rating, 1), count))
            bucket.sort()
            del bucket[per_stratum:]
    rows = [r[1:] for key in sorted(strata) for r in strata[key]]
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('w') as handle:
        writer = csv.writer(handle)
        writer.writerow(['username', 'speed', 'rating_band', 'mean_rating', 'games'])
        writer.writerows(rows)
    return {'strata': len(strata), 'sampled_player_contexts': len(rows), **stats}
