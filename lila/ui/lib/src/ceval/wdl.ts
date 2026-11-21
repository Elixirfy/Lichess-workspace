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

// Expected points: win = 1, draw = 0.5, loss = 0. Round once and take the complement.
export function expectedScorePercentages(p: Wdl, decimalPlaces: 0 | 1 = 1): [number, number] | undefined {
  if (!validWdl(p)) return undefined;
  const total = p.white + p.draw + p.black;
  const scale = 10 ** decimalPlaces;
  const units = 100 * scale;
  const white = Math.round(((p.white + p.draw / 2) / total) * units);
  return [white / scale, (units - white) / scale];
}

export function expectedScoreDisplay(p: Wdl, kind: 'estimate' | 'result'): [number, number] | undefined {
  const percentages = expectedScorePercentages(p, 0);
  if (!percentages || kind === 'result') return percentages;
  // Reserve the endpoints of the scale for settled positions and official results.
  const white = Math.max(1, Math.min(99, percentages[0]));
  return [white, 100 - white];
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
