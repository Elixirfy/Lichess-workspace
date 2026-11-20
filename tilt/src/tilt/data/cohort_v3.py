"""Locked S2 data-only workflow. No labels, fitting, or automatic engine execution.

Private artifacts live in --out; only the operator invokes network steps. Sampling
uses collect.staged_dump (including its definition of limit) and exactly the
sample_players ordering sha256('43:<lower username>:blitz'), then username.
"""
import argparse
import bisect
from contextlib import closing, contextmanager
import hashlib
import heapq
import hmac
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3

import pandas as pd
import requests

from . import collect, storage

SOURCE = 'https://database.lichess.org/standard/lichess_db_standard_rated_2026-10.pgn.zst'
BANDS = tuple(range(400, 3000, 200))
UNTIL = 1794787200000  # 2026-11-16T00:00:00Z, exclusive as in collect_api
LOCK = '0d59ce9d79e6e9e9e9992e5116b83e39440eacfc1f3a53b83772030d8b2a0b06'
KEY = 'ca2f1c3ac567a14c1b85bd95c43f5aa1bd29f565a42e9cd932db274ca91239ae'
BINARY = '00628bd9c9855c1b7ff93d7f8d51b413586cdc6336fe637f9a14a61531a05aca'
PUBLIC = 'label-v3-holdout-1:'
OUT = Path.home() / 'tilt-labels-v3/S2'
EXCLUDE = Path.home() / 'tilt-users-all.txt'
CANDIDATE_COLUMNS = ['band', 'rank', 'role', 'username']


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    tmp.replace(path)


def read_json(path):
    return json.loads(Path(path).read_text())


def write_csv(path, frame):
    path = Path(path)
    tmp = path.with_suffix('.tmp')
    frame.to_csv(tmp, index=False)
    tmp.replace(path)


def readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)


def read_normalized(data, name):
    """Respect committed batches without storage.read's DDL on the old root."""
    folder = Path(data) / 'processed'
    with closing(readonly(folder / 'index.sqlite')) as conn:
        batches = {r[0] for r in conn.execute('SELECT batch FROM batches')}
    files = [p for p in sorted((folder / 'normalized' / name).glob('*.parquet')) if p.stem in batches]
    schema = storage.GAME_SCHEMA if name == 'games' else storage.MOVE_SCHEMA
    return pd.read_parquet(files) if files else pd.DataFrame(columns=schema.names)


def check_lock():
    path = Path(__file__).resolve().parents[3] / 'reports/label_v3_preregistration.md'
    # S2 ended immediately before Addendum S3. Later append-only stages must
    # preserve these exact bytes, rather than rewrite S2's lock each stage.
    current = path.read_bytes()
    prefix = current.split(b'\n\n## Addendum S3', 1)[0] + b'\n'
    if hashlib.sha256(prefix).hexdigest() != LOCK:
        raise ValueError('Pre-registration lock mismatch')


def baseline(out, old):
    path = Path(out) / 'baseline.json'
    manifest = Path(old) / 'processed/features/manifest.json'
    if not path.exists():
        write_json(path, {'features_manifest_sha256': sha(manifest), 'prereg_sha256': LOCK})
    return read_json(path)


