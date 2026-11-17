"""Rule facts only. An attack is not proof of a forced capture or material win.

Move/capture extraction adapted from commentary/core.py at 02a6d45.
"""

import chess

from .history import History, canonical_fen


def color_name(color: chess.Color) -> str:
    return "white" if color else "black"


def piece_value(piece: chess.Piece | None) -> dict | None:
    if piece is None:
        return None
    return {"color": color_name(piece.color), "role": chess.piece_name(piece.piece_type)}


def rule_facts(history: History) -> dict:
    board, before, last = history.board, history.before, history.last
    values = {
        "source": f"python-chess:{chess.__version__}",
        "fen": canonical_fen(board),
        "turn": color_name(board.turn),
        "check": board.is_check(),
        "checkmate": board.is_checkmate(),
        "stalemate": board.is_stalemate(),
        "pieces": [
            {"square": chess.square_name(square), **piece_value(piece)}
            for square, piece in sorted(board.piece_map().items())
        ],
        # These are rule attack relations, including pinned attackers. Consumers
        # must not describe them as legal captures or guaranteed protection.
        "attacks": [
            {"from": chess.square_name(square), "to": chess.square_name(target)}
            for square in sorted(board.piece_map())
            for target in sorted(board.attacks(square))
        ],
        "lastMove": None,
    }
    if last is not None:
        captured = before.piece_at(last.to_square)
        en_passant = before.is_en_passant(last)
        if en_passant:
            captured = chess.Piece(chess.PAWN, not before.turn)
        values["lastMove"] = {
            "uci": last.uci(),
            "san": history.san,
            "ply": board.ply(),
            "mover": color_name(before.turn),
            "piece": piece_value(before.piece_at(last.from_square)),
            "from": chess.square_name(last.from_square),
            "to": chess.square_name(last.to_square),
            "capture": piece_value(captured),
            "enPassant": en_passant,
            "castling": (
                "kingSide" if before.is_kingside_castling(last) else "queenSide"
            ) if before.is_castling(last) else None,
            "promotion": chess.piece_name(last.promotion) if last.promotion else None,
        }
    return values
