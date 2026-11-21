import assert from 'node:assert/strict';

// Independent reference for smoke tests that read real engine evaluations.
export function expectedWhiteWinPercent(cp, mate) {
  const score = mate == null ? cp : 1000 * Math.sign(mate);
  assert.ok(Number.isFinite(score) && mate !== 0, 'The engine must supply a finite cp or a mate score');
  return Math.round(100 / (1 + Math.exp(-0.00368208 * Math.min(1000, Math.max(-1000, score)))));
}
