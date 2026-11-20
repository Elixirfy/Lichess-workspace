"""Run from the monorepo root: python -m tilt <command>."""
import argparse
import json
from pathlib import Path

from .data.storage import DEFAULT_DATA


def parser():
    root = argparse.ArgumentParser(description='Tilt research pipeline — human labels and separate weak-label models')
    root.add_argument('--data', type=Path, default=DEFAULT_DATA, help='Private data directory (default: tilt/data with raw/, processed/, external/)')
    sub = root.add_subparsers(dest='command', required=True)
    api = sub.add_parser('collect-api', help='Serial, resumable Lichess NDJSON download')
    api.add_argument('usernames', nargs='*')
    api.add_argument('--users-file')
    api.add_argument('--max', type=int, default=50)
    api.add_argument('--backfill', action='store_true', help='Fetch strictly older games than the oldest cursor watermark')
    api.add_argument('--since', type=int, help='UTC epoch milliseconds')
    api.add_argument('--until', type=int, help='UTC epoch milliseconds')
    api.add_argument('--perf-type', help='Comma-separated perf types, e.g. blitz,rapid')
    sub.add_parser('normalize', help='Recover normalized tables from raw API gzip files')
    for name in ('collect-dump', 'sample-players'):
        dump = sub.add_parser(name, help='Stream local PGN(.zst) or database.lichess.org monthly dump')
        dump.add_argument('source')
        dump.add_argument('--max-staging-gb', type=float, default=5)
        dump.add_argument('--speeds', help='Comma-separated speeds')
        dump.add_argument('--min-games', type=int, default=20 if name == 'sample-players' else 1)
        dump.add_argument('--limit', type=int, help='Stop after this many candidate games (before min-games filtering)')
        dump.add_argument('--since', type=int)
        dump.add_argument('--until', type=int)
        if name == 'collect-dump':
            dump.add_argument('--users-file')
            dump.add_argument('--users', nargs='+', help='Target usernames')
        else:
            dump.add_argument('--output', required=True)
            dump.add_argument('--per-stratum', type=int, default=10)
            dump.add_argument('--rating-band-width', type=int, default=200)
            dump.add_argument('--seed', type=int, default=42)
    engine = sub.add_parser('analyze', help='Cached process-parallel fixed-budget MultiPV=2 Stockfish')
    engine.add_argument('--engine', default='/usr/games/stockfish')
    budget = engine.add_mutually_exclusive_group()
    budget.add_argument('--nodes', type=int, default=100000)
    budget.add_argument('--depth', type=int)
    engine.add_argument('--processes', type=int, default=2)
    engine.add_argument('--hash-mb', type=int, default=64)
    feature = sub.add_parser('features', help='Build move/window/event/game/session features and prior-only baselines')
    feature.add_argument('--max-history-games', type=int, default=200)
    feature.add_argument('--window', type=int, default=12)
    feature.add_argument('--min-prior-games', type=int, default=5)
    feature.add_argument('--session-gap-minutes', type=int, default=30)
    app = sub.add_parser('label-app', help='Run the local Vietnamese human-labelling app')
    app.add_argument('--port', type=int, default=8000)
    dataset = sub.add_parser('build-dataset', help='Join human labels, audit leakage, pseudonymise and split')
    dataset.add_argument('--time-validation-ms', type=int)
    dataset.add_argument('--time-test-ms', type=int)
    weak = sub.add_parser('weak-label', help='Separate behavioural proxy labels; never human labels')
    weak.add_argument('--users-file', type=Path, default=Path.home() / 'tilt-users.txt')
    train = sub.add_parser('train', help='Train weak-label tree models and CPU LSTM')
    train.add_argument('--epochs', type=int, default=12)
    train.add_argument('--trees', type=int, default=100)
    train.add_argument('--threads', type=int, default=2)
    evaluate = sub.add_parser('evaluate', help='Report agreement with weak labels, not emotions')
    evaluate.add_argument('--bootstrap-repetitions', type=int, default=100)
    score = sub.add_parser('score', help='Local weak-model scores and exploratory prefix timelines')
    score.add_argument('--player', required=True)
    score.add_argument('--game')
    score.add_argument('--every-plies', type=int, default=12, help='Timeline stride in board plies')
    worker = sub.add_parser('lila-worker', help='Score finished games queued by a lila site (tilt_queue)')
    worker.add_argument('--lila-url', default='http://localhost:9663')
    worker.add_argument('--mongo', default='mongodb://127.0.0.1:27017')
    worker.add_argument('--db', default='lichess')
    worker.add_argument('--lila-data', type=Path, default=DEFAULT_DATA / 'external' / 'lila',
                        help='Separate data root for site games; models are read from --data')
    worker.add_argument('--lila-data-v3', type=Path, default=None,
                        help='Blitz-only data root for M-v3 (default: <lila-data>-v3)')
    worker.add_argument('--engine', default='/usr/games/stockfish')
    worker.add_argument('--interval', type=int, default=10, help='Seconds between queue polls')
    worker.add_argument('--once', action='store_true', help='Answer the current queue and exit')
    return root


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    from .data import collect
    try:
        match args.command:
            case 'collect-api':
                users = set(args.usernames) | collect.usernames(args.users_file)
                if not users:
                    p.error('Supply a username or --users-file')
                result = {'imported': collect.collect_api(args.data, users, args.max, args.since, args.until, args.perf_type, args.backfill)}
            case 'normalize':
                result = {'imported': collect.normalize_api(args.data)}
            case 'collect-dump':
                result = collect.collect_dump(args.data, args.source, collect.usernames(args.users_file) | {u.lower() for u in (args.users or [])},
                    set(args.speeds.split(',')) if args.speeds else None, args.min_games, args.limit, args.since, args.until, args.max_staging_gb)
            case 'sample-players':
                result = collect.sample_players(args.data, args.source, args.output, args.min_games,
                    args.per_stratum, args.rating_band_width, args.seed,
                    set(args.speeds.split(',')) if args.speeds else None, args.limit, args.since, args.until, args.max_staging_gb)
            case 'analyze':
                from .core.engine import analyze
                result = analyze(args.data, args.engine, args.nodes, args.depth, args.processes, args.hash_mb)
            case 'features':
                from .features.features import compute
                result = compute(args.data, args.window, args.min_prior_games, args.session_gap_minutes, args.max_history_games)
            case 'label-app':
                from .api.app import create_app
                import uvicorn
                uvicorn.run(create_app(args.data, port=args.port), host='127.0.0.1', port=args.port)
                return
            case 'build-dataset':
                from .data.dataset import build_dataset
                result = build_dataset(args.data, args.time_validation_ms, args.time_test_ms)
            case 'weak-label':
                from .labels.weak_labels import build
                result = build(args.data, args.users_file)
            case 'train':
                from .core.train import run
                if min(args.epochs, args.trees, args.threads) < 1:
                    raise ValueError('Epochs, trees and threads must be positive')
                result = run(args.data, args.epochs, args.trees, args.threads)
            case 'evaluate':
                from .evaluation.evaluate import run
                if args.bootstrap_repetitions < 2:
                    raise ValueError('Use at least two bootstrap repetitions')
                result = run(args.data, args.bootstrap_repetitions)
            case 'score':
                from .core.score import run
                result = run(args.data, args.player, args.game, args.every_plies)
            case 'lila-worker':
                from .workers.lila_worker import serve
                result = serve(args.mongo, args.db, args.lila_data, args.data, args.lila_url, args.engine,
                               args.interval, args.once, data_v3=args.lila_data_v3)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, FileNotFoundError) as exc:
        p.exit(2, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
