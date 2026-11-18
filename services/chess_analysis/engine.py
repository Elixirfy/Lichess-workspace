"""Bounded Stockfish calculations, independent of game actors and subscribers.

Score POV and cp-loss logic adapted from commentary/core.py at 02a6d45.
"""

from dataclasses import dataclass
from collections.abc import Iterable
from typing import Any

import chess
import chess.engine

from .facts import color_name
from .history import History

PRACTICE_PLIES = 7


def completed_lines(infos: Iterable[dict[str, Any]], width: int) -> list[dict[str, Any]]:
    """Pick the latest depth with an exact score for each requested line."""
    depths: dict[int, dict[int, dict[str, Any]]] = {}
    for info in infos:
        if "depth" not in info or "score" not in info or not info.get("pv"):
            continue
        if info.get("lowerbound") or info.get("upperbound"):
            continue
        depths.setdefault(info["depth"], {})[info.get("multipv", 1)] = info
    for depth in sorted(depths, reverse=True):
        lines = depths[depth]
        if len(lines) == width and len({line["pv"][0] for line in lines.values()}) == width:
            return [lines[i] for i in range(1, width + 1)]
    return []


def replay_pv(board: chess.Board, moves: list[chess.Move], max_plies: int = 6) -> list[dict[str, str]]:
    current = board.copy(stack=True)
    result = []
    for move in moves[:max_plies]:
        if current.is_game_over(claim_draw=False) or current.is_fifty_moves():
            break
        if move not in current.legal_moves:
            raise ValueError("engine returned an illegal variation")
        result.append({"uci": move.uci(), "san": current.san(move)})
        current.push(move)
    return result


def engine_score(info: dict[str, Any], board: chess.Board, pov: chess.Color, *, max_plies: int = 6) -> dict:
    score = info["score"].pov(pov)
    return {
        "cp": score.score(),
        "mate": score.mate(),
        "pov": color_name(pov),
        "depth": info.get("depth"),
        "nodes": info.get("nodes"),
        "bound": bool(info.get("lowerbound") or info.get("upperbound")),
        "pv": replay_pv(board, info.get("pv", []), max_plies),
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
        candidates = []
        rough_loss = (before["cp"] or 0) - (after["cp"] or 0)
        mate_changed = (before["mate"] or 0) > 0 >= (after["mate"] or 0) or (
            (after["mate"] or 0) < 0 <= (before["mate"] or 0)
        )
        if not history.board.is_game_over() and not history.board.is_fifty_moves() and (rough_loss >= 100 or mate_changed):
            # Recheck only possible teaching moments. Search within the worker,
            # using a small fixed budget and comparable scores from both sides.
            deeper = chess.engine.Limit(time=0.35)
            width = min(3, history.before.legal_moves.count())
            with self.engine.analysis(history.before, deeper, multipv=width, game=object()) as analysis:
                lines = completed_lines(analysis, width)
            with self.engine.analysis(history.board, deeper, multipv=1, game=object()) as analysis:
                replies = completed_lines(analysis, 1)
            if lines and replies:
                candidates = [
                    engine_score(line, history.before, learner, max_plies=PRACTICE_PLIES) for line in lines
                ]
                before, after = candidates[0], engine_score(replies[0], history.board, learner)
        return {
            "source": dict(self.engine.id),
            "limit": {"seconds": self.config.time_seconds, "threads": 1, "hashMb": self.config.hash_mb},
            "before": before,
            "after": after,
            "cpLoss": cp_loss(before, after),
            **({"verifiedCandidates": candidates} if candidates else {}),
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
