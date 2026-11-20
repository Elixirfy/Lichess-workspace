"""Local fishnet client for development: analyses the games queued in lila with the system Stockfish.

lila in dev mode accepts any fishnet client without a key (fishnet.offline_mode). Requests come from the
"Request a computer analysis" button and from the AI Coach, whose first question on a game queues its server
analysis. Started by start-lichess.sh, which stops it with lila.

Environment (all optional):
  FISHNET_LOCAL_URL      lila's fishnet endpoint (default http://localhost:9663/fishnet)
  FISHNET_LOCAL_ENGINES  Stockfish processes analysing the positions of a game in parallel (default 8)
  FISHNET_LOCAL_NODES    most nodes per position, lila asks for more (default 500000)
On an i5-12500H a 38-ply game takes 9 s with the defaults (depth about 20), 26 s with 4 engines at 1M nodes;
the evaluations differ by 5 cp on average, as much as two runs of the same setting.
  STOCKFISH              engine binary (default /usr/games/stockfish)
"""

import os
import queue
import time
from concurrent.futures import ThreadPoolExecutor

import chess
import chess.engine
import requests

URL = os.environ.get('FISHNET_LOCAL_URL', 'http://localhost:9663/fishnet')
ENGINES = max(1, int(os.environ.get('FISHNET_LOCAL_ENGINES', '8')))
MAX_NODES = int(os.environ.get('FISHNET_LOCAL_NODES', '500000'))
STOCKFISH = os.environ.get('STOCKFISH', '/usr/games/stockfish')
VARIANTS = ('standard', 'fromPosition', 'chess960')
IDLE_S = 2  # between two acquire calls while the queue is empty
DOWN_S = 5  # while lila is not up

UA = {'User-Agent': 'fishnet-local-dev/2.11.0'}
HELLO = {'fishnet': {'version': '2.11.0', 'apikey': ''}, 'stockfish': {'flavor': 'nnue'}}


def log(msg):
    print(time.strftime('%H:%M:%S'), msg, flush=True)


class Engines:
    """A pool of Stockfish processes, one position each at a time; a crashed engine is replaced."""

    def __init__(self, n):
        self.free = queue.Queue()
        for _ in range(n):
            self.free.put(self.start())
        self.pool = ThreadPoolExecutor(n)

    @staticmethod
    def start():
        engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH)
        engine.configure({'Threads': 1, 'Hash': 64})
        return engine

    def evaluate(self, board, nodes):
        engine = self.free.get()
        try:
            return evaluate(engine, board, nodes)
        except chess.engine.EngineError:
            engine.close()
            engine = self.start()
            return evaluate(engine, board, nodes)
        finally:
            self.free.put(engine)

    def analyse(self, positions, skip, nodes):
        def one(item):
            i, board = item
            return {'skipped': True} if i in skip else self.evaluate(board, nodes)

        return list(self.pool.map(one, enumerate(positions)))


def evaluate(engine, board, nodes):
    if board.is_checkmate():
        return {'score': {'mate': 0, 'mateGiven': False}, 'depth': 0, 'nodes': 0, 'time': 0, 'nps': 0, 'pv': ''}
    if board.is_game_over():
        return {'score': {'cp': 0}, 'depth': 0, 'nodes': 0, 'time': 0, 'nps': 0, 'pv': ''}
    info = engine.analyse(board, chess.engine.Limit(nodes=nodes))
    score = info['score'].relative  # the side to move, as UCI engines and fishnet report it
    mate = score.mate()
    return {
        'score': {'mate': mate} if mate is not None else {'cp': score.score()},
        'depth': info.get('depth', 0),
        'nodes': info.get('nodes', nodes),
        'time': int(info.get('time', 0) * 1000),
        'nps': info.get('nps', 0),
        'pv': ' '.join(m.uci() for m in info.get('pv', [])),
    }


def positions_of(work):
    board = chess.Board(work.get('position') or chess.STARTING_FEN, chess960=work.get('variant') == 'chess960')
    out = [board.copy()]
    for uci in work['moves'].split():
        board.push_uci(uci)
        out.append(board.copy())
    return out


def main():
    engines = Engines(ENGINES)
    http = requests.Session()
    http.headers.update(UA)
    log(f'fishnet-local: {ENGINES} engines, at most {MAX_NODES} nodes per position, polling {URL}')
    res = None  # the last response: 204 = no work, 202 = a work to do
    up = None
    while True:
        try:
            if res is None or res.status_code == 204:
                if res is not None:
                    time.sleep(IDLE_S)
                res = http.post(f'{URL}/acquire', json=HELLO, timeout=30)
                if res.status_code in (202, 204) and not up:
                    log('connected to lila')
                    up = True
                elif res.status_code not in (202, 204):  # 503 while lila warms up
                    res = None
                    time.sleep(DOWN_S)
                continue
            res.raise_for_status()
            work = res.json()
            if work.get('work', {}).get('type') != 'analysis' or work.get('variant') not in VARIANTS:
                # not posted: lila gives the work up after a few timeouts
                log(f"skipping work {work.get('work', {}).get('id')}: {work.get('variant')} is not supported")
                res = None
                time.sleep(IDLE_S)
                continue
            nodes = min(MAX_NODES, int(work['work'].get('nodes', {}).get('sf16', MAX_NODES)))
            start = time.monotonic()
            positions = positions_of(work)
            analysis = engines.analyse(positions, set(work.get('skipPositions', [])), nodes)
            # the answer to a posted analysis is the next work, or 204
            res = http.post(f"{URL}/analysis/{work['work']['id']}", json={**HELLO, 'analysis': analysis},
                            timeout=30)
            log(f"game {work['game_id']}: {len(positions)} positions at {nodes} nodes in "
                f'{time.monotonic() - start:.1f} s -> HTTP {res.status_code}')
        except requests.ConnectionError:
            if up is not False:
                log('lila is not up, waiting')
                up = False
            res = None
            time.sleep(DOWN_S)
        except Exception as e:  # a bad work or lila restarting: log it and ask again
            log(f'error: {type(e).__name__}: {e}')
            res = None
            time.sleep(DOWN_S)


if __name__ == '__main__':
    main()
