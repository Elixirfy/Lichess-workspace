"""Bounded narration: model selects verified statements, never supplies new prose.

The catalog is built from a replayed position. Claim IDs alone prove nothing:
values AND the complete Vietnamese statement must match a catalog entry.
"""

import json
import time
from dataclasses import dataclass
from typing import Literal

import chess
from pydantic import Field

from chess_analysis.facts import rule_facts
from chess_analysis.history import History
from .contracts import Contract
from .review import observation

VERSION = "coach-claims-v2"
PIECES = {"pawn": "tốt", "knight": "mã", "bishop": "tượng", "rook": "xe", "queen": "hậu", "king": "vua"}


class Unit(Contract):
    factId: str = Field(min_length=1, max_length=40)
    claimType: Literal["lastMove", "check", "mate", "stalemate", "attack", "noDirectAttack"]
    values: dict = Field(max_length=16)
    text: str = Field(min_length=1, max_length=700)


class Draft(Contract):
    schemaVersion: Literal[1]
    units: list[Unit] = Field(min_length=1, max_length=1)


@dataclass(frozen=True)
class Statement:
    claim_type: str
    values: dict
    texts: tuple[str, ...]


def catalog(history: History, kind: str, card: dict) -> dict[str, Statement]:
    """Rule observations only; no eval/forced wins. Attack includes pinned attackers."""
    board = history.board
    facts = rule_facts(history)
    if kind == "explain":
        move = facts["lastMove"]
        if move is None:
            raise ValueError("missing move")
        claim_type = "mate" if facts["checkmate"] else "stalemate" if facts["stalemate"] else "lastMove"
        checked = observation(history)
        if card != {key: checked[key] for key in ('text', 'highlights')} | {'moves': []}:
            raise ValueError("unverified move observation")
        values = {"move": move, "check": facts["check"], "mate": facts["checkmate"], "stalemate": facts["stalemate"],
                  "observation": {key: checked[key] for key in ('kind', 'evidence')}}
    elif kind == "threat":
        if board.is_check():
            claim_type, values = "check", {"color": facts["turn"], "square": chess.square_name(board.king(board.turn))}
        elif card["highlights"]:
            square = card["highlights"][0]
            target = chess.parse_square(square)
            if not board.is_attacked_by(not board.turn, target):
                raise ValueError("unverified attack")
            piece = board.piece_at(target)
            claim_type, values = "attack", {
                "square": square, "role": chess.piece_name(piece.piece_type), "color": facts["turn"],
                "attackers": sorted(chess.square_name(s) for s in board.attackers(not board.turn, target)),
            }
        else:
            if any(p.color == board.turn and p.piece_type != chess.KING and board.is_attacked_by(not board.turn, s)
                   for s, p in board.piece_map().items()):
                raise ValueError("unverified absence of attacks")
            claim_type, values = "noDirectAttack", {"color": facts["turn"]}
    else:
        raise ValueError("narration unavailable for this kind")
    result = {"focus": Statement(claim_type, values, (card["text"],))}
    # One message, one sentence: never append a second turn announcement.
    return result


def verify(raw: str, statements: dict[str, Statement], *, kind: str, hint_level: int = 0) -> str:
    # Low hints never admit provider text (even if it cites a real move).
    if kind == "hint" or hint_level != 0:
        raise ValueError("provider hints forbidden")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result
    draft = Draft.model_validate(json.loads(raw, object_pairs_hook=unique))
    if draft.units[0].factId != "focus" or len({u.factId for u in draft.units}) != len(draft.units):
        raise ValueError("missing focus or duplicate claim")
    for unit in draft.units:
        expected = statements.get(unit.factId)
        if (expected is None or unit.claimType != expected.claim_type
                or json.dumps(unit.values, sort_keys=True, ensure_ascii=False) != json.dumps(expected.values, sort_keys=True, ensure_ascii=False)
                or unit.text not in expected.texts):
            raise ValueError("unsupported claim or statement")
    text = " ".join(unit.text for unit in draft.units)
    if len(text) > 800:
        raise ValueError("text limit")
    return text


def narrate(provider, history: History, kind: str, card: dict) -> tuple[dict, dict]:
    started = time.monotonic()
    deadline = started + provider.budget_seconds
    statements = catalog(history, kind, card)
    # Only chess facts and approved wording. No request/session/game/user IDs,
    # cookies, internal auth, full jobs or untrusted drafts in the prompt.
    context = {"version": VERSION, "kind": kind, "statements": {
        key: {"claimType": value.claim_type, "values": value.values, "texts": list(value.texts)}
        for key, value in statements.items()
    }, "schema": Draft.model_json_schema()}
    metrics = {"version": VERSION, "provider": provider.name, "model": provider.model,
               "attempts": 0, "promptTokens": 0, "completionTokens": 0,
               "usageKnown": True, "fallback": True, "reason": "budget"}
    for attempt in range(2):
        if time.monotonic() >= deadline:
            break
        metrics["attempts"] += 1
        received = False
        try:
            response = provider.complete(context, repair=attempt == 1, deadline=deadline)
            received = True
            usage = response.usage
            if usage is None:
                metrics["usageKnown"] = False
            else:
                metrics["promptTokens"] += usage[0]
                metrics["completionTokens"] += usage[1]
            text = verify(response.content, statements, kind=kind)
            if time.monotonic() >= deadline:
                break
            metrics.update(fallback=False, reason="accepted")
            metrics["elapsedMs"] = round((time.monotonic() - started) * 1000)
            return {**card, "text": text}, metrics
        except (ValueError, TypeError, KeyError):
            if not received:
                metrics["usageKnown"] = False
            metrics["reason"] = "verification"
        except Exception:
            metrics["usageKnown"] = False
            # Transport errors do not get a second call; retrying a timeout
            # would consume the remaining budget without a verifiable draft.
            metrics["reason"] = "providerUnavailable"
            break
    metrics["elapsedMs"] = round((time.monotonic() - started) * 1000)
    return card, metrics
