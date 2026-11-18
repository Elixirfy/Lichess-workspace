import { square, type Board } from 'lib/game';

const roles: Record<string, string> = {
  tốt: 'P',
  mã: 'N',
  ngựa: 'N',
  tượng: 'B',
  tịnh: 'B',
  xe: 'R',
  hậu: 'Q',
  vua: 'K',
};
const files: Record<string, string> = {
  a: 'a',
  b: 'b',
  bê: 'b',
  bờ: 'b',
  bi: 'b',
  c: 'c',
  xê: 'c',
  d: 'd',
  dê: 'd',
  đê: 'd',
  dờ: 'd',
  đờ: 'd',
  đi: 'd',
  giờ: 'd', // Observed secondary ASR spelling of spoken dờ; scoped below.
  e: 'e',
  ê: 'e',
  f: 'f',
  ép: 'f',
  g: 'g',
  gờ: 'g',
  giê: 'g',
  h: 'h',
  hát: 'h',
  hờ: 'h',
};
const ranks: Record<string, string> = {
  một: '1',
  hai: '2',
  ba: '3',
  bốn: '4',
  tư: '4',
  năm: '5',
  sáu: '6',
  bảy: '7',
  tám: '8',
};

// Parse a small explicit language, then filter authoritative legal moves. Never
// discard arbitrary words, guess a rank, or ignore a conflicting piece/color.
export function vietnameseMoveCandidates(
  phrase: string,
  legal: readonly Uci[],
  board: Board,
): Uci[] | undefined {
  const words = phrase
    .normalize('NFC')
    .toLowerCase()
    .replace(/([a-hê])([1-8])/gu, '$1 $2')
    .trim()
    .split(/\s+/);
  let at = 0;
  const take = (...part: string[]) => {
    if (!part.every((word, index) => words[at + index] === word)) return false;
    at += part.length;
    return true;
  };
  const rankAt = (index: number) =>
    ranks[words[index]] ?? (/^[1-8]$/.test(words[index] ?? '') ? words[index] : undefined);
  // A rank after "đi" can denote English D in a coordinate. Otherwise the
  // word keeps its existing move-verb meaning.
  const takeGo = () => !(words[at] === 'đi' && rankAt(at + (words[at + 1] === 'hàng' ? 2 : 1))) && take('đi');
  let bareEnglishD = false;
  let bareSoundD = false;
  const readSquare = (): Key | undefined => {
    const start = at;
    take('ô');
    const column = take('cột');
    const fileWord = words[at];
    let file = files[words[at]];
    const numericFile = column && !file;
    if (numericFile) {
      const number = rankAt(at);
      if (number) file = String.fromCharCode(96 + Number(number));
    }
    if (!file) {
      at = start;
      return undefined;
    }
    at++;
    const namedRank = take('hàng');
    const rank = rankAt(at);
    if (!rank || (numericFile && !namedRank)) {
      at = start;
      return undefined;
    }
    at++;
    if (!column && fileWord === 'đi') bareEnglishD = true;
    if (!column && fileWord === 'giờ') bareSoundD = true;
    return (file + rank) as Key;
  };
  const readLink = () => {
    if (take('ăn')) {
      take('ở') || take('tại');
      return 'capture';
    }
    const moving = takeGo() || take('tiến') || take('nhảy');
    if (['đến', 'tới', 'sang', 'lên'].some(word => take(word)) || moving) return 'move';
    return undefined;
  };

  const verb = take('di', 'chuyển') || take('đưa') || take('cho') || take('đẩy') || takeGo();
  const namedPiece = take('quân') || take('con');
  const role = roles[words[at]];
  if (role) at++;
  else if (namedPiece) return [];
  let color: Color | undefined;
  if (role) {
    const namedColor = take('màu');
    if (take('trắng')) color = 'white';
    else if (take('đen')) color = 'black';
    else if (namedColor) return [];
    takeGo();
  }
  const fromMarker = take('từ') || take('ở') || take('tại');
  const firstLink = readLink();
  if (fromMarker && firstLink) return [];
  const first = readSquare();
  if (!first) return undefined;
  const secondLink = readLink();
  const second = readSquare();
  if ((firstLink && (secondLink || second)) || (secondLink && !second) || (fromMarker && !second)) return [];

  let promotion: string | undefined;
  let promote = take('phong');
  if (promote) take('cấp');
  if (take('thành')) promote = true;
  if (promote) {
    promotion = roles[words[at++]];
    if (!promotion || !'QRBN'.includes(promotion)) return [];
  }
  if (at !== words.length) return undefined;
  // "vua đi một" can mean "move one", not d1. Require a labelled column
  // or a complete source/destination pair before treating this word as D.
  if (bareEnglishD && !second) return [];
  // A clock expression is not a coordinate. Require a named chess piece and
  // two full squares for the unlabelled ASR spelling of dờ.
  if (bareSoundD && (!role || !second)) return [];
  // Keep upstream's source-square selection and destination ambiguity behavior.
  if (!second && !verb && !role && !firstLink && !promotion) return undefined;

  const from = second ? first : undefined;
  const to = second ?? first;
  const capture = firstLink === 'capture' || secondLink === 'capture';
  return legal
    .filter(uci => {
      if (uci.length !== 4 || uci.slice(2) !== to || (from && uci.slice(0, 2) !== from)) return false;
      const piece = board.pieces[square(uci.slice(0, 2))];
      if (!piece) return false;
      const actualColor = piece === piece.toUpperCase() ? 'white' : 'black';
      if ((role && piece.toUpperCase() !== role) || (color && actualColor !== color)) return false;
      if (promotion && (piece.toUpperCase() !== 'P' || !'18'.includes(to[1]))) return false;
      if (capture) {
        const target = board.pieces[square(to)];
        if (target) {
          if ((target === target.toUpperCase()) === (actualColor === 'white')) return false;
        } else if (piece.toUpperCase() !== 'P' || uci.startsWith(uci[2])) return false;
        // Empty diagonal pawn captures are en passant only because `legal` comes from the board.
      }
      return true;
    })
    .map(uci => (promotion ? `${uci}${promotion}` : uci));
}

