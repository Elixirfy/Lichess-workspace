from time import perf_counter

from chess_analysis.engine import Stockfish
from chess_analysis.facts import rule_facts
from chess_analysis.history import History, canonical_fen, parse_position, replay

from .contracts import AnalyseMove

ANALYSIS_VERSION = "coach-facts-v1"


def validate_job(job: AnalyseMove) -> History:
    snapshot = job.snapshot
    history = replay(snapshot.initialFen, snapshot.sanHistory)
    if (history.board.ply() != snapshot.ply
            or canonical_fen(history.board) != canonical_fen(parse_position(snapshot.fen))):
        raise ValueError("snapshot/history mismatch")
    if history.revision != job.positionRevision:
        raise ValueError("position revision mismatch")
    learner = job.learnerColor == "white"
    if history.last is None or history.before.turn != learner:
        raise ValueError("expected a learner move")
    # Lila owns resign/abort/draw status. Only assert board-derived terminal
    # outcomes here; never infer that every finished game was a checkmate.
    if snapshot.status == "mate" and (
        not history.board.is_checkmate() or snapshot.winner != job.learnerColor
    ):
        raise ValueError("checkmate status mismatch")
    if snapshot.status == "stalemate" and (
        not history.board.is_stalemate() or snapshot.winner is not None
    ):
        raise ValueError("stalemate status mismatch")
    if snapshot.status in ("created", "started") and snapshot.winner is not None:
        raise ValueError("unfinished game has a winner")
    return history


def analyse_move(job: AnalyseMove, engine: Stockfish) -> dict:
    started = perf_counter()
    history = validate_job(job)
    facts = rule_facts(history)
    facts_ms = (perf_counter() - started) * 1000
    engine_started = perf_counter()
    engine_result = engine.analyse(history, job.learnerColor == "white")
    engine_ms = (perf_counter() - engine_started) * 1000
    return {
        "schemaVersion": 1,
        "requestId": job.requestId,
        "kind": job.kind,
        "positionRevision": history.revision,
        "analysisVersion": ANALYSIS_VERSION,
        "status": job.snapshot.status,
        "winner": job.snapshot.winner,
        "facts": facts,
        "engine": engine_result,
        "timings": {"replayFactsMs": round(facts_ms, 3), "engineMs": round(engine_ms, 3)},
    }
