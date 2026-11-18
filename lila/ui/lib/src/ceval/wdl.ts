export interface Wdl {
  white: number;
  draw: number;
  black: number;
}

export function validWdl(p?: Wdl): p is Wdl {
  if (!p) return false;
  const values = [p.white, p.draw, p.black];
  return (
    values.every(x => Number.isFinite(x) && x >= 0 && x <= 1) &&
    Math.abs(values.reduce((a, b) => a + b, 0) - 1) < 0.00001
  );
}

// Expected points: win = 1, draw = 0.5, loss = 0. Complementary tenths total 100.0%.
export function expectedScorePercentages(p: Wdl): [number, number] | undefined {
  if (!validWdl(p)) return undefined;
  const total = p.white + p.draw + p.black;
  const white = Math.round(((p.white + p.draw / 2) / total) * 1000);
  return [white / 10, (1000 - white) / 10];
}

export function uciWdl(values: number[], whitePov: boolean): Wdl | undefined {
  if (
    values.length !== 3 ||
    !values.every(x => Number.isInteger(x) && x >= 0 && x <= 1000) ||
    values.reduce((a, b) => a + b, 0) !== 1000
  )
    return undefined;
  return {
    white: values[whitePov ? 0 : 2] / 1000,
    draw: values[1] / 1000,
    black: values[whitePov ? 2 : 0] / 1000,
  };
}

// Legacy cp-only evaluations: the pinned Stockfish 15.1 WDL model, not engine-emitted WDL.
// https://github.com/official-stockfish/Stockfish/blob/sf_15.1/src/uci.cpp
// Also independently checked against python-chess Cp.wdl(model="sf15.1", ply=...).
function sf151Wins(cp: number, ply: number): number {
  const m = Math.min(240, Math.max(ply, 0)) / 64;
  const a = ((-0.58270499 * m + 2.68512549) * m + 15.24638015) * m + 344.49745382;
  const b = ((-2.65734562 * m + 15.96509799) * m - 20.69040836) * m + 73.61029937;
  const x = Math.min(4000, Math.max((cp * 361) / 100, -4000));
  return Math.floor(0.5 + 1000 / (1 + Math.exp((a - x) / b)));
}

export function evalWdl(
  score: EvalScore,
  ply: number,
): { probabilities: Wdl; source: 'engine-wdl' | 'score-wdl' } | undefined {
  if (score.wdl !== undefined)
    return validWdl(score.wdl) ? { probabilities: score.wdl, source: 'engine-wdl' } : undefined;
  if (!Number.isInteger(ply) || ply < 0) return undefined;
  let probabilities: Wdl;
  if (score.mate !== undefined) {
    if (!Number.isFinite(score.mate) || !Number.isInteger(score.mate) || !score.mate) return undefined;
    probabilities = { white: Number(score.mate > 0), draw: 0, black: Number(score.mate < 0) };
  } else {
    if (!Number.isFinite(score.cp)) return undefined;
    const white = sf151Wins(score.cp!, ply);
    const black = sf151Wins(-score.cp!, ply);
    probabilities = { white: white / 1000, draw: (1000 - white - black) / 1000, black: black / 1000 };
  }
  return { probabilities, source: 'score-wdl' };
}
