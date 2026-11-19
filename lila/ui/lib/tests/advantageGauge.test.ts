import assert from 'node:assert/strict';
import { test } from 'node:test';
import { init, attributesModule, classModule, type VNode } from 'snabbdom';

import type { CevalHandler } from '../src/ceval/types';
import { renderGauge } from '../src/ceval/view/main';

type Wdl = { white: number; draw: number; black: number };
type Options = { expectedScore: boolean; result?: Wdl };
type Node = {
  ply: number;
  ceval?: EvalScore;
  eval?: EvalScore;
  outcome?: () => { winner?: Color } | undefined;
};

function gauge(node: Node, options: Options = { expectedScore: true }, color: Color = 'white') {
  const ctrl = {
    ongoing: false,
    showEvalGauge: () => true,
    showEvaluation: () => true,
    getOrientation: () => color,
    getNode: () => ({ outcome: () => undefined, ...node }),
  } as unknown as CevalHandler;
  return init([attributesModule, classModule])(
    document.createElement('div'),
    renderGauge(ctrl, options) as VNode,
  ).elm as HTMLElement;
}

const values = (view: HTMLElement) =>
  ['white', 'black'].map(
    color => view.querySelector(`.eval-gauge__${color} .eval-gauge__value`)?.textContent,
  );

test('review gauge uses the same half-draw projection as the live panel', () => {
  const wdl = Object.freeze({ white: 0, draw: 0.876, black: 0.124 });
  const view = gauge({ ply: 12, ceval: Object.assign({ cp: -59 }, { wdl }) });
  assert.deepEqual(values(view), ['43.8%', '56.2%']);
  assert.equal(view.getAttribute('style'), '--eval-percent: 56.2%');
  assert.equal(view.dataset.metric, 'expected-score');
  assert.equal(view.dataset.source, 'engine-wdl');
  assert.match(view.getAttribute('aria-label')!, /Trắng 43.8%.*Đen 56.2%/);
  assert.match(view.title, /Hòa tính nửa điểm/);
  assert.deepEqual(wdl, { white: 0, draw: 0.876, black: 0.124 });
});

test('reversing the board preserves color values and reverses the gauge', () => {
  const node = { ply: 7, ceval: Object.assign({ cp: 100 }, { wdl: { white: 0.8, draw: 0.1, black: 0.1 } }) };
  const white = gauge(node);
  const black = gauge(node, { expectedScore: true }, 'black');
  assert.deepEqual(values(white), ['85.0%', '15.0%']);
  assert.deepEqual(values(black), values(white));
  assert.equal(white.classList.contains('reverse'), false);
  assert.equal(black.classList.contains('reverse'), true);
});

test('a node without evaluation clears the preceding gauge and its percentages', () => {
  gauge({ ply: 8, ceval: Object.assign({ cp: 900 }, { wdl: { white: 1, draw: 0, black: 0 } }) });
  const view = gauge({ ply: 2 });
  assert.deepEqual(values(view), [undefined, undefined]);
  assert.equal(view.getAttribute('style'), '--eval-percent: 50%');
  assert.equal(view.classList.contains('empty'), true);
  assert.equal(view.dataset.source, undefined);
  assert.match(view.title, /Chưa có đánh giá/);
});

test('live all-draw WDL is equal expected points, not a conditional win division', () => {
  const view = gauge({ ply: 50, ceval: Object.assign({ cp: 0 }, { wdl: { white: 0, draw: 1, black: 0 } }) });
  assert.deepEqual(values(view), ['50.0%', '50.0%']);
  assert.doesNotMatch(view.textContent, /NaN|Infinity/);
});

test('official win and draw results override cached evaluations at the selected final node', () => {
  for (const [result, expected] of [
    [{ white: 1, draw: 0, black: 0 }, ['100.0%', '0.0%']],
    [{ white: 0, draw: 0, black: 1 }, ['0.0%', '100.0%']],
    [{ white: 0, draw: 1, black: 0 }, ['50.0%', '50.0%']],
  ] as const) {
    const view = gauge({ ply: 20, ceval: { cp: -250 } }, { expectedScore: true, result });
    assert.deepEqual(values(view), expected);
    assert.equal(view.dataset.source, 'official');
    assert.equal(view.dataset.metric, 'result');
    assert.match(view.title, /Kết quả chính thức/);
  }
});

test('proven position outcomes work without an engine evaluation', () => {
  assert.deepEqual(values(gauge({ ply: 4, outcome: () => ({ winner: 'black' }) })), ['0.0%', '100.0%']);
  assert.deepEqual(values(gauge({ ply: 6, outcome: () => ({}) })), ['50.0%', '50.0%']);
});

test('legacy cp-only evaluations are identified as a WDL model conversion', () => {
  const view = gauge({ ply: 30, eval: { cp: 0 } });
  assert.deepEqual(values(view), ['50.0%', '50.0%']);
  assert.equal(view.dataset.source, 'score-wdl');
  assert.match(view.title, /Stockfish 15.1/);
});

test('other gauge callers keep the existing display without the review percentages', () => {
  const view = gauge({ ply: 12, ceval: { cp: 120 } }, { expectedScore: false });
  assert.deepEqual(values(view), [undefined, undefined]);
  assert.equal(view.dataset.metric, undefined);
});
