"""Bounded Stockfish calculations, independent of game actors and subscribers.

Score POV and cp-loss logic adapted from commentary/core.py at 02a6d45.
"""

from dataclasses import dataclass
from typing import Any

import chess
import chess.engine

from .facts import color_name
from .history import History


def replay_pv(board: chess.Board, moves: list[chess.Move]) -> list[dict[str, str]]:
    current = board.copy(stack=True)
    result = []
    for move in moves[:6]:
        if current.is_game_over(claim_draw=False) or current.is_fifty_moves():
            break
        if move not in current.legal_moves:
            raise ValueError("engine returned an illegal variation")
        result.append({"uci": move.uci(), "san": current.san(move)})
        current.push(move)
    return result


def engine_score(info: dict[str, Any], board: chess.Board, pov: chess.Color) -> dict:
    score = info["score"].pov(pov)
    return {
        "cp": score.score(),
        "mate": score.mate(),
        "pov": color_name(pov),
        "depth": info.get("depth"),
        "nodes": info.get("nodes"),
        "bound": bool(info.get("lowerbound") or info.get("upperbound")),
        "pv": replay_pv(board, info.get("pv", [])),
    }


def cp_loss(before: dict, after: dict) -> int | None:
    if before["pov"] != after["pov"] or before["bound"] or after["bound"]:
        return None
    if before["cp"] is None or after["cp"] is None:
        return None
    return max(0, before["cp"] - after["cp"])


@dataclass(frozen=True)
class EngineConfig:
    path: str
    time_seconds: float = 0.1
    timeout_seconds: float = 5.0
    hash_mb: int = 32

    def __post_init__(self) -> None:
        if not 0 < self.time_seconds <= 5:
            raise ValueError("engine time must be in (0, 5] seconds")
        if not self.time_seconds < self.timeout_seconds <= 30:
            raise ValueError("engine timeout must exceed search time and be <=30s")
        if not 1 <= self.hash_mb <= 512:
            raise ValueError("engine hash must be in [1, 512] MB")


class Stockfish:
    """One process per worker; use sequentially and always close the context.

    Engine errors propagate: the durable caller must retry or record missing
    coverage. A rules-only result must never count as successful engine analysis.
    """

    def __init__(self, config: EngineConfig):
        self.config = config
        self.engine: chess.engine.SimpleEngine | None = None

    def __enter__(self) -> "Stockfish":
        self.engine = chess.engine.SimpleEngine.popen_uci(
            self.config.path, timeout=self.config.timeout_seconds
        )
        try:
            self.engine.configure({"Threads": 1, "Hash": self.config.hash_mb})
        except BaseException:
            self.engine.close()
            self.engine = None
            raise
        return self

    def __exit__(self, *_: object) -> None:
        if self.engine is not None:
            try:
                self.engine.quit()
            finally:
                self.engine.close()
                self.engine = None

    def analyse(self, history: History, learner: chess.Color) -> dict:
        if self.engine is None:
            raise RuntimeError("engine is not started")
        if history.last is None or history.before.turn != learner:
            raise ValueError("move analysis must target a learner move")
        scores = []
        for board in (history.before, history.board):
            info = self.engine.analyse(
                board,
                chess.engine.Limit(time=self.config.time_seconds),
                # Reset state between independent jobs, retain repetition history.
                game=object(),
            )
            scores.append(engine_score(info, board, learner))
        before, after = scores
        return {
            "source": dict(self.engine.id),
            "limit": {"seconds": self.config.time_seconds, "threads": 1, "hashMb": self.config.hash_mb},
            "before": before,
            "after": after,
            "cpLoss": cp_loss(before, after),
        }

    def position(self, board: chess.Board, learner: chess.Color) -> dict:
        if self.engine is None:
            raise RuntimeError("engine is not started")
        info = self.engine.analyse(
            board, chess.engine.Limit(time=self.config.time_seconds), game=object()
        )
        score = engine_score(info, board, learner)
        if not score["pv"]:
            raise ValueError("no legal candidate available")
        return score
