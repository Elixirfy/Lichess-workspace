import { attacks } from 'chessops/attacks';
import { castlingSide, type Chess } from 'chessops/chess';
import { SquareSet } from 'chessops/squareSet';
import type { Color, NormalMove, Role, Square } from 'chessops/types';
import { kingCastlesTo, makeSquare, opposite, parseSquare } from 'chessops/util';

export const pieceNames = {
  pawn: 'tốt',
  knight: 'mã',
  bishop: 'tượng',
  rook: 'xe',
  queen: 'hậu',
  king: 'vua',
};
export const colorNames = { white: 'Trắng', black: 'Đen' };
const pieceValues: Record<Role, number> = { pawn: 1, knight: 3, bishop: 3, rook: 5, queen: 9, king: 0 };
const center = ['d4', 'e4', 'd5', 'e5'].map(square => parseSquare(square)!);

interface Capture {
  move: NormalMove;
  attacker: Role;
  victim: Role;
  target: Square;
}

function captures(position: Chess): Capture[] {
  const result: Capture[] = [];
  const ctx = position.ctx();
  for (const from of position.board[position.turn]) {
    const attacker = position.board.getRole(from)!;
    const targets =
      attacker === 'pawn' && position.epSquare !== undefined
        ? position.board[opposite(position.turn)].with(position.epSquare)
        : position.board[opposite(position.turn)];
    for (const to of position.dests(from, ctx).intersect(targets)) {
      const target = position.board.has(to) ? to : to + (position.turn === 'white' ? -8 : 8);
      const victim = position.board.getRole(target)!;
      const promotion = attacker === 'pawn' && SquareSet.backranks().has(to) ? 'queen' : undefined;
      result.push({ move: { from, to, promotion }, attacker, victim, target });
    }
  }
  return result;
}

const pieceAt = (role: Role, square: Square) => `${pieceNames[role]} ở ${makeSquare(square)}`;
const capitalize = (text: string) => text[0].toUpperCase() + text.slice(1);

export function practiceFeedback(
  before: Chess,
  move: NormalMove,
  after: Chess,
  learner: Color,
): { text: string; capture?: NormalMove } {
  const mover = before.turn === learner ? 'Bạn' : colorNames[before.turn];
  const responder = before.turn === learner ? 'Đối thủ' : 'Bạn';
  if (after.isCheckmate()) {
    const king = makeSquare(after.board.kingOf(after.turn)!);
    return {
      text: `Chiếu hết. Vua ${colorNames[after.turn].toLowerCase()} ở ${king} không còn cách thoát chiếu.`,
    };
  }
  if (after.isStalemate())
    return { text: `Hòa do hết nước đi. ${colorNames[after.turn]} không bị chiếu và không còn nước hợp lệ.` };
  if (after.isInsufficientMaterial()) return { text: 'Hòa vì cả hai bên không còn đủ quân để chiếu hết.' };
  if (after.halfmoves >= 100) return { text: 'Nước này đạt mốc hòa theo luật 50 nước.' };

  const castle = castlingSide(before, move);
  const square = castle ? kingCastlesTo(before.turn, castle) : move.to;
  const piece = after.board.get(square)!;
  const label = capitalize(pieceAt(piece.role, square));
  const taken = castle
    ? undefined
    : (before.board.getRole(move.to) ??
      (piece.role === 'pawn' && move.to === before.epSquare ? 'pawn' : undefined));
  const start = move.promotion
    ? `${mover} phong tốt thành ${pieceNames[move.promotion]} ở ${makeSquare(square)}. `
    : castle
      ? `${mover} nhập thành, đưa vua và xe ra khỏi ô xuất phát. `
      : taken
        ? `${mover} bắt ${pieceNames[taken]} tại ${makeSquare(square)}. `
        : '';
  const check = after.isCheck() ? `${mover} chiếu vua. ${colorNames[after.turn]} phải đỡ chiếu. ` : '';

  const replies = captures(after);
  const danger = replies
    .filter(reply => reply.target === square || pieceValues[reply.victim] > pieceValues[reply.attacker])
    .sort(
      (a, b) =>
        pieceValues[b.victim] - pieceValues[b.attacker] - (pieceValues[a.victim] - pieceValues[a.attacker]) ||
        Number(b.target === square) - Number(a.target === square),
    )[0];
  if (danger) {
    const reply = after.clone();
    reply.play(danger.move);
    const retake = captures(reply).find(capture => capture.target === danger.move.to);
    const consequence = retake
      ? `${mover} có thể dùng ${pieceAt(retake.attacker, retake.move.from)} bắt lại ở ${makeSquare(retake.move.to)}.`
      : `${mover} không thể bắt lại ngay ${pieceNames[danger.move.promotion ?? danger.attacker]} đó.`;
    const warning =
      `${responder} có thể dùng ${pieceAt(danger.attacker, danger.move.from)} bắt ${pieceAt(danger.victim, danger.target)}` +
      (danger.move.promotion ? ' và phong hậu.' : '.');
    return { text: start + check + warning + ' ' + consequence, capture: danger.move };
  }

  if (check) return { text: (start + check).trimEnd() };
  if (start) {
    const captureNote = taken ? `${responder} không có nước bắt lại ngay ở ô đó.` : '';
    return { text: (start + captureNote).trimEnd() };
  }
  if (before.isCheck()) return { text: `${label} giúp ${colorNames[before.turn]} thoát chiếu.` };

  const controlled = attacks(piece, square, after.board.occupied);
  const added = controlled.diff(attacks(before.board.get(move.from)!, move.from, before.board.occupied));
  const targets = [...added.intersect(after.board[after.turn])]
    .map(target => pieceAt(after.board.getRole(target)!, target))
    .slice(0, 2);
  if (targets.length) return { text: `${label} tạo thêm sức ép lên ${targets.join(' và ')}.` };
  const central = center.filter(s => added.has(s)).map(makeSquare);
  if (central.length) return { text: `${label} kiểm soát thêm ${central.join(' và ')} ở trung tâm.` };

  const squares = [...added.diff(after.board.occupied)].slice(0, 2).map(makeSquare);
  if (squares.length) return { text: `${label} kiểm soát thêm ${squares.join(' và ')}.` };
  return {
    text: `${label} không bị bắt ngay. Từ ô mới, quân này chưa tạo thêm mối đe dọa trực tiếp.`,
  };
}
