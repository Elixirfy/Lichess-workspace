"""Verified chess statements with optional position-specific teaching questions."""

import json
import re
import time
from dataclasses import dataclass, replace
from typing import Literal

from pydantic import Field

from chess_analysis.facts import rule_facts
from chess_analysis.history import History
from .contracts import Contract
from .review import observation, move_card

VERSION = "coach-claims-v5"


class Unit(Contract):
    factId: str = Field(min_length=1, max_length=40)
    claimType: Literal["lastMove", "check", "mate", "stalemate",
                       "tacticalLoss", "materialGain", "mateThreat", "captureThreat", "noNewThreat"]
    values: dict = Field(max_length=16)
    text: str = Field(min_length=1, max_length=700)


class Draft(Contract):
    schemaVersion: Literal[1]
    units: list[Unit] = Field(min_length=1, max_length=1)
    followUp: str | None = Field(default=None, min_length=10, max_length=140)


class Selection(Contract):
    schemaVersion: Literal[2]
    textIndex: int = Field(ge=0)
    followUp: str | None = Field(default=None, min_length=10, max_length=140)


DRAFT_SCHEMA = Selection.model_json_schema()


@dataclass(frozen=True)
class Statement:
    claim_type: str
    values: dict
    texts: tuple[str, ...]
    teaching_patterns: tuple[str, ...] = ()


TEACHING_PATTERNS = {
    "openBishop": ("Bạn (muốn|có thể) dùng đường chéo này để (kiểm soát|gây sức ép lên) ô nào?",),
    "centralControl": ("Bạn (muốn|có thể) dùng các ô trung tâm này để (hỗ trợ|phát triển) quân nào?",),
    "legalReplyCapture": ("Bạn (sẽ|có thể) tính tiếp (nước bắt lại|cuộc đổi quân) như thế nào?",),
    "mateThreat": ("Bạn (sẽ|có thể) ngăn (nước chiếu hết này|mối đe dọa này) bằng cách nào?",),
    "captureThreat": ("Bạn (sẽ|có thể) (bảo vệ|di chuyển) quân này bằng cách nào?",),
    "materialGain": ("Bạn (sẽ|có thể) tìm (cơ hội bắt quân|quân không được bảo vệ) như thế nào?",),
    "check": ("Bạn (sẽ|có thể) (thoát chiếu|chặn nước chiếu) bằng cách nào?",),
    "castling": ("Bạn (sẽ|có thể) đưa xe vào cuộc bằng cách nào?",),
    "newAttack": ("Bạn (sẽ|có thể) đoán (cách phòng thủ|nước đáp) của đối thủ như thế nào?",),
}


def catalog(history: History, kind: str, card: dict, checked: dict | None = None) -> dict[str, Statement]:
    """Expose only evidence already checked by the board and the worker."""
    facts = rule_facts(history)
    if kind in ("explain", "analyseMove"):
        move = facts["lastMove"]
        if move is None:
            raise ValueError("missing move")
        claim_type = "mate" if facts["checkmate"] else "stalemate" if facts["stalemate"] else "lastMove"
        checked = observation(history) if checked is None else checked
        if card != move_card(history, checked):
            raise ValueError("unverified move observation")
        if checked["kind"] in ("tacticalLoss", "materialGain"):
            claim_type = checked["kind"]
        values = {"move": move, "check": facts["check"], "mate": facts["checkmate"], "stalemate": facts["stalemate"],
                  "observation": {key: checked[key] for key in ('kind', 'evidence')}}
    elif kind == "threat":
        if checked is None or card != move_card(history, checked):
            raise ValueError("unverified threat observation")
        claim_type, values = checked["kind"], checked["evidence"]
    else:
        raise ValueError("narration unavailable for this kind")
    pattern_key = checked["kind"]
    alternatives = checked.get("alternativeTexts", ())
    patterns = TEACHING_PATTERNS.get(pattern_key, ())
    return {"focus": Statement(claim_type, values, (card["text"], *alternatives), patterns)}


def valid_teaching_question(text: str, statement: Statement) -> bool:
    for pattern in statement.teaching_patterns:
        parts = re.split(r"\(([^()]+)\)", pattern)
        literal_or_choice = (
            "(" + "|".join(map(re.escape, part.split("|"))) + ")" if i % 2 else re.escape(part)
            for i, part in enumerate(parts)
        )
        if re.fullmatch("".join(literal_or_choice), text):
            return True
    return False


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
    data = json.loads(raw, object_pairs_hook=unique)
    expected = statements["focus"]
    if isinstance(data, dict) and data.get("schemaVersion") == 2:
        draft = Selection.model_validate(data)
        if draft.textIndex >= len(expected.texts):
            raise ValueError("unsupported text index")
        text = expected.texts[draft.textIndex]
    else:
        draft = Draft.model_validate(data)
        unit = draft.units[0]
        if (unit.factId != "focus" or unit.claimType != expected.claim_type
                or json.dumps(unit.values, sort_keys=True, ensure_ascii=False) != json.dumps(expected.values, sort_keys=True, ensure_ascii=False)
                or unit.text not in expected.texts):
            raise ValueError("unsupported claim or statement")
        text = unit.text
    if draft.followUp is not None:
        if not valid_teaching_question(draft.followUp, statements["focus"]):
            raise ValueError("unsupported teaching question")
        text += " " + draft.followUp
    if len(text) > 800:
        raise ValueError("text limit")
    return text


def narrate(provider, history: History, kind: str, card: dict, checked: dict | None = None) -> tuple[dict, dict | None]:
    started = time.monotonic()
    deadline = started + provider.budget_seconds
    statements = catalog(history, kind, card, checked)
    focus = statements["focus"]
    # A newly attacked piece gives the learner a concrete decision to think through.
    # Tactical warnings already have a direct explanation or a separate retry.
    if kind != "analyseMove" or not focus.values.get("observation", {}).get("kind") == "newAttack":
        focus = replace(focus, teaching_patterns=())
        statements["focus"] = focus
    if kind == "analyseMove" and not focus.teaching_patterns and len(focus.texts) == 1:
        return card, None
    # Only chess facts and approved wording. No request/session/game/user IDs,
    # cookies, internal auth, full jobs or untrusted drafts in the prompt.
    context = {"version": VERSION, "kind": kind, "statements": {
        key: {"claimType": value.claim_type, "values": value.values, "texts": list(value.texts),
              **({"teachingPatterns": value.teaching_patterns} if value.teaching_patterns else {})}
        for key, value in statements.items()
    }, "schema": DRAFT_SCHEMA}
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
