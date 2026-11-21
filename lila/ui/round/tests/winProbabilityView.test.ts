import assert from 'node:assert/strict';
import { test } from 'node:test';
import { init, attributesModule, type VNode } from 'snabbdom';

import type RoundController from '../src/ctrl';
import render from '../src/view/winProbability';

const prediction = {
  status: 'ready',
  source: 'engine',
  engine: 'Stockfish 15.1',
  depth: 17,
  probabilities: { white: 0.1, draw: 0.8, black: 0.1 },
  human: { status: 'ready', model_id: 'pilot-v1', probabilities: { white: 0.6, draw: 0.1, black: 0.3 } },
};

function panel(data: unknown = prediction, replay = false): HTMLElement {
  const ctrl = { winProbability: { data }, replaying: () => replay } as unknown as RoundController;
  return init([attributesModule])(document.createElement('div'), render(ctrl) as VNode).elm as HTMLElement;
}

test('one bar shows Lichess Win% from the engine score when both WDL estimates disagree', () => {
  const view = panel({ ...prediction, evaluation_cp: 300 });
  assert.equal(view.querySelectorAll('.win-probability__bar').length, 1);
  assert.equal(view.querySelectorAll('.win-probability__values').length, 1);
  assert.equal(view.textContent.match(/\b\d+%/g)?.length, 2);
  assert.equal(view.dataset.source, 'engine');
  assert.equal(view.dataset.metric, 'lichess-win-percent');
  assert.match(view.getAttribute('title')!, /Win% của Lichess/);
  assert.equal(view.querySelector('.win-probability__white')!.getAttribute('style'), 'width:75%');
  assert.equal(view.querySelector('.win-probability__black')!.getAttribute('style'), 'width:25%');
  assert.equal(view.querySelector('.win-probability__draw'), null);
  assert.equal(view.querySelector('.win-probability__source'), null);
  assert.equal(view.querySelector('.win-probability__explanation'), null);
  assert.equal(view.textContent, 'Trắng 75%Đen 25%');
  assert.doesNotMatch(view.getAttribute('title')!, /Hòa tính nửa điểm/);
  assert.match(view.getAttribute('aria-label')!, /Ưu thế Trắng\/Đen.*Win% của Lichess/);
  assert.deepEqual(prediction.human.probabilities, { white: 0.6, draw: 0.1, black: 0.3 });
  assert.doesNotMatch(view.textContent, /Theo engine|Stockfish|d17/);
});

test('missing or invalid scores fall back to engine WDL with its own label', () => {
  for (const evaluation_cp of [undefined, NaN]) {
    const view = panel({ ...prediction, evaluation_cp });
    assert.equal(view.dataset.source, 'engine');
    assert.equal(view.dataset.metric, 'expected-score');
    assert.match(view.getAttribute('title')!, /WDL/);
    assert.match(view.querySelector('.win-probability__values')!.textContent, /Trắng 50%.*Đen 50%/);
    assert.equal(view.querySelector('.win-probability__source'), null);
    assert.equal(view.querySelector('.win-probability__explanation'), null);
    assert.equal(view.textContent, 'Trắng 50%Đen 50%');
    assert.match(view.getAttribute('title')!, /Stockfish.*cấp độ bot/);
    assert.equal(view.textContent.match(/\b\d+%/g)?.length, 2);
    assert.equal(view.querySelector('.win-probability__draw'), null);
  }
});

test('an official draw shows the result without an estimated advantage bar', () => {
  const view = panel({
    ...prediction,
    status: 'finished',
    source: 'official',
    probabilities: { white: 0, draw: 1, black: 0 },
  });
  assert.equal(view.dataset.source, 'official');
  assert.equal(view.dataset.metric, 'result');
  assert.match(view.textContent, /Kết quả chính thức/);
  assert.match(view.querySelector('.win-probability__status')!.textContent, /Ván đấu kết thúc hòa/);
  assert.equal(view.querySelector('.win-probability__values'), null);
  assert.equal(view.querySelector('.win-probability__bar'), null);
  assert.equal(view.dataset.model, undefined);
  assert.equal(view.querySelector('.win-probability__explanation'), null);
  assert.doesNotMatch(view.textContent, /thử nghiệm/);
});

test('official winners retain their color and override the human estimate', () => {
  for (const white of [0, 1]) {
    const view = panel({
      ...prediction,
      status: 'finished',
      source: 'official',
      probabilities: { white, draw: 0, black: 1 - white },
    });
    assert.equal(view.dataset.source, 'official');
    assert.equal(view.dataset.metric, 'result');
    assert.equal(view.dataset.model, undefined);
    assert.equal(
      view.querySelector('.win-probability__values')!.textContent,
      `Trắng ${white * 100}%Đen ${(1 - white) * 100}%`,
    );
    assert.doesNotMatch(view.textContent, /thử nghiệm|không tính hòa/);
  }
});

