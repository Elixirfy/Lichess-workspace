"""One short observation about a played move, derived from replayed boards.

Every statement describes a rule fact or a concrete legal reply. No attack map
is promoted to a legal capture, forced material loss, safety or engine verdict.
"""

import chess

from chess_analysis.engine import PRACTICE_PLIES
from chess_analysis.facts import rule_facts
from chess_analysis.history import History

PIECES = {"pawn": "tốt", "knight": "mã", "bishop": "tượng", "rook": "xe", "queen": "hậu", "king": "vua"}
VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
CENTER = chess.SquareSet([chess.D4, chess.E4, chess.D5, chess.E5])


def move_words(board: chess.Board, move: chess.Move, *, recapture=False) -> str:
    """Describe a legal move from its board, including both squares when relevant."""
    if board.is_castling(move):
        return "nhập thành cánh vua" if board.is_kingside_castling(move) else "nhập thành cánh hậu"
    piece = board.piece_at(move.from_square)
    role = PIECES[chess.piece_name(piece.piece_type)]
    origin, target = chess.square_name(move.from_square), chess.square_name(move.to_square)
    if board.is_capture(move):
        victim = "tốt" if board.is_en_passant(move) else PIECES[chess.piece_name(board.piece_type_at(move.to_square))]
        verb = "bắt lại" if recapture else "bắt"
        action = f"dùng {role} ở {origin} {verb} {victim} tại {target}"
        if board.is_en_passant(move):
            action += " bằng nước bắt tốt qua đường"
    elif piece.piece_type == chess.PAWN:
        direction = "lên" if piece.color == chess.WHITE else "xuống"
        action = f"đẩy tốt từ {origin} {direction} {target}"
    else:
        action = f"đưa {role} từ {origin} đến {target}"
    if move.promotion:
        action += f" và phong thành {PIECES[chess.piece_name(move.promotion)]}"
    return action


