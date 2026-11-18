import assert from 'node:assert/strict';
import { test } from 'node:test';

import { balanceGrammar } from '../src/grammar';

const terminalMass = (phrases: string[], ending: string) =>
  phrases.filter(phrase => phrase === ending || phrase.endsWith(` ${ending}`)).length;

test('notation variants do not give one spoken destination more prior mass', () => {
  const input = ['ép hai ép ba', 'g một ép ba', 'mã ép ba', 'ép hai ép bốn', 'ép bốn', '[unk]'];
  const balanced = balanceGrammar(input);
  assert.equal(terminalMass(balanced, 'ép ba'), terminalMass(balanced, 'ép bốn'));
  assert.deepEqual(new Set(balanced), new Set(input), 'Keep every complete phrase and the unknown path');
});

test('balancing applies to other ranks and ignores duplicated input phrases', () => {
  const input = ['xe a năm', 'hậu a năm', 'a hai a năm', 'a sáu', '[unk]'];
  const balanced = balanceGrammar([...input, 'xe a năm']);
  assert.equal(terminalMass(balanced, 'a năm'), terminalMass(balanced, 'a sáu'));
  assert.deepEqual(balanced, balanceGrammar(input));
  assert.deepEqual(new Set(balanced), new Set(input));
});

test('a large legal vocabulary is preserved without unbounded expansion', () => {
  for (const input of [
    Array.from({ length: 9000 }, (_, i) => `piece${i} square${i}`),
    [43, 47, 53].flatMap((size, group) =>
      Array.from({ length: size }, (_, i) => `variant${i} shared ending${group}`),
    ),
  ]) {
    const balanced = balanceGrammar(input);
    assert.ok(balanced.length <= Math.max(input.length, 8192));
    assert.deepEqual(new Set(balanced), new Set(input));
  }
});
