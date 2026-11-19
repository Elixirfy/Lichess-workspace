import type { GaugeOptions } from 'lib/ceval';

import type AnalyseCtrl from './ctrl';

// Only the original full mainline endpoint inherits the recorded game result.
// A variation or an earlier node must keep its own position evaluation.
export function reviewGaugeOptions(ctrl: AnalyseCtrl): GaugeOptions | undefined {
  if (ctrl.data.game.variant.key !== 'standard') return undefined;
  const parts = ctrl.data.treeParts;
  const originalPath = parts.map(part => part.id ?? '').join('');
  const final = parts[parts.length - 1];
  const official =
    !ctrl.synthetic &&
    !ctrl.study &&
    ctrl.data.game.status.id >= 30 &&
    ctrl.path === originalPath &&
    ctrl.node.ply === ctrl.data.game.turns &&
    ctrl.node.fen === final?.fen;
  const winner = ctrl.data.game.winner;
  return {
    expectedScore: true,
    result: official
      ? { white: Number(winner === 'white'), draw: Number(!winner), black: Number(winner === 'black') }
      : undefined,
  };
}