def observation(history: History) -> dict:
    board, before, last = history.board, history.before, history.last
    facts = rule_facts(history)
    move = facts['lastMove']
    if not move or last is None:
        raise ValueError('missing historical move')
    learner = before.turn
    square = move['to']
    role = PIECES[move['promotion'] or move['piece']['role']]
    played = move_words(before, last)

    def result(kind, text, evidence=None, highlights=None):
        return {'kind': kind, 'evidence': evidence or {}, 'text': text,
                'highlights': highlights if highlights is not None else [square]}

    if facts['checkmate']:
        return result('mate', f'Chiếu hết rồi! Bạn {played} và vua đối thủ hết cách thoát chiếu.')
    if facts['stalemate']:
        return result('stalemate', 'Đối thủ hết nước hợp lệ nhưng không bị chiếu, nên ván cờ hòa do hết nước đi.')
    if board.is_game_over(claim_draw=False) or board.is_fifty_moves():
        return result('draw', f'Sau khi bạn {played}, thế cờ đã đạt điều kiện hòa theo luật.')
    if move['promotion']:
        return result('promotion', f'Tốt đã thành {role} ở {square}, hãy tính lại các nước chiếu và bắt quân từ quân mới.')

    # Only the real side to move is allowed to supply a capture. In particular,
    # pinned attackers and illegal king captures cannot become warning claims.
    replies = []
    for reply in board.generate_legal_captures():
        victim = board.piece_at(reply.to_square)
        attacker = board.piece_at(reply.from_square)
        if (victim and victim.color == learner and victim.piece_type != chess.KING
                and (victim.piece_type != chess.PAWN or (move['capture'] and reply.to_square == last.to_square))):
            replies.append((VALUES[victim.piece_type], reply.to_square == last.to_square,
                            -VALUES[attacker.piece_type], reply.uci(), reply, victim))
    if replies:
        *_, reply, victim = max(replies, key=lambda item: item[:4])
        reply_san = board.san(reply)
        target = chess.square_name(reply.to_square)
        is_recapture = bool(move['capture'] and reply.to_square == last.to_square)
        reply_words = move_words(board, reply, recapture=is_recapture)
        text = f'Đối thủ có thể {reply_words}. Hãy để ý nước bắt này khi tính tiếp.'
        return result('legalReplyCapture', text,
                      {'uci': reply.uci(), 'san': reply_san, 'victim': chess.piece_name(victim.piece_type)},
                      [target, chess.square_name(reply.from_square)])
    if facts['check']:
        count = board.legal_moves.count()
        return result('checkReplies', f'Bạn {played} và chiếu vua. Đối thủ có {count} cách đỡ chiếu.', {'replies': count})
    if before.is_check():
        return result('escapeCheck', f'Bạn đã thoát chiếu bằng cách {played}.')
    if move['castling']:
        rook = ('f' if move['castling'] == 'kingSide' else 'd') + square[1]
        return result('castling', f'Nhập thành đưa vua tới {square} và xe tới {rook}, giúp bạn đưa xe vào cuộc.', {'rook': rook})

    # Castling rights are exact state changes, not a judgement of king safety.
    if before.has_castling_rights(learner) and not board.has_castling_rights(learner):
        return result('castlingRights', f'Sau khi bạn {played}, bạn không còn quyền nhập thành.')

    for target, piece in sorted(board.piece_map().items(), key=lambda item: -VALUES[item[1].piece_type]):
        if piece.color == learner and board.is_pinned(learner, target):
            origin = last.from_square if target == last.to_square else target
            if not before.is_pinned(learner, origin):
                name, location = PIECES[chess.piece_name(piece.piece_type)], chess.square_name(target)
                return result('absolutePin', f'{name.capitalize()} ở {location} đang bị ghim vào vua, hãy kiểm tra tính hợp lệ trước khi di chuyển quân này.',
                              {'square': location, 'king': chess.square_name(board.king(learner))}, [location])

    if (before.is_attacked_by(not learner, last.from_square)
            and not board.is_attacked_by(not learner, last.to_square)):
        return result('leaveAttack', f'Bạn đã {played} để rời khỏi tầm tấn công trực tiếp ở {move["from"]}.',
                      {'attackersBefore': sorted(chess.square_name(s) for s in before.attackers(not learner, last.from_square))})

    # Only say a new target is attacked when this piece did not attack it from
    # its previous square. Attack remains a geometric relation, not a capture.
    added = board.attacks(last.to_square) - before.attacks(last.from_square)
    targets = [(VALUES[p.piece_type], s, p) for s in added
               if (p := board.piece_at(s)) and p.color != learner and p.piece_type != chess.KING]
    if targets:
        value, target, piece = max(targets, key=lambda item: item[:2])
        king = board.king(not learner)
        if value >= 3 or (king is not None and chess.square_distance(target, king) <= 1):
            location, name = chess.square_name(target), PIECES[chess.piece_name(piece.piece_type)]
            text = (f'{role.capitalize()} ở {square} đang nhắm vào {name} {location} cạnh vua đối thủ, hãy xem cách phối hợp thêm quân.'
                    if king is not None and chess.square_distance(target, king) <= 1 else
                    f'{role.capitalize()} ở {square} vừa nhắm vào {name} ở {location}. Hãy để ý cách đối thủ bảo vệ quân này.')
            return result('newAttack', text,
                          {'target': location, 'role': chess.piece_name(piece.piece_type)}, [square, location])

    home_rank = 0 if learner else 7
    undeveloped = [chess.square_name(s) for s, p in sorted(board.piece_map().items())
                   if p.color == learner and p.piece_type in (chess.KNIGHT, chess.BISHOP)
                   and chess.square_rank(s) == home_rank]
    if board.fullmove_number <= 10 and undeveloped:
        if move['piece']['role'] == 'queen':
            return result('earlyQueen', f'Hậu đã ra {square} khi quân nhẹ ở {undeveloped[0]} còn ở hàng xuất phát, đừng quên phát triển các quân đó.',
                          {'undeveloped': undeveloped})
        if (move['piece']['role'] in ('knight', 'bishop') and len(before.move_stack) >= 2
                and before.move_stack[-2].to_square == last.from_square):
            return result('repeatDevelopment', f'Bạn đi cùng một {role} hai lượt liên tiếp trong khi quân nhẹ ở {undeveloped[0]} còn ở hàng xuất phát.',
                          {'previousOwnMove': before.move_stack[-2].uci(), 'undeveloped': undeveloped})

    if move['piece']['role'] == 'pawn':
        same_file = sorted(s for s in chess.SquareSet(board.pawns & board.occupied_co[learner])
                           if chess.square_file(s) == chess.square_file(last.to_square))
        if len(same_file) >= 2:
            names = [chess.square_name(s) for s in same_file]
            return result('doubledPawns', f'Các tốt {" và ".join(names)} đang cùng một cột, hãy tính cách phối hợp quân để hỗ trợ chúng.', {'pawns': names})

    for origin in sorted(chess.SquareSet(board.bishops & board.occupied_co[learner])):
        if before.piece_at(origin) == board.piece_at(origin) and origin != last.to_square:
            opened = board.attacks(origin) - before.attacks(origin)
            if len(opened) >= 2:
                name = chess.square_name(origin)
                return result('openBishop', f'Bạn {played}, mở đường chéo cho tượng {name}.',
                              {'bishop': name, 'opened': sorted(chess.square_name(s) for s in opened)}, [square, name])

    central = sorted(added & CENTER)
    if central:
        names = [chess.square_name(s) for s in central]
        return result('centralControl', f'{role.capitalize()} ở {square} vừa kiểm soát thêm {" và ".join(names)}, giúp bạn tranh chấp trung tâm.', {'squares': names})
    if move['piece']['role'] == 'rook':
        pawns = [s for s in chess.SquareSet(board.pawns) if chess.square_file(s) == chess.square_file(last.to_square)]
        if not pawns:
            file = chess.FILE_NAMES[chess.square_file(last.to_square)]
            return result('openFile', f'Xe {square} đã đứng trên cột {file} không còn tốt, hãy tìm cách phối hợp xe với các quân khác.', {'file': file})
    if move['capture']:
        return result('capture', f'Bạn {played}. Đối thủ chưa có nước bắt lại ngay tại {square}.',
                      {'immediateRecaptures': []})
    if move['piece']['role'] == 'pawn':
        controlled = sorted(board.attacks(last.to_square))
        names = [chess.square_name(s) for s in controlled]
        return result('pawnControl', f'Tốt {square} kiểm soát {" và ".join(names)}, hãy tính cách dùng các ô này để hỗ trợ quân nhẹ.', {'squares': names})
    return result('quiet', f'Sau khi bạn {played}, hãy để ý đối thủ có thể chiếu vua hoặc bắt quân ở đâu.')