def pick_candidates(rows, excluded, bands=BANDS):
    strata = {band: [] for band in bands}
    for user, speed, rating, count in rows:
        user = user.lower()
        band = int(rating // 200) * 200
        if speed == 'blitz' and count >= 12 and band in strata and user not in excluded:
            bisect.insort(strata[band], (digest(f'43:{user}:blitz'), user))
            del strata[band][30:]
    result = []
    for band in sorted(strata):
        for rank, (_, user) in enumerate(sorted(set(strata[band]))[:30], 1):
            result.append((band, rank, 'primary' if rank <= 16 else 'reserve', user))
    return pd.DataFrame(result, columns=CANDIDATE_COLUMNS)


def sample(data, out, exclude, old, bands=None):
    out = Path(out)
    if (out / 'holdout_manifest.parquet').exists():
        raise ValueError('Assignment is frozen')
    resample = bands is not None
    selected = tuple(sorted(set(bands))) if resample else BANDS
    if not selected or set(selected) - set(BANDS):
        raise ValueError('Bands must be lower edges in 400..2800')
    target = out / 'candidates.csv'
    if resample:
        if (out / 'sample_resample.json').exists():
            raise ValueError('Only one enlarged re-sample is allowed')
        cohort = pd.read_csv(out / 'cohort.csv')
        if len(cohort) >= 170 or any((cohort.band == b).sum() >= 16 for b in selected):
            raise ValueError('Re-sample requires fewer than 170 players and only short bands')
        previous = pd.read_csv(target)
    elif target.exists():
        raise ValueError('Initial sample already exists')
    before = baseline(out, old)
    limit = 2400000 if resample else 1200000
    excluded = collect.usernames(exclude)
    if len(excluded) != 196:
        raise ValueError('Expected 196 unique excluded accounts')
    if resample:
        excluded |= set(previous.loc[~previous.band.isin(selected), 'username'])
    # No normalized dump data is retained; the temporary header spool is deleted.
    with collect.staged_dump(out, SOURCE, speeds={'blitz'}, limit=limit,
                             headers_only=True, max_staging_gb=5) as (conn, stats):
        rows = conn.execute('''SELECT username,speed,AVG(rating),COUNT(*) FROM players
            GROUP BY username,speed HAVING COUNT(*)>=12 AND AVG(rating) IS NOT NULL ORDER BY username,speed''')
        header_hash = hashlib.sha256()
        def hashed_input():
            for row in rows:
                header_hash.update((json.dumps(row, separators=(',', ':')) + '\n').encode())
                yield row
        candidates = pick_candidates(hashed_input(), excluded, selected)
    if resample:
        # Names assigned to untouched bands cannot be re-used in a short band.
        retained = previous[~previous.band.isin(selected)]
        candidates = candidates[~candidates.username.isin(retained.username)].copy()
        # Refill ranks after removing cross-window duplicate accounts.
        candidates['rank'] = candidates.groupby('band').cumcount() + 1
        candidates['role'] = candidates['rank'].map(lambda r: 'primary' if r <= 16 else 'reserve')
        candidates = pd.concat([retained, candidates]).sort_values(['band', 'rank'])
        shutil.copyfile(target, out / 'candidates_initial.csv')
    write_csv(target, candidates)
    manifest = dict(source=SOURCE, source_url_sha256=digest(SOURCE), eligible_headers_sha256=header_hash.hexdigest(), limit=limit, seed=43,
                    min_games=12, band_width=200, bands=list(selected), primary=16, reserves=14,
                    ordering="sha256('43:' + lower_username + ':blitz'), username",
                    exclude_sha256=sha(exclude), candidates_sha256=sha(target),
                    code_sha256=sha(__file__), **before, **stats)
    write_json(out / ('sample_resample.json' if resample else 'sample_manifest.json'), manifest)
    return {'candidates': len(candidates), 'bands': len(selected), 'limit': limit}


@contextmanager
def users_response(data, ids):
    """POST analogue of serial_response; same global flock and 60s 429 policy."""
    folder = storage.DEFAULT_DATA / 'external'
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / 'http.lock').open('a') as lock:
        collect.fcntl.flock(lock, collect.fcntl.LOCK_EX)
        while True:
            response = requests.post('https://lichess.org/api/users', data=','.join(ids),
                headers={'User-Agent': collect.USER_AGENT, 'Accept': 'application/json'}, timeout=(15, 120))
            if response.status_code == 429:
                response.close()
                collect.time.sleep(60)
                continue
            try:
                response.raise_for_status()
                yield response
            finally:
                response.close()
            return


def screening_reason(account):
    if account is None:
        return 'closed_or_missing'
    reasons = [name for name in ('tosViolation', 'disabled', 'closed') if account.get(name)]
    if account.get('title') == 'BOT':
        reasons.append('BOT')
    return ';'.join(reasons)


def screen(out):
    out = Path(out)
    if (out / 'holdout_manifest.parquet').exists():
        raise ValueError('Assignment is frozen')
    candidates = pd.read_csv(out / 'candidates.csv')
    records = {}
    users = candidates.username.tolist()
    for start in range(0, len(users), 300):
        with users_response(out, users[start:start + 300]) as response:
            payload = response.json()
        if not isinstance(payload, list):
            raise ValueError('Invalid users response')
        for account in payload:
            records[str(account.get('id', account.get('username', ''))).lower()] = account
    candidates['reason'] = [screening_reason(records.get(u)) for u in users]
    candidates['eligible'] = candidates.reason.eq('')
    write_csv(out / 'screened.csv', candidates)
    write_json(out / 'screen_manifest.json', {'candidates_sha256': sha(out / 'candidates.csv'),
                                              'screened_sha256': sha(out / 'screened.csv')})
    return {'screened': len(candidates), 'dropped': int((~candidates.eligible).sum())}


