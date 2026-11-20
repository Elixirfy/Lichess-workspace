"""Small bounded-memory Parquet batches with a transactional SQLite import index."""
from pathlib import Path
import sqlite3
import uuid

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

DEFAULT_DATA = Path(__file__).resolve().parents[3] / 'data'

GAME_SCHEMA = pa.schema([(n, t) for n, t in [
    ('game_id', pa.string()), ('white', pa.string()), ('black', pa.string()),
    ('white_rating', pa.int64()), ('black_rating', pa.int64()), ('speed', pa.string()),
    ('initial_seconds', pa.float64()), ('increment_seconds', pa.float64()),
    ('white_berserk', pa.bool_()), ('black_berserk', pa.bool_()),
    ('start_ms', pa.int64()), ('last_move_ms', pa.int64()), ('end_ms', pa.int64()),
    ('end_upper_ms', pa.int64()), ('end_kind', pa.string()), ('observed_ms', pa.int64()),
    ('status', pa.string()), ('winner', pa.string()), ('result', pa.string()),
    ('source', pa.string()), ('rated', pa.bool_()), ('initial_fen', pa.string()),
    ('middle_ply', pa.int64()), ('end_ply', pa.int64()), ('plies', pa.int64())]])
MOVE_SCHEMA = pa.schema([(n, t) for n, t in [
    ('game_id', pa.string()), ('ply', pa.int64()), ('color', pa.string()),
    ('player', pa.string()), ('uci', pa.string()), ('san', pa.string()),
    ('fen_before', pa.string()), ('fen_after', pa.string()),
    ('clock_seconds', pa.float64()), ('increment_applied', pa.bool_()),
    ('cp', pa.float64()), ('mate', pa.float64()), ('eval_source', pa.string()),
    ('api_best', pa.string())]])


def connect(data):
    data = Path(data)
    (data / 'processed').mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(data / 'processed' / 'index.sqlite')
    had_batches = conn.execute("SELECT 1 FROM sqlite_master WHERE name='batches'").fetchone()
    conn.execute('CREATE TABLE IF NOT EXISTS imported (game_id TEXT PRIMARY KEY)')
    conn.execute('CREATE TABLE IF NOT EXISTS batches (batch TEXT PRIMARY KEY)')
    if not had_batches:
        # Upgrade local pre-manifest shards; later orphan files are never visible to readers.
        for file in (data / 'processed' / 'normalized' / 'games').glob('*.parquet'):
            if (data / 'processed' / 'normalized' / 'moves' / file.name).exists():
                conn.execute('INSERT OR IGNORE INTO batches VALUES (?)', (file.stem,))
    conn.commit()
    return conn


def append(data, games, moves):
    if not games:
        return 0
    data = Path(data)
    with connect(data) as conn:
        conn.execute('BEGIN IMMEDIATE')
        ids = {g['game_id'] for g in games if not conn.execute(
            'SELECT 1 FROM imported WHERE game_id=?', (g['game_id'],)).fetchone()}
        if not ids:
            return 0
        unique_games, unique_moves = {}, {}
        for game in games:
            if game['game_id'] in ids:
                unique_games.setdefault(game['game_id'], game)
        for move in moves:
            if move['game_id'] in ids:
                unique_moves.setdefault((move['game_id'], move['ply']), move)
        games, moves = list(unique_games.values()), list(unique_moves.values())
        batch = uuid.uuid4().hex
        files = []
        try:
            for name, rows, schema in [('games', games, GAME_SCHEMA), ('moves', moves, MOVE_SCHEMA)]:
                folder = data / 'processed' / 'normalized' / name
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / f'{batch}.parquet'
                files.append(path)
                pq.write_table(pa.Table.from_pylist(rows, schema=schema), path, compression='zstd')
            conn.executemany('INSERT INTO imported VALUES (?)', [(i,) for i in sorted(ids)])
            conn.execute('INSERT INTO batches VALUES (?)', (batch,))
        except BaseException:
            for file in files:
                file.unlink(missing_ok=True)
            raise
    return len(games)


def read(data, name):
    path = Path(data) / 'processed' / 'normalized' / name
    schema = GAME_SCHEMA if name == 'games' else MOVE_SCHEMA
    if not path.exists() or not list(path.glob('*.parquet')):
        return pa.Table.from_pylist([], schema=schema).to_pandas()
    with connect(data) as conn:
        committed = {row[0] for row in conn.execute('SELECT batch FROM batches')}
    files = [file for file in sorted(path.glob('*.parquet')) if file.stem in committed]
    return pd.read_parquet(files) if files else pa.Table.from_pylist([], schema=schema).to_pandas()


def write_frame(path, frame):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    frame.to_parquet(temp, index=False, compression='zstd')
    temp.replace(path)


def records(frame):
    return frame.astype(object).where(pd.notna(frame), None).to_dict('records')