def move_card(history: History, value: dict | None = None) -> dict:
    if value is None:
        value = observation(history)
    return {key: value[key] for key in ('text', 'highlights')} | {'moves': []}


def checked_candidate(board, score):
    line = score.get("pv", [])
    if not line:
        return None
    first = line[0]
    move = chess.Move.from_uci(first["uci"])
    return move if move in board.legal_moves and board.san(move) == first["san"] else None


def reply_targets(board, reply, *, all_targets=False):
    """Name pieces newly attacked by the replying piece, in board order."""
    after = board.copy(stack=False)
    after.push(reply)
    if not after.piece_at(reply.to_square) or after.is_pinned(board.turn, reply.to_square):
        return []
    attacks = after.attacks(reply.to_square)
    if not all_targets:
        attacks -= board.attacks(reply.from_square)
    return [f"{PIECES[chess.piece_name(piece.piece_type)]} ở {chess.square_name(square)}"
            for square in sorted(attacks)
            if (piece := after.piece_at(square)) and piece.color == after.turn
            and (all_targets or piece.piece_type not in (chess.PAWN, chess.KING))]


def practice_line(board, move, reply, text):
    moves = [{"san": board.san(move), "uci": move.uci()}]
    if reply:
        after = board.copy(stack=False)
        after.push(move)
        moves.append({"san": after.san(reply), "uci": reply.uci()})
    return {"moves": moves, "text": text}


def practice_benefit(history, after, move, reply, victim, targets, mate, allows_mate):
    if after.is_checkmate():
        return "Nước này chiếu hết."
    if (mate or 0) > 0:
        text = "Nước này mở đầu cách chiếu hết."
        replies = after.legal_moves.count()
        if replies == 1:
            return text + " Đối thủ chỉ có một nước đáp hợp lệ."
        if after.is_check():
            return text + f" Đối thủ có {replies} cách đỡ chiếu."
        return text
    if victim and (after.piece_at(reply.to_square) != victim or reply not in after.legal_moves):
        target = chess.square_name(reply.to_square)
        piece = PIECES[chess.piece_name(victim.piece_type)]
        attacker = history.board.piece_at(reply.from_square)
        if attacker and after.piece_at(reply.from_square) == attacker:
            name = PIECES[chess.piece_name(attacker.piece_type)].capitalize()
            return f"{name} ở {chess.square_name(reply.from_square)} hết nước bắt {piece} tại {target}."
        return f"Nước bắt {piece} tại {target} không còn sau phương án này."
    if len(targets) == 2 and reply in after.legal_moves and not after.is_capture(reply):
        if len(reply_targets(after, reply)) < len(targets):
            remaining = reply_targets(after, reply, all_targets=True)
            subject = "con tốt" if after.piece_type_at(reply.from_square) == chess.PAWN else "quân đó"
            consequence = (f"{subject} chỉ tấn công {remaining[0]}" if len(remaining) == 1 else
                           f"{subject} tấn công {' và '.join(remaining)}" if remaining else
                           "hai quân đã thoát đòn tấn công cùng lúc")
            return f"Nếu đối thủ {move_words(after, reply)}, {consequence}."
    if allows_mate:
        return "Phương án này tránh thế bị chiếu hết của nước đã đi."
    if after.is_check():
        return "Nước chiếu buộc đối thủ phải lo đỡ vua."
    if history.before.is_capture(move) and not any(
        capture.to_square == move.to_square for capture in after.generate_legal_captures()
    ):
        return f"Đối thủ chưa có nước bắt lại ngay tại {chess.square_name(move.to_square)}."
    central = (after.attacks(move.to_square) - history.before.attacks(move.from_square)) & CENTER
    if central:
        squares = " và ".join(chess.square_name(square) for square in central)
        return f"Nước này kiểm soát thêm {squares} ở trung tâm."
    return "Phương án này giữ thế cờ tốt hơn so với nước đã đi."


