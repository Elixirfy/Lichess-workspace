"""Deterministic Vietnamese cards. Only this projection is public to browsers."""

import chess

from chess_analysis.engine import Stockfish
from chess_analysis.history import canonical_fen, parse_position, replay

from .analysis import analyse_move, validate_job
from .contracts import AnalyseMove, QuestionJob
from .review import CENTER, PIECES, VALUES, move_card, move_words, review_move
CHECK_HINT = "Ưu tiên thoát chiếu trước khi thực hiện kế hoạch khác."
THREAT_HINT = "Trước khi triển khai kế hoạch, hãy tìm nước chiếu hoặc bắt quân nguy hiểm nhất của đối thủ."
QUIET_HINT = "Trước khi chọn nước, hãy kiểm tra sự an toàn của vua và các quân đang bị tấn công."


def answer(job: QuestionJob, engine: Stockfish, provider=None) -> dict:
    if job.kind == "explain":
        if job.hintLevel != 0:
            raise ValueError("unexpected hint level")
        raw = job.model_dump(exclude={"hintLevel"})
        raw["kind"] = "analyseMove"
        historical = AnalyseMove.model_validate(raw)
        history = validate_job(historical)
        checked, _ = review_move(history, engine.analyse(history, history.before.turn),
                                 official_draw=job.snapshot.status == "draw")
        card = move_card(history, checked)
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
                text = first_hint(history)
                card = {
                    "text": text,
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
                        "text": candidate_text(board, move, score["pv"]),
                        "highlights": [chess.square_name(move.from_square), chess.square_name(move.to_square)],
                        "moves": score["pv"],
                    }
            else:
                raise ValueError("invalid hint level")
        else:
            if job.hintLevel != 0 or not history.last or history.before.turn == board.turn:
                raise ValueError("threat requires an opponent move")
            checked = threat_observation(history)
            card = move_card(history, checked)
    narration = {}
    if provider is not None and job.kind in ("explain", "threat"):
        from .narrative import narrate
        card, metrics = narrate(provider, history, job.kind, card, checked)
        narration = {"narration": metrics}
    return {
        "schemaVersion": 1, "requestId": job.requestId, "kind": job.kind,
        "positionRevision": job.positionRevision, "hintLevel": job.hintLevel,
        "analysisVersion": "coach-deterministic-v1", "card": card, **narration,
        **({"practice": checked["practice"]} if job.kind == "explain" and "practice" in checked else {}),
    }


def immediate_threats(board):
    """List mate-in-one and plausible material threats for the side on move."""
    for move in board.legal_moves:
        victim = board.piece_at(move.to_square)
        if not board.gives_check(move) and victim is None:
            continue
        after = board.copy(stack=False)
        after.push(move)
        if after.is_checkmate():
            yield 100, move
        elif victim and board.is_capture(move):
            attacker = after.piece_at(move.to_square)
            recapture = any(reply.to_square == move.to_square for reply in after.generate_legal_captures())
            gain = VALUES[victim.piece_type] - (VALUES[attacker.piece_type] if recapture else 0)
            if gain > 0:
                yield gain, move


def threat_observation(history):
    board = history.board
    if board.is_check():
        king = chess.square_name(board.king(board.turn))
        return {"kind": "check", "text": "Vua của bạn đang bị chiếu, hãy chọn một nước đỡ chiếu hợp lệ.",
                "highlights": [king], "evidence": {"king": king}}
    as_if_passed = board.copy(stack=True)
    as_if_passed.push(chess.Move.null())
    old = {move: severity for severity, move in immediate_threats(history.before)}
    current = list(immediate_threats(as_if_passed))
    # Keep an existing mate threat visible. For material, focus on dangers
    # introduced or made more severe by the move the learner just saw.
    candidates = [(severity, move) for severity, move in current
                  if severity == 100 or severity > old.get(move, 0)]
    if not candidates:
        return {"kind": "noNewThreat",
                "text": "Chưa thấy nước chiếu hết ngay hoặc nước bắt quân có lợi rõ ràng mới xuất hiện.",
                "highlights": [], "evidence": {}}
    severity, move = max(candidates, key=lambda item: (item[0], item[1].uci()))
    san = as_if_passed.san(move)
    origin, target = chess.square_name(move.from_square), chess.square_name(move.to_square)
    if severity == 100:
        kind, text = "mateThreat", f"Đối thủ dọa {move_words(as_if_passed, move)} để chiếu hết."
    else:
        kind, text = "captureThreat", f"Đối thủ dọa {move_words(as_if_passed, move)}."
    return {"kind": kind, "text": text, "highlights": [origin, target],
            "evidence": {"san": san, "uci": move.uci(), "target": target}}


def first_hint(history):
    if history.board.is_check():
        return CHECK_HINT
    if history.last and threat_observation(history)["kind"] in ("mateThreat", "captureThreat"):
        return THREAT_HINT
    return QUIET_HINT


def candidate_text(board, move, variation):
    after = board.copy(stack=False)
    after.push(move)
    if after.is_checkmate():
        purpose = "nước này chiếu hết"
    elif board.is_castling(move):
        purpose = "nước này nhập thành và đưa xe vào cuộc"
    elif board.is_check():
        purpose = "nước này giúp vua thoát chiếu"
    elif board.is_capture(move):
        purpose = "hãy tính tiếp xem đối thủ có thể bắt lại hay không"
    elif after.is_check():
        purpose = "nước này buộc đối thủ đỡ chiếu"
    elif (board.piece_type_at(move.from_square) in (chess.KNIGHT, chess.BISHOP)
          and chess.square_rank(move.from_square) == (0 if board.turn else 7)
          and chess.square_rank(move.from_square) != chess.square_rank(move.to_square)):
        role = PIECES[chess.piece_name(board.piece_type_at(move.from_square))]
        purpose = f"nước này phát triển {role} khỏi hàng xuất phát"
    elif move.to_square in CENTER:
        purpose = "nước này đưa quân vào trung tâm"
    elif len(variation) > 1:
        purpose = "hãy xem nước đáp của đối thủ trong biến gợi ý"
    else:
        purpose = "hãy tự kiểm tra ý tưởng trước khi đi"
    return f"Thử {move_words(board, move)}. {purpose.capitalize()}."


def execute(raw: bytes, engine: Stockfish, provider=None) -> dict:
    import json
    data = json.loads(raw)
    if data.get("kind") == "analyseMove":
        job = AnalyseMove.model_validate(data)
        result = analyse_move(job, engine)
        history = validate_job(job)
        checked, insight = review_move(history, result["engine"], official_draw=job.snapshot.status == "draw")
        card = move_card(history, checked)
        if provider is not None and job.proactive:
            from .narrative import narrate
            card, metrics = narrate(provider, history, job.kind, card, checked)
            if metrics is not None:
                result["narration"] = metrics
        result.update(card=card, coachInsight=insight)
        if "practice" in checked:
            result["practice"] = checked["practice"]
        return result
    return answer(QuestionJob.model_validate(data), engine, provider)
