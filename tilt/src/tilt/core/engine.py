"""Fixed-budget MultiPV=2 analysis, process workers, FEN+settings SQLite cache."""
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import multiprocessing
from pathlib import Path
import sqlite3

import chess
import chess.engine

from ..data import storage

_ENGINE = None
_SETTINGS = None


def cache_db(data):
    path = Path(data) / 'processed' / 'engine'
    path.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path / 'cache.sqlite')
    conn.execute('CREATE TABLE IF NOT EXISTS positions (fen TEXT, settings_key TEXT, payload TEXT, PRIMARY KEY(fen,settings_key))')
    return conn


def _init_worker(binary, settings, loader=None):
    global _ENGINE, _SETTINGS
    _SETTINGS = settings
    # loader: optional command prefix (e.g. a bundled ld.so with --library-path) that runs the
    # same binary on hosts with an older glibc. The cache key still hashes the binary itself.
    _ENGINE = chess.engine.SimpleEngine.popen_uci([*loader, binary] if loader else binary)
    _ENGINE.configure({'Threads': 1, 'Hash': settings['hash_mb']})


def _position(fen):
    board = chess.Board(fen)
    if not board.is_valid():
        raise ValueError('Invalid position')
    if board.is_game_over():
        outcome = board.outcome()
        cp = (1000 if outcome.winner else -1000) if outcome.winner is not None else 0
        pvs = []
    else:
        # A fresh game clears engine state. No warm-hash dependence on task order.
        pvs = _ENGINE.analyse(board, chess.engine.Limit(**_SETTINGS['budget']), multipv=2,
                              game=object(), info=chess.engine.INFO_ALL)
        cp = None
    def score(pv):
        value = pv['score'].white()
        return {'cp': value.score(), 'mate': value.mate()}
    first = score(pvs[0]) if pvs else {'cp': cp, 'mate': None}
    second = score(pvs[1]) if len(pvs) > 1 else {'cp': None, 'mate': None}
    return dict(fen=fen, **first, second_cp=second['cp'], second_mate=second['mate'],
        best_move=pvs[0]['pv'][0].uci() if pvs else None,
        engine_version=_ENGINE.id.get('name', 'unknown'), settings=_SETTINGS,
        actual_depth=pvs[0].get('depth') if pvs else None,
        actual_nodes=pvs[0].get('nodes') if pvs else 0)


def _batch(task):
    binary, settings, fens, loader = task
    _init_worker(binary, settings, loader)
    try:
        return [_position(fen) for fen in fens]
    finally:
        _ENGINE.quit()


def analyze(data, binary='/usr/games/stockfish', nodes=100000, depth=None, processes=2, hash_mb=64,
            loader=None, batch_size=512):
    if batch_size < 1 or processes < 1 or hash_mb < 1 or (depth is not None and depth < 1) or (depth is None and nodes < 1):
        raise ValueError('Engine budgets, memory and process count must be positive')
    executable = Path(binary).resolve()
    if not executable.is_file():
        raise ValueError(f'Engine not found: {executable}')
    # The binary hash prevents a silent cache hit after a Stockfish upgrade.
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    settings = dict(binary_sha256=digest, threads=1, hash_mb=hash_mb, multipv=2,
        budget={'depth': depth} if depth is not None else {'nodes': nodes},
        position_history='FEN only; repetitions unavailable', fresh_game_per_position=True)
    key = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()
    moves = storage.read(data, 'moves')
    # Also fill missing best/second-best metadata for evaluated positions.
    positions = sorted(set(moves.fen_before) | set(moves.fen_after))
    with cache_db(data) as conn:
        known = {r[0] for r in conn.execute('SELECT fen FROM positions WHERE settings_key=?', (key,))}
        missing = [fen for fen in positions if fen not in known]
        if missing:
            with ProcessPoolExecutor(max_workers=processes, mp_context=multiprocessing.get_context('spawn')) as pool:
                tasks = ((str(executable), settings, missing[i:i + batch_size], loader)
                         for i in range(0, len(missing), batch_size))
                for batch in pool.map(_batch, tasks):
                    for result in batch:
                        conn.execute('INSERT OR REPLACE INTO positions VALUES (?,?,?)',
                                     (result['fen'], key, json.dumps(result)))
                    conn.commit()
    manifest = Path(data) / 'processed' / 'engine' / 'selected.json'
    manifest.write_text(json.dumps({'settings_key': key, **settings}, indent=2))
    return {'positions': len(positions), 'computed': len(missing), 'cache_hits': len(positions) - len(missing), 'settings_key': key}


def load_cache(data, fields=None):
    """Load the selected cache; `fields` keeps only those payload keys to bound memory."""
    manifest = Path(data) / 'processed' / 'engine' / 'selected.json'
    if not manifest.exists():
        return {}, None
    selected = json.loads(manifest.read_text())
    with cache_db(data) as conn:
        rows = conn.execute('SELECT fen,payload FROM positions WHERE settings_key=?', (selected['settings_key'],))
        if fields is None:
            values = {fen: json.loads(payload) for fen, payload in rows}
        else:
            values = {}
            for fen, payload in rows:
                full = json.loads(payload)
                values[fen] = {key: full.get(key) for key in fields}
    return values, selected
