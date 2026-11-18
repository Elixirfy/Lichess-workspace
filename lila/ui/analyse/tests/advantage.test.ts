import assert from 'node:assert/strict';
import { test } from 'node:test';

import { reviewGaugeOptions } from '../src/advantage';
import type AnalyseCtrl from '../src/ctrl';

function review(overrides: Record<string, unknown> = {}): AnalyseCtrl {
  return {
    synthetic: false,
    study: undefined,
    path: 'aabb',
    node: { ply: 2, fen: 'final' },
    data: {
      game: { status: { id: 31 }, winner: 'white', turns: 2, variant: { key: 'standard' } },
      treeParts: [
        { id: '', ply: 0, fen: 'initial' },
        { id: 'aa', ply: 1, fen: 'first' },
        { id: 'bb', ply: 2, fen: 'final' },
      ],
    },
    ...overrides,
  } as unknown as AnalyseCtrl;
}

test('only the original endpoint receives the recorded game result', () => {
  assert.deepEqual(reviewGaugeOptions(review()), {
    expectedScore: true,
    result: { white: 1, draw: 0, black: 0 },
  });
  for (const overrides of [
    { path: 'aa', node: { ply: 1, fen: 'first' } },
    { path: 'aacc', node: { ply: 2, fen: 'final' } },
    { node: { ply: 2, fen: 'other' } },
    { synthetic: true },
    { study: {} },
  ])
    assert.equal(reviewGaugeOptions(review(overrides))!.result, undefined);
});

test('official draws, black wins, aborts and active games are distinct', () => {
  for (const [id, winner, expected] of [
    [34, undefined, { white: 0, draw: 1, black: 0 }],
    [30, 'black', { white: 0, draw: 0, black: 1 }],
    [25, undefined, undefined],
    [20, undefined, undefined],
  ] as const) {
    const ctrl = review();
    ctrl.data.game.status.id = id;
    ctrl.data.game.winner = winner;
    assert.deepEqual(reviewGaugeOptions(ctrl)!.result, expected);
  }
});

test('nonstandard variants retain the original gauge', () => {
  const ctrl = review();
  ctrl.data.game.variant.key = 'chess960';
  assert.equal(reviewGaugeOptions(ctrl), undefined);
});