test('a live all-draw estimate has equal expected points for both colors', () => {
  for (const human of [false, true]) {
    const probabilities = { white: 0, draw: 1, black: 0 };
    const view = panel({
      ...prediction,
      probabilities,
      human: human ? { status: 'ready', model_id: 'pilot-v1', probabilities } : { status: 'unavailable' },
    });
    assert.equal(view.dataset.metric, 'expected-score');
    assert.match(view.querySelector('.win-probability__values')!.textContent, /Trắng 50%.*Đen 50%/);
    assert.match(view.getAttribute('title')!, /Hòa tính nửa điểm/);
    assert.equal(view.querySelector('.win-probability__explanation'), null);
    assert.doesNotMatch(view.textContent, /NaN|Infinity|kết thúc hòa/);
  }
});

test('the two labels and bar segments use whole percentages that sum to 100', () => {
  for (const [probabilities, values] of [
    [{ white: 0.1, draw: 0.2, black: 0.7 }, [20, 80]],
    [{ white: 0, draw: 0.9, black: 0.1 }, [45, 55]],
    [{ white: 1e-12, draw: 1 - 4e-12, black: 3e-12 }, [50, 50]],
    [{ white: 0.5049, draw: 0, black: 0.4951 }, [50, 50]],
    [{ white: 0.5051, draw: 0, black: 0.4949 }, [51, 49]],
  ] as const) {
    const view = panel({ ...prediction, human: undefined, probabilities });
    const nodes = [...view.querySelectorAll('.win-probability__values span')];
    assert.deepEqual(
      nodes.map(node => node.textContent),
      [`Trắng ${values[0]}%`, `Đen ${values[1]}%`],
    );
    for (const [i, color] of ['white', 'black'].entries())
      assert.equal(
        view.querySelector(`.win-probability__${color}`)!.getAttribute('style'),
        `width:${values[i]}%`,
      );
  }
});

test('a draw-heavy estimate rounds to 44/56 advantage', () => {
  const probabilities = Object.freeze({ white: 0, draw: 0.876, black: 0.124 });
  const view = panel({ ...prediction, human: undefined, probabilities });
  assert.equal(view.querySelector('.win-probability__values')!.textContent, 'Trắng 44%Đen 56%');
  assert.equal(view.dataset.metric, 'expected-score');
  assert.match(view.getAttribute('title')!, /Ưu thế/);
  assert.doesNotMatch(view.textContent, /không tính hòa|có bên thắng|100%/);
});

test('advantage distinguishes clear and near-winning positions while remaining an estimate', () => {
  for (const [probabilities, text] of [
    [{ white: 0.8, draw: 0.1, black: 0.1 }, 'Trắng 85%Đen 15%'],
    [{ white: 0.98, draw: 0.02, black: 0 }, 'Trắng 99%Đen 1%'],
  ] as const) {
    const view = panel({ ...prediction, human: undefined, probabilities });
    assert.equal(view.querySelector('.win-probability__values')!.textContent, text);
    assert.equal(view.dataset.source, 'engine');
    assert.equal(view.dataset.metric, 'expected-score');
    assert.doesNotMatch(view.textContent, /Kết quả chính thức|không tính hòa/);
  }
});

test('a mate score takes precedence over cp and saturated WDL', () => {
  const blackWin = Object.freeze({ white: 0, draw: 0, black: 1 });
  const almostWhiteWin = Object.freeze({ white: 0.9997, draw: 0.0002, black: 0.0001 });
  const engine = panel({ ...prediction, probabilities: blackWin, evaluation_cp: 0, mate: -1 });
  const saturated = panel({ ...prediction, probabilities: almostWhiteWin, evaluation_cp: 1400 });
  assert.equal(engine.querySelector('.win-probability__values')!.textContent, 'Trắng 2%Đen 98%');
  assert.equal(saturated.querySelector('.win-probability__values')!.textContent, 'Trắng 98%Đen 2%');
  assert.equal(engine.querySelector('.win-probability__white')!.getAttribute('style'), 'width:2%');
  assert.equal(engine.querySelector('.win-probability__black')!.getAttribute('style'), 'width:98%');
  assert.equal(engine.dataset.metric, 'lichess-win-percent');
  assert.equal(saturated.dataset.source, 'engine');
});

test('replay and unavailable positions never retain either source of probabilities', () => {
  const views = [panel(prediction, true)];
  for (const status of ['pending', 'busy', 'stale', 'unavailable', 'aborted'])
    views.push(panel({ ...prediction, status }));
  for (const view of views) {
    assert.equal(view.querySelector('.win-probability__bar'), null);
    assert.equal(view.querySelector('.win-probability__values'), null);
    assert.equal(view.querySelector('.win-probability__source'), null);
    assert.equal(view.querySelector('.win-probability__explanation'), null);
    assert.equal(view.dataset.source, undefined);
    assert.equal(view.dataset.metric, undefined);
    assert.equal(view.getAttribute('title'), null);
  }
});
