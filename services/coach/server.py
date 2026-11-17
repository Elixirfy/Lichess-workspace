"""Internal bounded HTTP worker. Lila owns persistence, retry, and cancellation."""

import argparse
import hmac
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from chess_analysis.engine import EngineConfig, Stockfish
from .questions import execute
from .provider import from_env


def make_server(host: str, port: int, token: str, config: EngineConfig, workers: int = 1, provider=None):
    if len(token) < 32 or not 1 <= workers <= 8:
        raise ValueError("internal token must have >=32 characters; workers must be 1..8")
    capacity = threading.BoundedSemaphore(workers)

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *_):
            pass  # No bearer, request body or untrusted draft in logs.

        def reply(self, status, value):
            data = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if self.path != "/analyse":
                return self.reply(404, {"error": "not_found"})
            auth = self.headers.get("Authorization", "")
            if not hmac.compare_digest(auth.encode("utf-8"), ("Bearer " + token).encode("utf-8")):
                return self.reply(401, {"error": "unauthorized"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return self.reply(400, {"error": "invalid_length"})
            if not 0 < length <= 65536:
                return self.reply(413, {"error": "body_limit"})
            if not capacity.acquire(blocking=False):
                return self.reply(429, {"error": "busy"})
            try:
                started = time.perf_counter()
                raw = self.rfile.read(length)
                with Stockfish(config) as engine:
                    result = execute(raw, engine, provider)
                result.setdefault("timings", {})["workerMs"] = round((time.perf_counter() - started) * 1000, 3)
                status, result = 200, result
            except (ValueError, TypeError, KeyError, AttributeError):
                status, result = 422, {"error": "invalid_job"}
            except Exception:
                status, result = 503, {"error": "analysis_unavailable"}
            finally:
                capacity.release()
            # Free compute capacity before a client can receive success and
            # issue its next request. Writing first creates spurious 429s.
            self.reply(status, result)

    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8137)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    config = EngineConfig(path=os.environ.get("STOCKFISH_PATH", "stockfish"))
    server = make_server(args.host, args.port, os.environ.get("COACH_INTERNAL_TOKEN", ""), config, args.workers, from_env())
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
