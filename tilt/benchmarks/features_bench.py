"""Offline feature benchmark. Run: python benchmarks/features_bench.py --games 1000.

Synthetic positions/evals/clocks only; one known player, anonymous opponent.
Preparation is excluded; measured compute includes reads and all feature writes.
"""
import argparse
from pathlib import Path
import random
import tempfile
import time

import chess

from tilt.data import storage
from tilt.features.features import compute
from tilt.data.normalize import api_game


def synthesize(data, games=1000, plies=80):
    rng, board, sans = random.Random(42), chess.Board(), []
    for _ in range(plies):
        move = rng.choice(sorted(board.legal_moves, key=lambda m: m.uci()))
        sans.append(board.san(move))
        board.push(move)
    raw = dict(id='synthetic', variant='standard', status='resign', winner='white',
               players={'white': {'user': {'id': 'bench-player'}, 'rating': 1600}, 'black': {'rating': 1600}},
               clock={'initial': 180, 'increment': 2}, speed='blitz', moves=' '.join(sans),
               analysis=[{'eval': 0} for _ in sans], clocks=[18000 - 100 * (p // 2) for p in range(plies)],
               createdAt=100000, lastMoveAt=160000)
    template, moves = api_game(raw, observed_ms=161000)
    gs, ms = [], []
    for i in range(games):
        gid, start = f'bench{i:08d}', (i + 1) * 300000
        gs.append({**template, 'game_id': gid, 'start_ms': start, 'last_move_ms': start + 60000,
                   'end_ms': start + 60000, 'end_upper_ms': start + 61000, 'observed_ms': start + 61000})
        ms.extend({**m, 'game_id': gid, 'cp': float((i * 13 + m['ply'] * 37) % 500 - 250)} for m in moves)
    storage.append(data, gs, ms)


def benchmark(data, games=1000, plies=80, max_history_games=200):
    synthesize(data, games, plies)
    started = time.perf_counter()
    compute(data, max_history_games=max_history_games)
    return time.perf_counter() - started


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--games', '-N', type=int, default=1000)
    parser.add_argument('--plies', type=int, default=80)
    parser.add_argument('--max-history-games', type=int, default=200)
    args = parser.parse_args()
    if min(args.games, args.plies, args.max_history_games) < 1:
        parser.error('games, plies and history must be positive')
    with tempfile.TemporaryDirectory(prefix='tilt-bench-') as folder:
        elapsed = benchmark(Path(folder), args.games, args.plies, args.max_history_games)
    print(f'{args.games} games x {args.plies} plies; K={args.max_history_games}; compute={elapsed:.3f} s')


if __name__ == '__main__':
    main()
