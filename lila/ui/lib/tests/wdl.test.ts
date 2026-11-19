import assert from 'node:assert/strict';
import { test } from 'node:test';

import { evalWdl, expectedScorePercentages, uciWdl } from '../src/ceval/wdl';
import reference from './fixtures/sf151-wdl.json' with { type: 'json' };

test('legacy score conversion matches independent python-chess Stockfish 15.1 vectors', () => {
  for (const { cp, ply, wdl } of reference) {
    const result = evalWdl({ cp }, ply)!;
    assert.equal(result.source, 'score-wdl');
    assert.deepEqual(
      [result.probabilities.white, result.probabilities.draw, result.probabilities.black].map(v =>
        Math.round(v * 1000),
      ),
      wdl,
      `cp=${cp}, ply=${ply}`,
    );
  }
});

test('native WDL is preferred over cp and never rewritten', () => {
  const wdl = Object.freeze({ white: 0, draw: 0.876, black: 0.124 });
  const result = evalWdl({ cp: 500, wdl }, 12)!;
  assert.equal(result.source, 'engine-wdl');
  assert.equal(result.probabilities, wdl);
  assert.deepEqual(expectedScorePercentages(result.probabilities), [43.8, 56.2]);
});

test('empty, invalid and nonfinite scores cannot create an advantage', () => {
  for (const score of [
    {},
    { cp: NaN },
    { cp: Infinity },
    { mate: 0 },
    { mate: Infinity },
    { mate: 1.1 },
    { cp: 1, wdl: { white: 2, draw: 0, black: 0 } },
  ])
    assert.equal(evalWdl(score, 12), undefined);
  assert.equal(evalWdl({ cp: 0 }, -1), undefined);
  assert.equal(evalWdl({ cp: 0 }, NaN), undefined);
  assert.equal(uciWdl([1, 998, 1], true)?.draw, 0.998);
  for (const raw of [[1, 998, 2], [-1, 1000, 1], [NaN, 0, 1000], [0.5, 999, 0.5], []])
    assert.equal(uciWdl(raw, true), undefined);
});

test('mate scores retain their White perspective and old cp models are symmetric', () => {
  assert.deepEqual(expectedScorePercentages(evalWdl({ mate: 3 }, 8)!.probabilities), [100, 0]);
  assert.deepEqual(expectedScorePercentages(evalWdl({ mate: -3 }, 8)!.probabilities), [0, 100]);
  for (const cp of [0, 1, 59, 100, 300, 4000]) {
    const positive = evalWdl({ cp }, 30)!.probabilities;
    const negative = evalWdl({ cp: -cp }, 30)!.probabilities;
    assert.equal(positive.white, negative.black);
    assert.equal(positive.draw, negative.draw);
    assert.equal(positive.black, negative.white);
  }
});