// Select an acoustic retry, not a text correction. A misplaced từ can trigger
// another decode but remains invalid in the actual move parser. Labelled,
// numeric, unknown and negated input never enter this short-command grammar.
export function vietnameseShortGrammar(heard: string, phrases: readonly string[]): string[] {
  const words = heard.normalize('NFC').toLowerCase().trim().split(/\s+/);
  const role = words[0];
  if (!roles[role] || ![5, 6].includes(words.length)) return [];
  const end = words.length - 2;
  if (
    !files[words[1]] ||
    !ranks[words[2]] ||
    !files[words[end]] ||
    !ranks[words[end + 1]] ||
    (words.length === 6 && !['từ', 'tới', 'đến'].includes(words[3]))
  )
    return [];
  const short: string[] = [];
  for (const phrase of phrases) {
    const match = phrase.match(/^(\S+) từ cột (\S+) hàng (\S+) đến cột (\S+) hàng (\S+)$/u);
    if (!match || match[1] !== role || !files[match[2]] || !files[match[4]]) continue;
    const from = `${match[2]} ${match[3]}`;
    const to = `${match[4]} ${match[5]}`;
    short.push(`${role} ${from} ${to}`, `${role} ${from} tới ${to}`, `${role} ${from} đến ${to}`);
  }
  return short.length ? [...new Set([...short, 'đừng', 'không', '[unk]'])] : [];
}

