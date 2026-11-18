import { charToRole } from 'chessops';

import { squareDist, type Board } from 'lib/game';

export { findTransforms, type Transform } from './transforms';

// optimizations for xval mappings when most keys only map to 1 value.  On V8 using
// voice move data, this is 50% faster while using half the memory of Map<string, Set>

export function movesTo(s: number, role: string, board: Board): number[] {
  const deltas = (d: number[], s = 0) => d.flatMap(x => [s - x, s + x]);

  if (role === 'K') return deltas([1, 7, 8, 9], s).filter(o => o >= 0 && o < 64 && squareDist(s, o) === 1);
  else if (role === 'N')
    return deltas([6, 10, 15, 17], s).filter(o => o >= 0 && o < 64 && squareDist(s, o) <= 2);
  const dests: number[] = [];
  for (const delta of deltas(
    role === 'Q' ? [1, 7, 8, 9] : role === 'R' ? [1, 8] : role === 'B' ? [7, 9] : [],
  )) {
    for (
      let square = s + delta;
      square >= 0 && square < 64 && squareDist(square, square - delta) === 1;
      square += delta
    ) {
      dests.push(square);
      if (board.pieces[square]) break;
    }
  }
  return dests;
}

export function as<T>(v: T, f: () => void): () => T {
  return () => {
    f();
    return v;
  };
}

export type SparseSet<T> = Set<T> | T;
export type SparseMap<V> = Map<string, SparseSet<V>>;

export function spread<T>(v: SparseSet<T>): T[] {
  return v instanceof Set ? [...v] : [v];
}

export function spreadMap<T>(m: SparseMap<T>): [string, T[]][] {
  return [...m].map(([k, v]) => [k, spread(v)]);
}

export function getSpread<T>(m: SparseMap<T>, key: string): T[] {
  const v = m.get(key);
  return v ? spread(v) : [];
}

export function remove<T>(m: SparseMap<T>, key: string, val: T): void {
  const v = m.get(key);
  if (v === val) m.delete(key);
  else if (v instanceof Set) v.delete(val);
}

export function pushMap<T>(m: SparseMap<T>, key: string, val: T): void {
  const v = m.get(key);
  if (!v) m.set(key, val);
  else {
    if (v instanceof Set) v.add(val);
    else if (v !== val) m.set(key, new Set([v, val]));
  }
}

export function src(uci: Uci) {
  return uci.slice(0, 2) as Key;
}

export function dest(uci: Uci) {
  return uci.slice(2, 4) as Key;
}

export const promo = (uci: Uci): Role | undefined => charToRole(uci.slice(4, 5));

export function flash(): void {
  const div = document.querySelector<HTMLElement>('#voice-status-row')!;
  div.classList.add('flash');
  div.onanimationend = () => div.classList.remove('flash');
}