def replacement_order(screened, band):
    rows = screened[(screened.role == 'reserve') & screened.eligible].copy()
    rows['distance'] = (rows.band - band).abs()
    return rows.sort_values(['distance', 'band', 'rank']).username.tolist()


def download_player(data, out, user):
    """Per-player root inside v3new prevents failed reserves contaminating the cohort.

    The existing cursor is committed only after a complete response. An interrupted
    response is retried from the fixed latest window; completed cursors are never
    requested again, including a crash before our ledger commit.
    """
    attempt = Path(data) / 'external/downloads' / user
    raw = attempt / 'raw/api' / user
    if not list(raw.glob('cursor-*.json')):
        try:
            collect.collect_api(attempt, [user], max_games=150, since=None, until=UNTIL, perf='blitz')
        except requests.HTTPError as exc:
            if exc.response is None or exc.response.status_code not in (404, 410):
                raise
            return {'games': 0, 'game_ids': [], 'start_ms': None, 'end_ms': None,
                    'reason': 'closed_or_missing'}
    collect.normalize_api(attempt)
    games = storage.read(attempt, 'games')
    games = games[(games.speed == 'blitz') & (games.start_ms < UNTIL)
                  & (games.white.eq(user) | games.black.eq(user))]
    games = games.sort_values(['start_ms', 'game_id'], ascending=[False, True]).head(150)
    return {'games': len(games), 'game_ids': games.game_id.tolist(),
            'start_ms': int(games.start_ms.min()) if len(games) else None,
            'end_ms': int(games.start_ms.max()) if len(games) else None}


def collect_cohort(data, out):
    out, data = Path(out), Path(data)
    if (out / 'holdout_manifest.parquet').exists():
        raise ValueError('Assignment is frozen')
    if read_json(out / 'screen_manifest.json')['candidates_sha256'] != sha(out / 'candidates.csv'):
        raise ValueError('Run screen on the current candidates first')
    screened = pd.read_csv(out / 'screened.csv').fillna({'reason': ''})
    ledger_path = out / 'collection_state.json'
    ledger = read_json(ledger_path) if ledger_path.exists() else {}
    used, final = set(), []
    resampled = None
    if (out / 'sample_resample.json').exists():
        resampled = set(read_json(out / 'sample_resample.json')['bands'])
        previous = pd.read_csv(out / 'cohort.csv')
        final = previous.loc[~previous.slot_band.isin(resampled)].to_dict('records')
        used = {row['username'] for row in final}
    for band in BANDS:
        if resampled is not None and band not in resampled:
            continue
        primaries = screened[(screened.band == band) & (screened.role == 'primary')].sort_values('rank')
        for row in primaries.itertuples():
            history = []
            choices = [row.username] + replacement_order(screened, band)
            for user in choices:
                if user in used:
                    continue
                info = screened[screened.username == user].iloc[0]
                if not info.eligible:
                    history.append({'username': user, 'reason': info.reason})
                    continue
                if user not in ledger:
                    ledger[user] = download_player(data, out, user)
                    write_json(ledger_path, ledger)
                    print(f'Completed downloads: {len(ledger)}', flush=True)
                details = ledger[user]
                used.add(user)  # a short account cannot be retried in another slot
                if details['games'] < 60:
                    history.append({'username': user, 'reason': details.get('reason', 'fewer_than_60'), 'games': details['games']})
                    continue
                final.append(dict(band=int(info.band), slot_band=band, slot_rank=row.rank,
                                  username=user, games=details['games'], start_ms=details['start_ms'],
                                  end_ms=details['end_ms'], replacement_history=json.dumps(history)))
                break
    cohort = pd.DataFrame(final, columns=['band', 'slot_band', 'slot_rank', 'username', 'games',
                                         'start_ms', 'end_ms', 'replacement_history']).sort_values(['slot_band', 'slot_rank'])
    write_csv(out / 'cohort.csv', cohort)
    membership = []
    scratch = data / 'external/materialized'
    if scratch.exists():
        shutil.rmtree(scratch)
    if (data / 'raw/api').exists():
        shutil.rmtree(data / 'raw/api')
    for row in cohort.itertuples():
        attempt = data / 'external/downloads' / row.username
        games = storage.read(attempt, 'games')
        ids = set(ledger[row.username]['game_ids'])
        moves = storage.read(attempt, 'moves')
        storage.append(scratch, storage.records(games[games.game_id.isin(ids)]),
                       storage.records(moves[moves.game_id.isin(ids)]))
        target = data / 'raw/api' / row.username
        target.mkdir(parents=True, exist_ok=True)
        for file in (attempt / 'raw/api' / row.username).glob('*.ndjson.gz'):
            shutil.copyfile(file, target / file.name)
        membership.extend((row.username, gid) for gid in sorted(ids))
    write_csv(out / 'membership.csv', pd.DataFrame(membership, columns=['player', 'game_id']))
    # Publish the committed index last: stale shards become ignored orphans.
    storage.connect(scratch).close()
    for name in ('games', 'moves'):
        target = data / 'processed/normalized' / name
        target.mkdir(parents=True, exist_ok=True)
        for file in (scratch / 'processed/normalized' / name).glob('*.parquet'):
            shutil.copyfile(file, target / file.name)
    (data / 'processed').mkdir(parents=True, exist_ok=True)
    shutil.copyfile(scratch / 'processed/index.sqlite', data / 'processed/index.tmp')
    (data / 'processed/index.tmp').replace(data / 'processed/index.sqlite')
    collect.normalize_api(data)
    write_json(out / 'collection_manifest.json', {'cohort_sha256': sha(out / 'cohort.csv'),
        'membership_sha256': sha(out / 'membership.csv'), 'screened_sha256': sha(out / 'screened.csv'),
        'until': UNTIL, 'max': 150, 'perf': 'blitz'})
    return {'players': len(cohort), 'player_games': len(membership),
            'next_action': ('cache-subset' if len(cohort) >= 170 else
                            'stop_for_operator_decision' if resampled is not None else
                            'resample_short_bands_once')}