def practice_for(history, engine, reply, played_text, targets, missed_mate, allows_mate):
    candidates = engine.get("verifiedCandidates", [])
    if not candidates or candidates[0].get("bound"):
        return None
    best = candidates[0]
    victim = history.board.piece_at(reply.to_square) if reply and history.board.is_capture(reply) else None
    alternatives = []
    seen = {history.last}
    for score in candidates[:3]:
        move = checked_candidate(history.before, score)
        if move is None or move in seen or score.get("bound"):
            continue
        mate = score.get("mate")
        cp = score.get("cp")
        if best.get("mate") and best["mate"] > 0:
            eligible = mate is not None and mate > 0
        elif allows_mate:
            eligible = cp is not None and best.get("cp") is not None and cp >= best["cp"] - 45
        else:
            played_cp = engine["after"].get("cp")
            eligible = (cp is not None and best.get("cp") is not None and cp >= best["cp"] - 45
                        and played_cp is not None and cp - played_cp >= 120)
        if not eligible:
            continue
        seen.add(move)
        after = history.before.copy(stack=True)
        after.push(move)
        alternative_reply = checked_candidate(after, {"pv": score["pv"][1:]})
        if not alternative_reply and not after.is_game_over(claim_draw=False) and not after.is_fifty_moves():
            continue
        lead = move_words(history.before, move)
        benefit = practice_benefit(history, after, move, reply, victim, targets, mate, allows_mate)
        text = f"Bạn có thể {lead}. {benefit}"
        if (mate or 0) > 0:
            alternatives.append({"moves": score["pv"][:PRACTICE_PLIES], "text": text})
        else:
            alternatives.append(practice_line(history.before, move, alternative_reply, text))
    if not alternatives:
        return None
    prompt = ("Tìm lại nước bắt đầu cách chiếu hết." if missed_mate else
              "Tìm một nước giúp vua tránh nguy cơ bị chiếu hết." if allows_mate else
              "Thử tìm một nước giúp bạn giữ thế cờ tốt hơn.")
    return {"version": 3, "prompt": prompt, "played": practice_line(history.before, history.last, reply, played_text),
            "alternatives": alternatives}


