"""Deterministic Vietnamese cards. Only this projection is public to browsers."""

import chess

from chess_analysis.engine import Stockfish
from chess_analysis.history import canonical_fen, parse_position, replay

from .analysis import analyse_move, validate_job
from .contracts import AnalyseMove, QuestionJob
from .review import move_card

PIECES = {"pawn": "tốt", "knight": "mã", "bishop": "tượng", "rook": "xe", "queen": "hậu", "king": "vua"}


def answer(job: QuestionJob, engine: Stockfish, provider=None) -> dict:
    if job.kind == "explain":
        if job.hintLevel != 0:
            raise ValueError("unexpected hint level")
        raw = job.model_dump(exclude={"hintLevel"})
        raw["kind"] = "analyseMove"
        historical = AnalyseMove.model_validate(raw)
        history = validate_job(historical)
        card = move_card(history)
    else:
        history = replay(job.snapshot.initialFen, job.snapshot.sanHistory)
        board = history.board
        if (history.revision != job.positionRevision or board.ply() != job.snapshot.ply
                or canonical_fen(board) != canonical_fen(parse_position(job.snapshot.fen))):
            raise ValueError("snapshot/history mismatch")
        if (board.turn != (job.learnerColor == "white") or board.is_game_over()
                or board.is_fifty_moves() or job.snapshot.status != "started"):
            raise ValueError("live question unavailable")
        if job.kind == "hint":
            if job.hintLevel == 1:
                card = {
                    "text": "Ưu tiên thoát chiếu trước khi thực hiện kế hoạch khác." if board.is_check() else
                        "Trước khi chọn nước, hãy kiểm tra sự an toàn của vua và các quân đang bị tấn công.",
                    "highlights": [], "moves": [],
                }
            elif job.hintLevel in (2, 3):
                score = engine.position(board, board.turn)
                candidate = score["pv"][0]
                move = chess.Move.from_uci(candidate["uci"])
                if job.hintLevel == 2:
                    role = chess.piece_name(board.piece_type_at(move.from_square))
                    origin = chess.square_name(move.from_square)
                    card = {
                        "text": f"Hãy xem xét các nước hợp lệ của {PIECES[role]} ở {origin}.",
                        "highlights": [origin], "moves": [],
                    }
                else:
                    card = {
                        "text": f"Một nước ứng viên từ engine là {candidate['san']}, hãy tự kiểm tra ý tưởng trước khi đi.",
                        "highlights": [chess.square_name(move.from_square), chess.square_name(move.to_square)],
                        "moves": score["pv"],
                    }
            else:
                raise ValueError("invalid hint level")
        else:
            if job.hintLevel != 0 or not history.last or history.before.turn == board.turn:
                raise ValueError("threat requires an opponent move")
            card = threat_card(board)
    narration = {}
    if provider is not None and job.kind in ("explain", "threat"):
        from .narrative import narrate
        card, metrics = narrate(provider, history, job.kind, card)
        narration = {"narration": metrics}
    return {
        "schemaVersion": 1, "requestId": job.requestId, "kind": job.kind,
        "positionRevision": job.positionRevision, "hintLevel": job.hintLevel,
        "analysisVersion": "coach-deterministic-v1", "card": card, **narration,
    }


def threat_card(board: chess.Board) -> dict:
    if board.is_check():
        square = chess.square_name(board.king(board.turn))
        return {"text": "Vua của bạn đang bị chiếu, hãy chọn một nước đỡ chiếu hợp lệ.", "highlights": [square], "moves": []}
    order = {chess.QUEEN: 5, chess.ROOK: 4, chess.BISHOP: 3, chess.KNIGHT: 2, chess.PAWN: 1}
    targets = [
        (order.get(piece.piece_type, 0), square, piece)
        for square, piece in board.piece_map().items()
        if piece.color == board.turn and piece.piece_type != chess.KING
        and board.is_attacked_by(not board.turn, square)
    ]
    if targets:
        _, square, piece = max(targets, key=lambda item: (item[0], item[1]))
        name = chess.square_name(square)
        role = PIECES[chess.piece_name(piece.piece_type)]
        # Rule attack relations include pinned attackers; no assertion of a
        # legal capture, forced loss, or a "hanging" piece is made.
        return {"text": f"Quân {role} ở {name} nằm trong tầm tấn công của đối thủ, hãy kiểm tra độ an toàn của quân này.", "highlights": [name], "moves": []}
    return {"text": "Chưa xác nhận được quân của bạn đang nằm trong tầm tấn công trực tiếp, hãy kiểm tra nước vừa đi của đối thủ trước khi tiếp tục.", "highlights": [], "moves": []}


def execute(raw: bytes, engine: Stockfish, provider=None) -> dict:
    import json
    data = json.loads(raw)
    if data.get("kind") == "analyseMove":
        job = AnalyseMove.model_validate(data)
        result = analyse_move(job, engine)
        result["card"] = move_card(validate_job(job))
        return result
    return answer(QuestionJob.model_validate(data), engine, provider)
