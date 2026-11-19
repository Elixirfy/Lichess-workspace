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

test('review uses Lichess Win% even when the same engine WDL is saturated', () => {
  const wdl = Object.freeze({ white: 1, draw: 0, black: 0 });
  const view = gauge({ ply: 12, ceval: { cp: 300, wdl } });
  assert.deepEqual(values(view), ['75%', '25%']);
  assert.equal(view.getAttribute('style'), '--eval-percent: 25%');
  assert.equal(view.dataset.metric, 'lichess-win-percent');
  assert.equal(view.dataset.source, 'engine-score');
  assert.match(view.getAttribute('aria-label')!, /Trắng 75%.*Đen 25%/);
  assert.match(view.title, /Win% của Lichess/);
});

test('reversing the board preserves color values and reverses the gauge', () => {
  const node = { ply: 7, ceval: Object.assign({ cp: 100 }, { wdl: { white: 0.8, draw: 0.1, black: 0.1 } }) };
  const white = gauge(node);
  const black = gauge(node, { expectedScore: true }, 'black');
  assert.deepEqual(values(white), ['59%', '41%']);
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

test('WDL-only stored evaluations retain a clearly labelled fallback', () => {
  const view = gauge({ ply: 50, ceval: { wdl: { white: 0, draw: 1, black: 0 } } });
  assert.deepEqual(values(view), ['50%', '50%']);
  assert.equal(view.dataset.metric, 'expected-score');
  assert.match(view.title, /WDL.*Hòa tính nửa điểm/);
  assert.doesNotMatch(view.textContent, /NaN|Infinity/);
});

test('official win and draw results override cached evaluations at the selected final node', () => {
  for (const [result, expected] of [
    [{ white: 1, draw: 0, black: 0 }, ['100%', '0%']],
    [{ white: 0, draw: 0, black: 1 }, ['0%', '100%']],
    [{ white: 0, draw: 1, black: 0 }, ['50%', '50%']],
  ] as const) {
    const view = gauge({ ply: 20, ceval: { cp: -250 } }, { expectedScore: true, result });
    assert.deepEqual(values(view), expected);
    assert.equal(view.dataset.source, 'official');
    assert.equal(view.dataset.metric, 'result');
    assert.match(view.title, /Kết quả chính thức/);
  }
});

test('proven position outcomes work without an engine evaluation', () => {
  assert.deepEqual(values(gauge({ ply: 4, outcome: () => ({ winner: 'black' }) })), ['0%', '100%']);
  assert.deepEqual(values(gauge({ ply: 6, outcome: () => ({}) })), ['50%', '50%']);
});

test('Lichess ceilings apply to extreme centipawns and mate lines, not official results', () => {
  const engine = gauge({ ply: 11, ceval: { cp: 1400, wdl: { white: 1, draw: 0, black: 0 } } });
  assert.deepEqual(values(engine), ['98%', '2%']);
  assert.equal(engine.getAttribute('style'), '--eval-percent: 2%');
  assert.match(engine.getAttribute('aria-label')!, /Trắng 98% · Đen 2%/);
  const mate = gauge({ ply: 3, ceval: { mate: -1 } }, { expectedScore: true }, 'black');
  assert.deepEqual(values(mate), ['2%', '98%']);
  assert.equal(mate.dataset.metric, 'lichess-win-percent');
  assert.equal(mate.getAttribute('style'), '--eval-percent: 98%');
  const legacy = gauge({ ply: 30, eval: { cp: 1200 } });
  assert.deepEqual(values(legacy), ['98%', '2%']);
  assert.equal(legacy.dataset.source, 'engine-score');
});

test('legacy cp-only evaluations also use Lichess Win%', () => {
  const view = gauge({ ply: 30, eval: { cp: 0 } });
  assert.deepEqual(values(view), ['50%', '50%']);
  assert.equal(view.dataset.source, 'engine-score');
  assert.match(view.title, /Win% của Lichess/);
});

test('other gauge callers keep the existing display without the review percentages', () => {
  const view = gauge({ ply: 12, ceval: { cp: 120 } }, { expectedScore: false });
  assert.deepEqual(values(view), [undefined, undefined]);
  assert.equal(view.dataset.metric, undefined);
});