def review_move(history, engine, *, official_draw=False):
    """Return the public observation and the evidence used to rank it."""
    rule = observation(history)
    if official_draw:
        rule = {"kind": "draw", "text": "Ván cờ kết thúc hòa theo luật.",
                "highlights": [], "evidence": {}}
    kind = rule["kind"]
    if kind in ("mate", "stalemate", "draw"):
        insight = {"kind": kind, "importance": 1100 if kind != "draw" else 250}
        if kind != "draw":
            insight["lesson"] = kind
        return rule, insight
    before, after = engine.get("before", {}), engine.get("after", {})
    loss = engine.get("cpLoss")
    before_mate, after_mate = before.get("mate"), after.get("mate")
    bounded = before.get("bound") or after.get("bound")
    reply = checked_candidate(history.board, after)
    alternative = checked_candidate(history.before, before)
    alternative = alternative if alternative != history.last else None
    missed_mate = alternative is not None and (before_mate or 0) > 0 and (after_mate or 0) <= 0
    allows_mate = reply is not None and (after_mate or 0) < 0 and (before_mate or 0) >= 0
    if not bounded and (allows_mate or missed_mate or (loss is not None and loss >= 120)):
        played = move_words(history.before, history.last)
        alternative_words = move_words(history.before, alternative) if alternative else None
        if allows_mate:
            text = f"Sau khi bạn {played}, Stockfish tìm thấy cách chiếu hết cho đối thủ."
            lesson, importance = "king", 1000
        elif missed_mate:
            text = f"Bạn đã bỏ lỡ cơ hội chiếu hết khi {played}."
            lesson, importance = "missed", 900
        else:
            text = f"Theo Stockfish, thế cờ khó hơn sau khi bạn {played}."
            lesson, importance = ("reply" if reply and history.board.is_capture(reply) else "compare"), min(loss, 800)
        reply_words = None
        targets = []
        if reply:
            recapture = history.before.is_capture(history.last) and reply.to_square == history.last.to_square
            reply_words = move_words(history.board, reply, recapture=recapture)
            if not history.board.is_capture(reply):
                targets = reply_targets(history.board, reply)[:2]
                if len(targets) == 2:
                    reply_words += f", tấn công cả {targets[0]} lẫn {targets[1]}"
                elif targets:
                    reply_words += f", tấn công {targets[0]}"
            reply_sentence = f"Đối thủ có thể {reply_words}."
            if not (allows_mate or missed_mate) and (targets or history.board.is_capture(reply)):
                text = f"Sau khi bạn {played}, đối thủ có thể {reply_words}."
            else:
                text += " " + reply_sentence
        option = f" Bạn có thể cân nhắc {alternative_words}." if alternative_words else ""
        if missed_mate and alternative_words:
            option = f" Biến chiếu hết bắt đầu bằng cách {alternative_words}."
        highlights = ([chess.square_name(reply.from_square), chess.square_name(reply.to_square)]
                      if reply else rule["highlights"])
        evidence = {"played": played, "reply": reply_words, "alternative": alternative_words, "cpLoss": loss,
                    "beforeMate": before_mate, "afterMate": after_mate, "targets": targets}
        practice = practice_for(history, engine, reply, text, targets, missed_mate, allows_mate)
        ending = "" if practice else option
        checked = {"kind": "tacticalLoss", "text": text + ending, "highlights": highlights, "evidence": evidence}
        if practice:
            checked["practice"] = practice
        if reply_words and (targets or history.board.is_capture(reply)) and not (allows_mate or missed_mate):
            checked["alternativeTexts"] = [f"Đối thủ có thể {reply_words}." + ending]
        return checked, {"kind": "tacticalLoss", "importance": importance, "lesson": lesson}
    captured = history.before.piece_at(history.last.to_square)
    if (not bounded and captured and VALUES[captured.piece_type] >= 3 and loss is not None and loss <= 45
            and (after.get("cp") or 0) >= 100
            and not any(m.to_square == history.last.to_square for m in history.board.generate_legal_captures())):
        played = move_words(history.before, history.last)
        square = chess.square_name(history.last.to_square)
        name = PIECES[chess.piece_name(captured.piece_type)]
        ending = f"Đối thủ chưa có nước bắt lại ngay tại {square}."
        checked = {"kind": "materialGain", "text": f"Hay, bạn đã {played}. {ending}",
                   "highlights": [square], "evidence": {"played": played, "captured": name, "square": square},
                   "alternativeTexts": [f"Bạn tận dụng tốt cơ hội khi {played}. {ending}"]}
        return checked, {"kind": "materialGain", "importance": 100 + VALUES[captured.piece_type],
                         "lesson": "loosePiece"}
    if kind == "promotion":
        return rule, {"kind": kind, "importance": 100, "lesson": "promotion"}
    steady = not bounded and loss is not None and loss <= 45
    incomplete_scores = loss is None and before.get("cp") is not None and after.get("cp") is not None
    if steady or incomplete_scores:
        if kind == "openBishop":
            bishop = rule["evidence"]["bishop"]
            point = f"Mở đường chéo cho tượng {bishop} là điểm tốt của nước này."
            rule["text"] = (f"Tốt, bạn đã mở đường chéo cho tượng {bishop}. Tượng có thêm chỗ để phát triển."
                            if steady else point)
            rule["alternativeTexts"] = [
                f"{point} Bạn có thể tính chuyện đưa tượng ra."
            ]
        elif kind == "centralControl":
            rule["alternativeTexts"] = [rule["text"]]
            squares = " và ".join(rule["evidence"]["squares"])
            piece = history.board.piece_at(history.last.to_square)
            name = PIECES[chess.piece_name(piece.piece_type)]
            rule["text"] = f"Điểm tốt là {name} của bạn vừa kiểm soát thêm {squares} ở trung tâm."
        elif kind == "castling":
            rule["alternativeTexts"] = [rule["text"]]
            rule["text"] = f"Một điểm tốt của nước nhập thành là xe được đưa về {rule['evidence']['rook']}."
    return rule, {"kind": kind, "importance": 0}
