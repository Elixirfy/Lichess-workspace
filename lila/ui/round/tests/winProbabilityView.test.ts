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

test('one bar shows expected-score advantage from the preferred human estimate', () => {
  const view = panel();
  assert.equal(view.querySelectorAll('.win-probability__bar').length, 1);
  assert.equal(view.querySelectorAll('.win-probability__values').length, 1);
  assert.equal(view.textContent.match(/\d+\.\d%/g)?.length, 2);
  assert.equal(view.dataset.source, 'human');
  assert.equal(view.dataset.metric, 'expected-score');
  assert.match(view.getAttribute('title')!, /Ưu thế người chơi · thử nghiệm/);
  assert.match(view.querySelector('.win-probability__values')!.textContent, /Trắng 65.0%.*Đen 35.0%/);
  assert.equal(view.querySelector('.win-probability__white')!.getAttribute('style'), 'width:65%');
  assert.equal(view.querySelector('.win-probability__black')!.getAttribute('style'), 'width:35%');
  assert.equal(view.querySelector('.win-probability__draw'), null);
  assert.equal(view.querySelector('.win-probability__source'), null);
  assert.equal(view.querySelector('.win-probability__explanation'), null);
  assert.equal(view.textContent, 'Trắng 65.0%Đen 35.0%');
  assert.match(view.getAttribute('title')!, /50% = cân bằng.*Hòa tính nửa điểm/);
  assert.match(view.getAttribute('aria-label')!, /Ưu thế Trắng\/Đen.*điểm kỳ vọng/);
  assert.deepEqual(prediction.human.probabilities, { white: 0.6, draw: 0.1, black: 0.3 });
  assert.doesNotMatch(view.textContent, /Theo engine|Stockfish|d17/);
});

test('missing or unsupported human context falls back to one clearly identified engine estimate', () => {
  for (const reason of ['missing_context', 'outside_scope', 'model_unavailable']) {
    const view = panel({ ...prediction, human: { status: 'unavailable', reason } });
    assert.equal(view.dataset.source, 'engine');
    assert.match(view.getAttribute('title')!, /Ưu thế theo engine/);
    assert.match(view.querySelector('.win-probability__values')!.textContent, /Trắng 50.0%.*Đen 50.0%/);
    assert.equal(view.querySelector('.win-probability__source'), null);
    assert.equal(view.querySelector('.win-probability__explanation'), null);
    assert.equal(view.textContent, 'Trắng 50.0%Đen 50.0%');
    assert.match(view.getAttribute('title')!, /engine.*cấp độ bot/);
    assert.equal(view.textContent.match(/\d+\.\d%/g)?.length, 2);
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
      `Trắng ${(white * 100).toFixed(1)}%Đen ${((1 - white) * 100).toFixed(1)}%`,
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
    assert.match(view.querySelector('.win-probability__values')!.textContent, /Trắng 50.0%.*Đen 50.0%/);
    assert.match(view.getAttribute('title')!, /Hòa tính nửa điểm/);
    assert.equal(view.querySelector('.win-probability__explanation'), null);
    assert.doesNotMatch(view.textContent, /NaN|Infinity|kết thúc hòa/);
  }
});

test('two displayed values and segment widths sum to 100.0% without swapping White and Black', () => {
  for (const probabilities of [
    { white: 0.1, draw: 0.2, black: 0.7 },
    { white: 0, draw: 0.9, black: 0.1 },
    { white: 1e-12, draw: 1 - 4e-12, black: 3e-12 },
    { white: 0.5005, draw: 0, black: 0.4995 },
  ]) {
    const view = panel({ ...prediction, human: undefined, probabilities });
    const nodes = [...view.querySelectorAll('.win-probability__values span')];
    assert.equal(nodes.length, 2);
    const values = nodes.map(node => Number(node.textContent.match(/(\d+\.\d)%/)![1]));
    assert.equal(Math.round((values[0] + values[1]) * 10), 1000);
    const expectedWhite = (probabilities.white + probabilities.draw / 2) * 100;
    assert.ok(Math.abs(values[0] - expectedWhite) <= 0.050001);
    for (const [i, color] of ['white', 'black'].entries())
      assert.equal(
        view.querySelector(`.win-probability__${color}`)!.getAttribute('style'),
        `width:${values[i]}%`,
      );
  }
});

test('the reported 0/87.6/12.4 case becomes 43.8/56.2 advantage without changing its WDL', () => {
  const probabilities = Object.freeze({ white: 0, draw: 0.876, black: 0.124 });
  const view = panel({ ...prediction, human: undefined, probabilities });
  assert.equal(view.querySelector('.win-probability__values')!.textContent, 'Trắng 43.8%Đen 56.2%');
  assert.equal(view.dataset.metric, 'expected-score');
  assert.match(view.getAttribute('title')!, /Ưu thế/);
  assert.doesNotMatch(view.textContent, /không tính hòa|có bên thắng|100.0%/);
});

test('advantage distinguishes clear and near-winning positions while remaining an estimate', () => {
  for (const [probabilities, text] of [
    [{ white: 0.8, draw: 0.1, black: 0.1 }, 'Trắng 85.0%Đen 15.0%'],
    [{ white: 0.98, draw: 0.02, black: 0 }, 'Trắng 99.0%Đen 1.0%'],
  ] as const) {
    const view = panel({ ...prediction, human: undefined, probabilities });
    assert.equal(view.querySelector('.win-probability__values')!.textContent, text);
    assert.equal(view.dataset.source, 'engine');
    assert.equal(view.dataset.metric, 'expected-score');
    assert.doesNotMatch(view.textContent, /Kết quả chính thức|không tính hòa/);
  }
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
