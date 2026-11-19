import assert from 'node:assert/strict';
import { test } from 'node:test';

import { expectedScorePercentages, uciWdl } from '../src/ceval/wdl';

test('native WDL retains the White perspective and its expected points', () => {
  assert.deepEqual(uciWdl([800, 150, 50], true), { white: 0.8, draw: 0.15, black: 0.05 });
  assert.deepEqual(uciWdl([800, 150, 50], false), { white: 0.05, draw: 0.15, black: 0.8 });
  const wdl = Object.freeze({ white: 0, draw: 0.876, black: 0.124 });
  assert.deepEqual(expectedScorePercentages(wdl), [43.8, 56.2]);
});

test('empty, invalid and nonfinite UCI WDL cannot create an advantage', () => {
  assert.equal(uciWdl([1, 998, 1], true)?.draw, 0.998);
  for (const raw of [[1, 998, 2], [-1, 1000, 1], [NaN, 0, 1000], [0.5, 999, 0.5], []])
    assert.equal(uciWdl(raw, true), undefined);
});
