"""Replay server SAN and identify a position by its entire legal history.

Adapted from feature/commentary@02a6d45:services/commentary/chess_history.py.
"""

from dataclasses import dataclass
from hashlib import sha256
from typing import Sequence

import chess

REVISION_FORMAT = "coach-position-v1"
MAX_PLIES = 2000


def canonical_fen(board: chess.Board) -> str:
    """Full FEN, including clocks; only a legally capturable en-passant square."""
    return board.fen(en_passant="legal")


def parse_position(fen: str) -> chess.Board:
    if len(fen.split()) != 6:
        raise ValueError("expected full FEN")
    board = chess.Board(fen)
    if not board.is_valid():
        raise ValueError("invalid position")
    return board


def position_revision(initial_fen: str, uci_history: Sequence[str]) -> str:
    """Inputs must already be canonical and replayed (see replay).

    UTF-8 bytes, LF separators, UCI separated by one ASCII space, no final LF.
    No status, game ID, request ID or provider information participates.
    """
    value = f"{REVISION_FORMAT}\nstandard\n{initial_fen}\n{' '.join(uci_history)}"
    return sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class History:
    initial_fen: str
    board: chess.Board
    before: chess.Board
    last: chess.Move | None
    san: str | None
    uci_history: tuple[str, ...]
    revision: str


def replay(initial_fen: str, san_history: Sequence[str]) -> History:
    if len(san_history) > MAX_PLIES:
        raise ValueError("history too long")
    board = parse_position(initial_fen)
    initial = canonical_fen(board)
    before = board.copy(stack=True)
    last = None
    san = None
    ucis: list[str] = []
    for index, value in enumerate(san_history):
        # Lila automatically ends standard games at 100 reversible halfmoves;
        # python-chess otherwise waits for the FIDE 75-move automatic draw.
        if board.is_game_over(claim_draw=False) or board.is_fifty_moves():
            raise ValueError("history continues after terminal position")
        if index == len(san_history) - 1:
            before = board.copy(stack=True)
        last = board.parse_san(value)
        if last not in board.legal_moves:
            raise ValueError("illegal history move")
        san = board.san(last)
        if value != san:
            raise ValueError("expected canonical SAN")
        ucis.append(last.uci())
        board.push(last)
    history = tuple(ucis)
    return History(initial, board, before, last, san, history, position_revision(initial, history))
