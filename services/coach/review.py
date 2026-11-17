"""One short observation about a played move, derived from replayed boards.

Every statement describes a rule fact or a concrete legal reply. No attack map
is promoted to a legal capture, forced material loss, safety or engine verdict.
"""

import chess

from chess_analysis.facts import rule_facts
from chess_analysis.history import History

PIECES = {"pawn": "tốt", "knight": "mã", "bishop": "tượng", "rook": "xe", "queen": "hậu", "king": "vua"}
VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
CENTER = chess.SquareSet([chess.D4, chess.E4, chess.D5, chess.E5])


def observation(history: History) -> dict:
    board, before, last = history.board, history.before, history.last
    facts = rule_facts(history)
    move = facts['lastMove']
    if not move or last is None:
        raise ValueError('missing historical move')
    learner = before.turn
    square = move['to']
    role = PIECES[move['promotion'] or move['piece']['role']]
    san = move['san']

    def result(kind, text, evidence=None, highlights=None):
        return {'kind': kind, 'evidence': evidence or {}, 'text': text,
                'highlights': highlights if highlights is not None else [square]}

    if facts['checkmate']:
        return result('mate', f'Nước {san} đã chiếu hết vua đối thủ và kết thúc ván cờ.')
    if facts['stalemate']:
        return result('stalemate', 'Đối thủ hết nước hợp lệ nhưng không bị chiếu, nên ván cờ hòa do hết nước đi.')
    if board.is_game_over(claim_draw=False) or board.is_fifty_moves():
        return result('draw', f'Sau {san}, thế cờ đã đạt điều kiện hòa theo luật.')
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
        name = PIECES[chess.piece_name(victim.piece_type)]
        text = (f'Đối thủ có nước {reply_san} bắt lại {name} sau {san}, nên hãy tính cả nước trả trước khi đổi quân.'
                if move['capture'] and reply.to_square == last.to_square else
                f'Sau {san}, đối thủ có thể dùng {reply_san} bắt {name} ở {target}, hãy kiểm tra quân này trước.')
        return result('legalReplyCapture', text,
                      {'uci': reply.uci(), 'san': reply_san, 'victim': chess.piece_name(victim.piece_type)},
                      [target, chess.square_name(reply.from_square)])
    if facts['check']:
        count = board.legal_moves.count()
        return result('checkReplies', f'Nước {san} buộc đối thủ đỡ chiếu với {count} cách đi hợp lệ.', {'replies': count})
    if before.is_check():
        return result('escapeCheck', f'Nước {san} đã giải được thế chiếu, hãy xem đối thủ còn có thể gây sức ép vào đâu.')
    if move['castling']:
        rook = ('f' if move['castling'] == 'kingSide' else 'd') + square[1]
        return result('castling', f'Nhập thành đưa vua tới {square} và xe tới {rook}, giúp bạn đưa xe vào cuộc.', {'rook': rook})

    # Castling rights are exact state changes, not a judgement of king safety.
    if before.has_castling_rights(learner) and not board.has_castling_rights(learner):
        return result('castlingRights', f'Sau {san}, bạn không còn quyền nhập thành, hãy tính cách phối hợp vua và xe.')

    for target, piece in sorted(board.piece_map().items(), key=lambda item: -VALUES[item[1].piece_type]):
        if piece.color == learner and board.is_pinned(learner, target):
            origin = last.from_square if target == last.to_square else target
            if not before.is_pinned(learner, origin):
                name, location = PIECES[chess.piece_name(piece.piece_type)], chess.square_name(target)
                return result('absolutePin', f'{name.capitalize()} ở {location} đang bị ghim vào vua, hãy kiểm tra tính hợp lệ trước khi di chuyển quân này.',
                              {'square': location, 'king': chess.square_name(board.king(learner))}, [location])

    if (before.is_attacked_by(not learner, last.from_square)
            and not board.is_attacked_by(not learner, last.to_square)):
        return result('leaveAttack', f'Nước {san} đưa {role} ra khỏi tầm tấn công trực tiếp ở {move["from"]}.',
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
                    f'Nước {san} đưa {name} ở {location} vào tầm tấn công của {role}, hãy tính phản ứng của đối thủ.')
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
                return result('openBishop', f'Nước {san} mở đường chéo cho tượng {name}, hãy tận dụng để phát triển quân.',
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
        captured = PIECES[move['capture']['role']]
        return result('capture', f'Nước {san} lấy {captured} mà đối thủ không có nước bắt lại hợp lệ ngay vào {square}.',
                      {'immediateRecaptures': []})
    if move['piece']['role'] == 'pawn':
        controlled = sorted(board.attacks(last.to_square))
        names = [chess.square_name(s) for s in controlled]
        return result('pawnControl', f'Tốt {square} kiểm soát {" và ".join(names)}, hãy tính cách dùng các ô này để hỗ trợ quân nhẹ.', {'squares': names})
    return result('quiet', f'Chưa có điểm nổi bật đã xác nhận ở nước {san}, bạn có thể hỏi gợi ý cho lượt tiếp theo.')


def move_card(history: History) -> dict:
    value = observation(history)
    return {key: value[key] for key in ('text', 'highlights')} | {'moves': []}