// Representative templates keep Vosk context finite. The deterministic parser
// also accepts the documented synonyms when secondary ASR supplies them.
export function vietnameseMovePhrases(legal: readonly Uci[], board: Board): string[] {
  const names: Record<string, string> = { P: 'tốt', N: 'mã', B: 'tượng', R: 'xe', Q: 'hậu', K: 'vua' };
  const fileNames = ['a', 'bê', 'xê', 'đê', 'e', 'ép', 'gờ', 'hát'];
  const rankNames = ['một', 'hai', 'ba', 'bốn', 'năm', 'sáu', 'bảy', 'tám'];
  const saySquare = (key: string) => `${fileNames[key.charCodeAt(0) - 97]} ${rankNames[Number(key[1]) - 1]}`;
  const sayExplicit = (key: string, numbered = false) =>
    `cột ${numbered ? rankNames[key.charCodeAt(0) - 97] : fileNames[key.charCodeAt(0) - 97]} hàng ${rankNames[Number(key[1]) - 1]}`;
  const phrases: string[] = [];
  for (const uci of legal) {
    if (uci.length !== 4) continue;
    const piece = board.pieces[square(uci.slice(0, 2))];
    if (!piece || !names[piece.toUpperCase()]) continue;
    const role = names[piece.toUpperCase()];
    const color = piece === piece.toUpperCase() ? 'trắng' : 'đen';
    const from = saySquare(uci.slice(0, 2));
    const to = saySquare(uci.slice(2));
    phrases.push(
      `${role} ${color} ${from} ${to}`,
      `${role} ${from} ${to}`,
      `quân ${role} ${color} từ ${from} đến ${to}`,
      `đưa ${role} từ ${from} tới ${to}`,
      `đi từ ${from} đến ${to}`,
      `${from} sang ${to}`,
      `${role} tới ${to}`,
      `${role} ${color} lên ${to}`,
      `di chuyển quân ${role} từ ${from} sang ô ${to}`,
      `${role} ở ${from} đi ${to}`,
      `${role} từ ${sayExplicit(uci.slice(0, 2))} đến ${sayExplicit(uci.slice(2))}`,
      `${role} từ ${sayExplicit(uci.slice(0, 2), true)} đến ${sayExplicit(uci.slice(2), true)}`,
    );
    if (['b', 'd'].some(file => uci.startsWith(file) || uci[2] === file))
      for (const [b, d] of [
        ['bờ', 'đờ'],
        ['bi', 'đi'],
        ['bê', 'dê'],
      ]) {
        // "dờ" is absent from small-vn-0.4; secondary ASR can still supply it.
        const alternate = (key: string, labelled = false) => {
          const file = key.startsWith('b') ? b : key.startsWith('d') ? d : fileNames[key.charCodeAt(0) - 97];
          const rank = rankNames[Number(key[1]) - 1];
          return labelled ? `cột ${file} hàng ${rank}` : `${file} ${rank}`;
        };
        phrases.push(
          `${role} ${alternate(uci.slice(0, 2))} ${alternate(uci.slice(2))}`,
          `${role} từ ${alternate(uci.slice(0, 2), true)} đến ${alternate(uci.slice(2), true)}`,
        );
      }
    if (piece.toUpperCase() === 'P')
      phrases.push(`đẩy tốt ${color} từ ô ${from} lên ô ${to}`, `tốt ${color} tiến lên ${to}`);
    if (piece.toUpperCase() === 'N') phrases.push(`mã nhảy lên ô ${to}`);
    if (
      (board.pieces[square(uci.slice(2))] && isEnemy(piece, board.pieces[square(uci.slice(2))])) ||
      (piece.toUpperCase() === 'P' && !uci.startsWith(uci[2]))
    )
      phrases.push(`${role} ${color} ${from} ăn ${to}`, `${role} ăn ở ${to}`);
    if (piece.toUpperCase() === 'P' && '18'.includes(uci[3]))
      for (const name of ['hậu', 'xe', 'tượng', 'mã'])
        phrases.push(
          `${role} ${color} từ ${from} đến ${to} phong ${name}`,
          `${role} ${color} từ ${from} đến ${to} phong cấp thành ${name}`,
        );
  }
  return [...new Set(phrases)];
}

function isEnemy(a: string, b: string) {
  return (a === a.toUpperCase()) !== (b === b.toUpperCase());
}