def engine_row(row):
    payload = json.loads(row[2])
    return (payload.get('engine_version') is not None and payload.get('settings', {}).get('binary_sha256') == BINARY
            and (payload.get('actual_nodes') or 0) > 0
            and (payload.get('cp') is not None or payload.get('mate') is not None))


def hashed_rows(conn, count=500):
    """Bounded heap over the real full FEN+settings key; no SQLite writes."""
    rows = (r for r in conn.execute('SELECT fen,settings_key,payload FROM positions WHERE settings_key=?', (KEY,))
            if engine_row(r))
    return heapq.nsmallest(count, rows, key=lambda r: (digest(r[0] + '\0' + r[1]), r[0]))


def copy_positions(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.unlink(missing_ok=True)
    with closing(sqlite3.connect(tmp)) as conn:
        conn.execute('CREATE TABLE positions (fen TEXT, settings_key TEXT, payload TEXT, PRIMARY KEY(fen,settings_key))')
        conn.executemany('INSERT INTO positions VALUES (?,?,?)', rows)
        conn.commit()
    tmp.replace(path)


def cache_subset(data, out, old):
    data, out = Path(data), Path(out)
    moves = read_normalized(data, 'moves')
    fens = sorted(set(moves.fen_before) | set(moves.fen_after))
    hits = []
    with closing(readonly(Path(old) / 'processed/engine/cache.sqlite')) as conn:
        for fen in fens:
            row = conn.execute('SELECT fen,settings_key,payload FROM positions WHERE fen=? AND settings_key=?', (fen, KEY)).fetchone()
            if row:
                hits.append(row)
        agreement = hashed_rows(conn)
    if len(agreement) != 500:
        raise ValueError('Old cache has fewer than 500 engine rows')
    copy_positions(data / 'processed/engine/cache.sqlite', hits)
    copy_positions(out / 'agreement_sample.sqlite', agreement)
    write_json(data / 'processed/engine/selected.json', read_json(Path(old) / 'processed/features/manifest.json')['engine'])
    result = {'positions': len(fens), 'cache_hits': len(hits), 'remaining': len(fens) - len(hits),
              'agreement_rows': len(agreement), 'settings_key': KEY}
    write_json(out / 'cache_subset.json', result)
    return result


def public_id(value, namespace=''):
    # Existing HMAC helper only reads the environment, never ~/.tilt-salt.
    if len(os.environ.get('TILT_SALT', '')) >= 16:
        from ..labels.labels import private_id
        return private_id(namespace + value)
    return hmac.new(PUBLIC.encode(), (namespace + value).encode(), hashlib.sha256).hexdigest()


def assign_frame(cohort, games, old_games, old_users):
    """Assign kept feature sides; all development sides of shared holdouts drop."""
    a_players = set()
    for _, group in cohort.groupby('band'):
        players = sorted(group.username, key=lambda u: (digest(PUBLIC + u.lower()), u))
        a_players.update(players[:(3 * len(players) + 5) // 10])
    result = games[['game_id', 'player', 'session_id', 'start_ms', 'color']].copy()
    if result[['start_ms', 'session_id']].isna().any().any():
        raise ValueError('Assignment requires start_ms and existing session_id for every side')
    result['assignment'] = 'development'
    result.loc[result.player.isin(a_players), 'assignment'] = 'A_prime'
    for player, group in result[~result.player.isin(a_players)].groupby('player'):
        # Erratum 2: n and the nearest-rank anchor use only kept sides.
        ordered = group.sort_values(['start_ms', 'game_id'])
        anchor = ordered.iloc[max(0, math.ceil(.8 * len(ordered)) - 1)]
        cutoff = ordered.loc[ordered.session_id == anchor.session_id, 'start_ms'].min()
        result.loc[group.index[group.start_ms >= cutoff], 'assignment'] = 'B_prime'
    holdout_ids = set(result.loc[result.assignment != 'development', 'game_id'])
    result.loc[result.assignment.eq('development') & result.game_id.isin(holdout_ids), 'assignment'] = 'drop_shared_development'
    old_sides = []
    for row in old_games[old_games.game_id.isin(holdout_ids)].itertuples():
        for color in ('white', 'black'):
            player = getattr(row, color)
            if player in old_users:
                old_sides.append(dict(game_id=row.game_id, player=player, session_id=None,
                    start_ms=row.start_ms, color=color, assignment='drop_shared_development'))
    result['cohort'] = 'new'
    if old_sides:
        old = pd.DataFrame(old_sides)
        old['cohort'] = 'old'
        result = pd.concat([result, old], ignore_index=True)
    result['player_id'] = result.player.map(public_id)
    result['game_id'] = result.game_id.map(lambda v: public_id(v, 'game:'))
    result['session_id'] = result.session_id.map(lambda v: public_id(v, 'session:') if pd.notna(v) else None)
    return result.drop(columns='player').sort_values(['cohort', 'player_id', 'start_ms', 'game_id']).reset_index(drop=True)


def cohort_sides(data, out, *, return_excluded=False):
    """Keep feature sides, excluding only normalized games with at most one ply."""
    membership = pd.read_csv(Path(out) / 'membership.csv')
    games = pd.read_parquet(Path(data) / 'processed/features/games.parquet',
                            columns=['game_id', 'player', 'session_id', 'start_ms', 'color'])
    result = membership.merge(games, on=['player', 'game_id'], how='left',
                              validate='one_to_one', indicator=True)
    missing = result._merge.eq('left_only')
    excluded = pd.DataFrame(columns=['player', 'game_id', 'status', 'plies'])
    if missing.any():
        normalized = read_normalized(data, 'games')[['game_id', 'status', 'plies']]
        excluded = result.loc[missing, ['player', 'game_id']].merge(
            normalized, on='game_id', how='left', validate='many_to_one', indicator=True)
        if excluded._merge.eq('left_only').any():
            raise ValueError('Normalized game missing for a selected player-game side')
        if not excluded.plies.le(1).fillna(False).all():
            raise ValueError('Features missing a selected player-game side with invalid or >= 2 plies')
        excluded = excluded.drop(columns='_merge')
    result = result.loc[~missing].drop(columns='_merge').reset_index(drop=True)
    if result.session_id.isna().any():
        raise ValueError('Features missing a selected player-game side')
    return (result, excluded) if return_excluded else result


def kept_counts(cohort, sides):
    """Include cohort players with zero kept sides in per-player checks."""
    return cohort.username.map(sides.groupby('player').size()).fillna(0).astype(int)


def assign(data, out, old, exclude):
    out = Path(out)
    target = out / 'holdout_manifest.parquet'
    excluded_path = out / 'excluded_sides.csv'
    def refuse_existing():
        if target.exists() or target.with_suffix('.sha256').exists() or excluded_path.exists():
            raise ValueError('Refusing to regenerate holdout manifest or excluded sides')

    refuse_existing()
    cohort = pd.read_csv(out / 'cohort.csv')
    sides, excluded = cohort_sides(data, out, return_excluded=True)
    # Validate before even creating a flock file. Never replace short players.
    if (kept_counts(cohort, sides) < 60).any():
        raise ValueError('Every cohort player must have at least 60 kept sides')
    result = assign_frame(cohort, sides, read_normalized(old, 'games'), collect.usernames(exclude))
    excluded_status_counts = {str(k): int(v) for k, v in excluded.status.value_counts(dropna=False).items()}
    excluded['player_id'] = excluded.pop('player').map(public_id)
    excluded['game_id'] = excluded.game_id.map(lambda value: public_id(value, 'game:'))
    excluded = excluded[['player_id', 'game_id', 'status', 'plies']]
    # The flock serializes concurrent writers; a published manifest is never replaced.
    with (out / 'assignment.lock').open('a') as lock:
        collect.fcntl.flock(lock, collect.fcntl.LOCK_EX)
        refuse_existing()
        write_csv(excluded_path, excluded)
        storage.write_frame(target, result)
        target.with_suffix('.sha256').write_text(f'{sha(target)}  {target.name}\n')
        write_json(out / 'assignment_metadata.json', {'pseudonym': 'pipeline HMAC from environment'
            if len(os.environ.get('TILT_SALT', '')) >= 16 else 'HMAC-SHA256 keyed by public assignment string',
            'percentile': 'nearest rank ceil(0.8*n) on kept sides, one-based; session start inclusive',
            'excluded_sides_sha256': sha(excluded_path), 'excluded_sides_by_status': excluded_status_counts,
            'collected_sides': len(sides) + len(excluded), 'kept_sides': len(sides),
            'cohort_sha256': sha(out / 'cohort.csv'), 'membership_sha256': sha(out / 'membership.csv')})
    return {'manifest_rows': len(result), 'sha256': sha(target)}


def gate_arithmetic(cohort, old_users, own_moves, plies, colab, before_hash, after_hash):
    clocks = int(own_moves.think_seconds.notna().sum())
    evaluated = int((plies.eval_after_cp.notna() | plies.eval_after_mate.notna()).sum())
    clock_coverage = clocks / len(own_moves) if len(own_moves) else 0
    eval_coverage = evaluated / len(plies) if len(plies) else 0
    agreement = colab.get('agreement', {})
    checks = {'settings': colab.get('settings_key') == KEY and colab.get('binary_sha256') == BINARY,
              'agreement': agreement.get('tested') == 500 and agreement.get('identical') == 500
                           and agreement.get('mismatches') == 0,
              'clocks': clock_coverage >= .90, 'evals': eval_coverage >= .98,
              'size': int((cohort.kept_player_games >= 60).sum()) >= 170
                      and int(cohort.kept_player_games.sum()) >= 20000,
              'no_overlap': not bool(set(cohort.username.str.lower()) & old_users),
              'old_manifest_unchanged': before_hash == after_hash}
    return {'checks': {k: bool(v) for k, v in checks.items()}, 'pass': all(checks.values()),
            'players': len(cohort), 'players_at_least_60': int((cohort.kept_player_games >= 60).sum()),
            'collected_sides': int(cohort.games.sum()), 'kept_sides': int(cohort.kept_player_games.sum()),
            'player_games': int(cohort.kept_player_games.sum()), 'own_moves': len(own_moves), 'clock_present': clocks,
            'clock_coverage': clock_coverage, 'plies': len(plies), 'eval_present': evaluated,
            'eval_coverage': eval_coverage}


def gate(data, out, old, exclude, colab_path):
    data, out, old = Path(data), Path(out), Path(old)
    cohort = pd.read_csv(out / 'cohort.csv')
    sides = cohort_sides(data, out)
    cohort['kept_player_games'] = kept_counts(cohort, sides)
    spans = sides.groupby('player').start_ms.agg(['min', 'max'])
    cohort['start_ms'] = cohort.username.map(spans['min'])
    cohort['end_ms'] = cohort.username.map(spans['max'])
    moves_path = data / 'processed/features/moves.parquet'
    # Filtered projection bounds RAM and never loads behaviour summaries.
    moves = pd.read_parquet(moves_path, columns=['game_id', 'player', 'ply', 'think_seconds',
                                               'eval_after_cp', 'eval_after_mate'])
    own = moves.merge(sides[['game_id', 'player']], on=['game_id', 'player'], validate='many_to_one')
    plies = moves[moves.game_id.isin(sides.game_id)].drop_duplicates(['game_id', 'ply'])
    colab = read_json(colab_path)
    if colab.get('features_manifest_sha256') != sha(data / 'processed/features/manifest.json'):
        raise ValueError('Colab result does not match returned features manifest')
    initial = read_json(out / 'baseline.json')['features_manifest_sha256']
    result = gate_arithmetic(cohort, collect.usernames(exclude), own, plies, colab,
                             initial, sha(old / 'processed/features/manifest.json'))
    result['unique_games'] = int(sides.game_id.nunique())
    write_json(out / 's2_gate.json', result)
    qc = cohort.groupby('band').agg(players=('games', 'size'), player_games=('games', 'sum'),
        kept_player_games=('kept_player_games', 'sum'),
        start_ms=('start_ms', 'min'), end_ms=('end_ms', 'max')).reset_index()
    coverage = []
    for band, group in cohort.groupby('band'):
        band_sides = sides[sides.player.isin(group.username)]
        own_band = own[own.player.isin(group.username)]
        ply_band = plies[plies.game_id.isin(band_sides.game_id)]
        coverage.append({'band': band, 'own_moves': len(own_band),
            'clock_coverage': float(own_band.think_seconds.notna().mean()) if len(own_band) else 0,
            'plies': len(ply_band), 'eval_coverage': float((ply_band.eval_after_cp.notna() |
                ply_band.eval_after_mate.notna()).mean()) if len(ply_band) else 0})
    qc = qc.merge(pd.DataFrame(coverage), on='band')
    write_csv(out / 'qc_bands.csv', qc)
    # Per-player date spans/counts only, with pseudonyms instead of usernames.
    dates = cohort[['band', 'username', 'games', 'kept_player_games', 'start_ms', 'end_ms']].copy()
    dates['player_id'] = dates.pop('username').map(public_id)
    dates['first_game_utc'] = pd.to_datetime(dates.start_ms, unit='ms', utc=True)
    dates['last_game_utc'] = pd.to_datetime(dates.end_ms, unit='ms', utc=True)
    write_csv(out / 'qc_dates.csv', dates)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('step', choices=['sample', 'screen', 'collect', 'cache-subset', 'assign', 'gate'])
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--data', type=Path, default=storage.DEFAULT_DATA / 'v3new')
    parser.add_argument('--old-data', type=Path, default=storage.DEFAULT_DATA)
    parser.add_argument('--exclude', type=Path, default=EXCLUDE)
    parser.add_argument('--bands', type=int, nargs='+', help='Short-band lower edges; enlarged re-sample once')
    parser.add_argument('--colab-result', type=Path)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    new_root, old_root = args.data.resolve(), args.old_data.resolve()
    if (new_root == old_root or new_root in old_root.parents or
            (old_root in new_root.parents and new_root != (old_root / 'v3new'))):
        parser.error('Use a separate new data root')
    check_lock()
    try:
        if args.step == 'sample':
            result = sample(args.data, args.out, args.exclude, args.old_data, args.bands)
        elif args.step == 'screen':
            result = screen(args.out)
        elif args.step == 'collect':
            result = collect_cohort(args.data, args.out)
        elif args.step == 'cache-subset':
            result = cache_subset(args.data, args.out, args.old_data)
        elif args.step == 'assign':
            result = assign(args.data, args.out, args.old_data, args.exclude)
        else:
            result = gate(args.data, args.out, args.old_data, args.exclude,
                          args.colab_result or args.out / 'colab_result.json')
        print(json.dumps(result, indent=2))
    except (ValueError, FileNotFoundError, FileExistsError, requests.RequestException):
        # HTTP exception strings can contain usernames or Authorization details.
        parser.exit(2, 'S2 step failed; inspect private artifacts and inputs. No identifiers logged.\n')
    finally:
        check_lock()


if __name__ == '__main__':
    main()
