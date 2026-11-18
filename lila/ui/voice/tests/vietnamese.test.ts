import { Chessground } from '@lichess-org/chessground';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { mock, test, type TestContext } from 'node:test';

import type { MoveRootCtrl } from 'lib/game/moveRootCtrl';

import type { Listener, Microphone, VoiceCtrl } from '../src/interfaces';
// Persistent logging uses IndexedDB, which jsdom does not implement.
mock.module('lib/permalog', { namedExports: { log: async () => {} } });
const { initModule } = await import('../src/move/voice.move');

const start = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
const grammar = readFileSync(new URL('../grammar/move-vi.json', import.meta.url), 'utf8');

async function setup(
  t: TestContext,
  fen = start,
  dests: [Key, Key[]][] = [['e2', ['e3', 'e4']]],
  timer = '0',
) {
  for (const method of ['info', 'groupCollapsed', 'groupEnd'] as const)
    t.mock.method(console, method, () => {});
  localStorage.clear();
  localStorage.setItem('voice.timer', timer);
  localStorage.setItem('voice.move', Date.now().toString());
  Object.assign(site, { asset: { url: (path: string) => path } });
  t.mock.method(globalThis, 'fetch', async () => new Response(grammar));
  const listeners = new Map<string, Listener>();
  const grammars = new Map<string, string[]>();
  const notices: string[] = [];
  // The external audio boundary is replaced; grammar, matching and Chessground are real.
  const mic = {
    initRecognizer: (words: string[], opts: { recId?: string; listener?: Listener }) => {
      grammars.set(opts.recId ?? 'default', words);
      if (opts.listener) listeners.set(opts.recId ?? 'default', opts.listener);
    },
    setRecognizer: () => {},
    setStatus: (text: string) => notices.push(text),
    stop: () => listeners.get('default')?.('', 'stop'),
    isListening: true,
  } as unknown as Microphone;
  const cg = Chessground(document.createElement('div'), {
    fen,
    turnColor: fen.includes(' w ') ? 'white' : 'black',
    movable: { free: false, dests: new Map(dests) },
  });
  t.after(() => cg.destroy());
  const sent: [Key, Key, Role | undefined, boolean | undefined][] = [];
  const root: MoveRootCtrl = {
    pluginMove: (...args) => sent.push(args),
    redraw: () => {},
    flipNow: () => {},
  };
  const voice = { mic, lang: () => 'vi', pushTalk: () => true, flash: () => {} } as VoiceCtrl;
  const move = initModule({ root, voice, initial: { cg, fen, canMove: true } });
  await move.initGrammar();
  return {
    move,
    cg,
    sent,
    voice,
    grammars,
    notices,
    say: (text: string) => listeners.get('default')!(text, 'full'),
    fallback: (text: string) => listeners.get('default')!(text, 'fallback'),
  };
}

test('secondary recognition can move directly but cannot execute unrelated controls', async t => {
  const { move, sent, fallback, say } = await setup(t, start, [['f2', ['f3', 'f4']]]);
  fallback('ép hai ép bốn');
  assert.equal(move.question(), false);
  assert.deepEqual(sent, [['f2', 'f4', undefined, true]]);
  fallback('xác nhận');
  fallback('xin thua');
  say('xác nhận');
  assert.equal(sent.length, 1);
  assert.equal(move.question(), false);
});

test('cancellation clears ambiguous arrows without submitting a move', async t => {
  const { move, cg, sent, say } = await setup(t, '7k/8/8/8/8/5N2/8/1N5K w - - 0 1', [
    ['b1', ['d2']],
    ['f3', ['d2']],
  ]);
  say('mã đê hai');
  assert.equal(cg.state.drawable.shapes.length, 2);
  say('hủy nước đi');
  say('xanh');
  assert.equal(cg.state.drawable.shapes.length, 0);
  assert.equal(move.question(), false);
  assert.deepEqual(sent, []);
});

test('secondary speech cannot accept resignation or an opponent request', async t => {
  const { move, sent, fallback, say } = await setup(t);
  for (const text of ['không xác nhận', 'xác nhận rồi xin thua', 'xin thua']) fallback(text);
  assert.deepEqual(sent, []);
  assert.equal(move.question(), false);
  say('xin thua');
  fallback('xác nhận');
  assert.match(String((move.question() || { prompt: '' }).prompt), /resignation/);
  const answers: boolean[] = [];
  say('huỷ bỏ');
  move.listenForResponse('draw', yes => answers.push(yes));
  fallback('đồng ý');
  assert.deepEqual(answers, []);
});

test('recognition routing treats commands and ambiguity as handled, unknown speech as unhandled', async t => {
  const { say } = await setup(t, start, [
    ['f2', ['f3', 'f4']],
    ['g1', ['f3', 'h3']],
  ]);
  assert.equal(say('xin chào'), false);
  assert.equal(say('ép ba'), true);
  assert.equal(say('huỷ bỏ'), true);
});

test('natural Vietnamese pawn commands preserve piece, color and coordinates', async t => {
  for (const phrase of [
    'tốt trắng e hai e bốn',
    'quân tốt trắng từ e hai đến e bốn',
    'đưa tốt trắng từ e2 tới e4',
    'cho con tốt trắng đi từ ê hai sang ê bốn',
    'di chuyển tốt màu trắng e 2 e 4',
    'e hai sang e bốn',
    'đi từ e hai đến e bốn',
    'tốt trắng lên e tư',
    'đẩy tốt trắng từ ô e hai lên ô e bốn',
    'tốt ở e hai đi e bốn',
    'quân tốt trắng ở ô e hai đi đến ô e bốn',
    'tốt trắng tiến lên e bốn',
    'di chuyển quân tốt từ e2 sang ô e4',
  ]) {
    const { move, say, sent } = await setup(t);
    assert.equal(say(phrase), true, phrase);
    assert.equal(move.question(), false, phrase);
    assert.deepEqual(sent, [['e2', 'e4', undefined, true]], phrase);
  }
});

test('natural commands reject wrong pieces, colors, captures, negation and illegal destinations', async t => {
  const { move, say, sent } = await setup(t);
  for (const phrase of [
    'mã trắng e hai e bốn',
    'tốt đen e hai e bốn',
    'tốt trắng e hai e năm',
    'tốt trắng từ e ba đến e bốn',
    'tốt trắng e hai ăn e bốn',
    'đừng đi tốt trắng e hai e bốn',
    'không đi tốt trắng e hai e bốn',
    'tốt trắng e hai e bốn rồi đầu hàng',
    'tốt trắng e hai e bốn phong hậu',
    'từ e hai',
    'tốt trắng ở e hai',
    'tốt trắng từ e hai đến e bốn rồi xác nhận',
    'tốt trắng lên e ba hoặc e bốn',
    'tốt trắng đến e hai đến e bốn',
  ]) {
    assert.equal(say(phrase), false, phrase);
    assert.equal(move.question(), false, phrase);
    assert.deepEqual(sent, []);
  }
});

test('natural piece destinations keep ambiguity and support black pieces and phonetic files', async t => {
  for (const phrase of [
    'đưa con ngựa trắng lên ép ba',
    'mã nhảy lên ô ép ba',
    'ngựa trắng gờ một đi tới f3',
  ]) {
    const white = await setup(t, start, [['g1', ['f3', 'h3']]]);
    assert.equal(white.say(phrase), true, phrase);
    assert.deepEqual(white.sent, [['g1', 'f3', undefined, true]], phrase);
    assert.equal(white.move.question(), false);
  }
  const black = await setup(t, start.replace(' w ', ' b '), [['e7', ['e6', 'e5']]]);
  black.say('quân tốt đen từ ê bảy tới e năm');
  assert.deepEqual(black.sent, [['e7', 'e5', undefined, true]]);
  const ambiguous = await setup(t, '4k3/8/8/8/8/8/8/1N2KN2 w - - 0 1', [
    ['b1', ['d2']],
    ['f1', ['d2']],
  ]);
  ambiguous.say('mã trắng tới đê hai');
  assert.equal(ambiguous.cg.state.drawable.shapes.length, 2);
  assert.equal(ambiguous.move.question(), false);
  ambiguous.say('xác nhận');
  assert.deepEqual(ambiguous.sent, []);
});

test('natural capture and promotion commands validate the actual legal move', async t => {
  const capture = await setup(t, '4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1', [['e4', ['e5', 'd5']]]);
  capture.say('tốt trắng từ e bốn ăn ở dê năm');
  assert.deepEqual(capture.sent, [['e4', 'd5', undefined, true]]);
  const ep = await setup(t, '4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1', [['e5', ['e6', 'd6']]]);
  ep.say('tốt trắng e năm ăn dê sáu');
  assert.deepEqual(ep.sent, [['e5', 'd6', undefined, true]]);
  const promotion = await setup(t, 'k7/4P3/8/8/8/8/8/4K3 w - - 0 1', [['e7', ['e8']]]);
  promotion.say('đưa tốt trắng từ e bảy tới e tám phong thành ngựa');
  assert.deepEqual(promotion.sent, [['e7', 'e8', 'knight', true]]);
});

test('natural promotion supports every legal piece for both colors', async t => {
  for (const [name, role] of [
    ['hậu', 'queen'],
    ['xe', 'rook'],
    ['tịnh', 'bishop'],
    ['ngựa', 'knight'],
  ] as const) {
    for (const color of ['white', 'black'] as const) {
      const white = color === 'white';
      const from: Key = white ? 'e7' : 'e2';
      const to: Key = white ? 'e8' : 'e1';
      const fen = white ? 'k7/4P3/8/8/8/8/8/K7 w - - 0 1' : 'k7/8/8/8/8/8/4p3/K7 b - - 0 1';
      const { say, sent } = await setup(t, fen, [[from, [to]]]);
      const phrase = `tốt ${white ? 'trắng' : 'đen'} từ ${from} đến ${to} phong cấp thành ${name}`;
      assert.equal(say(phrase), true, phrase);
      assert.deepEqual(sent, [[from, to, role, true]], phrase);
      say('đồng ý');
      assert.deepEqual(sent, [[from, to, role, true]], phrase);
    }
  }
});

test('standalone old confirmation and cancellation aliases cannot submit moves', async t => {
  for (const phrase of [
    'xác nhận nước đi',
    'đồng ý',
    'đúng rồi',
    'thực hiện nước đi',
    'hủy bỏ',
    'huỷ bỏ',
    'hủy nước đi',
    'huỷ nước đi',
    'bỏ nước này',
    'không đi',
    'sai rồi',
  ]) {
    const { say, sent, move } = await setup(t);
    say(phrase);
    assert.deepEqual(sent, [], phrase);
    assert.equal(move.question(), false);
  }
  for (const [phrase, destination] of [
    ['nhập thành ngắn', 'h1'],
    ['nhập thành bên vua', 'h1'],
    ['nhập thành dài', 'a1'],
    ['nhập thành bên hậu', 'a1'],
  ] as const) {
    const castle = await setup(t, '4k3/8/8/8/8/8/8/R3K2R w KQ - 0 1', [['e1', ['a1', 'h1']]]);
    assert.equal(castle.say(phrase), true, phrase);
    assert.deepEqual(castle.sent, [['e1', destination, undefined, true]], phrase);
  }
});

test('natural templates are present in the legal-position Vosk grammar', async t => {
  const { grammars } = await setup(t);
  const phrases = grammars.get('default')!;
  assert.ok(phrases.includes('tốt trắng e hai e bốn'));
  assert.ok(phrases.includes('quân tốt trắng từ e hai đến e bốn'));
  assert.ok(phrases.includes('tốt trắng lên e bốn'));
  assert.ok(!phrases.includes('tốt đen e hai e bốn'));
  assert.ok(!phrases.includes('tốt trắng e hai e năm'));
  assert.ok(phrases.includes('đồng ý'));
  assert.ok(phrases.includes('hủy nước đi'));
});

test('explicit file and rank names distinguish B and D with immediate submission', async t => {
  const cases = [
    ['tốt từ cột bê hàng hai đến cột bê hàng bốn', 'b2', 'b4'],
    ['tốt từ cột đê hàng hai đến cột đê hàng bốn', 'd2', 'd4'],
    ['tốt cột bê hàng hai tới cột bê hàng bốn', 'b2', 'b4'],
    ['tốt cột dê hàng hai tới cột dê hàng bốn', 'd2', 'd4'],
    ['tốt từ cột hai hàng hai đến cột hai hàng bốn', 'b2', 'b4'],
    ['tốt từ cột bốn hàng hai đến cột bốn hàng bốn', 'd2', 'd4'],
    ['tốt từ cột 2 hàng 2 đến cột 2 hàng 4', 'b2', 'b4'],
    ['tốt từ cột 4 hàng 2 đến cột 4 hàng 4', 'd2', 'd4'],
    ['tốt cột bê hàng hai tới bê bốn', 'b2', 'b4'],
  ] as const;
  for (const [phrase, from, to] of cases) {
    const { say, sent } = await setup(t, start, [
      ['b2', ['b4']],
      ['d2', ['d4']],
    ]);
    assert.equal(say(phrase), true, phrase);
    assert.deepEqual(sent, [[from, to, undefined, true]], phrase);
    say('xác nhận');
    assert.deepEqual(sent, [[from, to, undefined, true]], phrase);
  }
});

test('numeric file coordinates cover all eight files and reject malformed explicit coordinates', async t => {
  const fen = '7k/8/8/8/8/8/PPPPPPPP/7K w - - 0 1';
  for (const [column, from, to] of [
    ['một', 'a2', 'a4'],
    ['hai', 'b2', 'b4'],
    ['ba', 'c2', 'c4'],
    ['bốn', 'd2', 'd4'],
    ['năm', 'e2', 'e4'],
    ['sáu', 'f2', 'f4'],
    ['bảy', 'g2', 'g4'],
    ['tám', 'h2', 'h4'],
  ] as const) {
    const { say, sent } = await setup(t, fen, [[from, [to]]]);
    say(`tốt từ cột ${column} hàng hai đến cột ${column} hàng bốn`);
    say('đồng ý');
    assert.deepEqual(sent, [[from, to, undefined, true]], column);
  }
  for (const phrase of [
    'tốt cột chín hàng hai tới cột chín hàng bốn',
    'tốt cột không hàng hai tới cột không hàng bốn',
    'tốt cột bê hàng hai tới cột bê hàng chín',
    'tốt cột hai hai tới cột hai bốn',
    'tốt hai hàng hai tới hai hàng bốn',
    'tốt cột hàng hai tới cột hàng bốn',
    'tốt cột bê hàng hai tới cột đê hàng bốn',
    'đừng đi tốt cột bê hàng hai tới cột bê hàng bốn',
    'tốt cột bê hàng hai tới cột bê hàng bốn sai',
  ]) {
    const { say, sent, move } = await setup(t, start, [
      ['b2', ['b4']],
      ['d2', ['d4']],
    ]);
    say(phrase);
    say('xác nhận');
    assert.ok(!move.question(), phrase);
    assert.deepEqual(sent, [], phrase);
  }
});

test('explicit coordinate phrases train every legal B/D alternative without illegal destinations', async t => {
  const { grammars } = await setup(t, start, [
    ['b2', ['b3', 'b4']],
    ['d2', ['d3', 'd4']],
  ]);
  const phrases = grammars.get('default')!;
  for (const phrase of [
    'tốt từ cột bê hàng hai đến cột bê hàng ba',
    'tốt từ cột bê hàng hai đến cột bê hàng bốn',
    'tốt từ cột đê hàng hai đến cột đê hàng ba',
    'tốt từ cột đê hàng hai đến cột đê hàng bốn',
    'tốt từ cột hai hàng hai đến cột hai hàng bốn',
    'tốt từ cột bốn hàng hai đến cột bốn hàng bốn',
  ])
    assert.ok(phrases.includes(phrase), phrase);
  assert.ok(phrases.includes('[unk]'));
  assert.ok(!phrases.some(p => p.includes('cột bê hàng năm')));
  assert.ok(!phrases.some(p => p.includes('cột hai hàng năm')));
});

test('numeric B/D columns retain their files with Black and a rotated board', async t => {
  for (const [number, from, to] of [
    ['hai', 'b7', 'b5'],
    ['bốn', 'd7', 'd5'],
  ] as const) {
    const { cg, say, sent } = await setup(t, start.replace(' w ', ' b '), [
      ['b7', ['b5']],
      ['d7', ['d5']],
    ]);
    cg.toggleOrientation();
    say(`tốt từ cột ${number} hàng bảy đến cột ${number} hàng năm`);
    assert.deepEqual(sent, [[from, to, undefined, true]]);
    say('xác nhận');
    assert.deepEqual(sent, [[from, to, undefined, true]], number);
  }
});

test('Vietnamese and English B/D file names preserve both coordinates', async t => {
  for (const [name, from, to] of [
    ['bê', 'b2', 'b4'],
    ['bờ', 'b2', 'b4'],
    ['bi', 'b2', 'b4'],
    ['đê', 'd2', 'd4'],
    ['dê', 'd2', 'd4'],
    ['dờ', 'd2', 'd4'],
    ['đờ', 'd2', 'd4'],
    ['đi', 'd2', 'd4'],
  ] as const) {
    for (const phrase of [
      `tốt ${name} hai ${name} bốn`,
      `tốt từ cột ${name} hàng hai đến cột ${name} hàng bốn`,
    ]) {
      const { say, sent } = await setup(t, start, [
        ['b2', ['b4']],
        ['d2', ['d4']],
      ]);
      assert.equal(say(phrase), true, phrase);
      assert.deepEqual(sent, [[from, to, undefined, true]]);
      say('đồng ý');
      assert.deepEqual(sent, [[from, to, undefined, true]], phrase);
    }
  }
});

test('English D coordinates and the Vietnamese move verb do not consume each other', async t => {
  for (const [phrase, from, to] of [
    ['đi e hai e bốn', 'e2', 'e4'],
    ['tốt đi từ e hai đến e bốn', 'e2', 'e4'],
    ['tốt e hai đi e bốn', 'e2', 'e4'],
    ['mã đi ép ba', 'g1', 'f3'],
    ['đi đi hai đi bốn', 'd2', 'd4'],
    ['tốt đi từ đi hai đến đi bốn', 'd2', 'd4'],
    ['tốt từ cột đi hàng hai đến đê bốn', 'd2', 'd4'],
  ] as const) {
    const { say, sent } = await setup(t, start, [
      ['e2', ['e4']],
      ['g1', ['f3']],
      ['d2', ['d4']],
    ]);
    assert.equal(say(phrase), true, phrase);
    assert.deepEqual(sent, [[from, to, undefined, true]]);
    say('xác nhận');
    assert.deepEqual(sent, [[from, to, undefined, true]], phrase);
  }
});

test('a single unlabelled English D cannot turn an ambiguous move verb into a destination', async t => {
  const fen = '7k/8/8/8/8/8/8/4K3 w - - 0 1';
  for (const phrase of ['vua đi một', 'đi một', 'đừng đi vua cột đi hàng một', 'vua đi một bước']) {
    const { say, move, sent } = await setup(t, fen, [['e1', ['d1']]]);
    say(phrase);
    say('xác nhận');
    assert.ok(!move.question(), phrase);
    assert.deepEqual(sent, [], phrase);
  }
  const { say, sent } = await setup(t, fen, [['e1', ['d1']]]);
  say('vua tới cột đi hàng một');
  say('xác nhận');
  assert.deepEqual(sent, [['e1', 'd1', undefined, true]]);
  for (const phrase of ['tốt bờ hai tới dờ bốn', 'tốt bi hai tới đi bốn']) {
    const rejected = await setup(t, start, [
      ['b2', ['b4']],
      ['d2', ['d4']],
    ]);
    rejected.say(phrase);
    rejected.say('đồng ý');
    assert.deepEqual(rejected.sent, [], phrase);
  }
});

test('phonetic B/D grammar covers legal aliases with words present in the pinned Vosk vocabulary', async t => {
  const { grammars } = await setup(t, start, [
    ['b2', ['b4']],
    ['d2', ['d4']],
  ]);
  const phrases = grammars.get('default')!;
  for (const phrase of [
    'tốt bờ hai bờ bốn',
    'tốt bi hai bi bốn',
    'tốt đờ hai đờ bốn',
    'tốt đi hai đi bốn',
    'tốt từ cột bờ hàng hai đến cột bờ hàng bốn',
    'tốt từ cột đờ hàng hai đến cột đờ hàng bốn',
    'tốt từ cột bi hàng hai đến cột bi hàng bốn',
    'tốt từ cột đi hàng hai đến cột đi hàng bốn',
  ])
    assert.ok(phrases.includes(phrase), phrase);
  assert.ok(
    !phrases.some(phrase => phrase.split(' ').includes('dờ')),
    'Primary model lacks dờ; keep it available to secondary parsing only',
  );
  assert.ok(!phrases.includes('tốt bi hai đi bốn'));
  assert.ok(phrases.includes('[unk]'));
});

test('Vietnamese recognizer uses legal command context and retains an unknown-speech path', async t => {
  const { grammars, move, cg } = await setup(t, start, [
    ['f2', ['f3', 'f4']],
    ['g1', ['f3', 'h3']],
  ]);
  const phrases = grammars.get('default')!;
  assert.ok(phrases.includes('ép hai ép bốn'));
  assert.ok(phrases.includes('ép hai ép ba'));
  assert.ok(phrases.includes('mã ép ba'));
  assert.ok(phrases.includes('xác nhận'));
  assert.ok(phrases.includes('[unk]'));
  assert.ok(!phrases.includes('tiếp theo'), 'Round input must not train on puzzle-only commands');
  assert.ok(!phrases.includes('ép hai ép năm'), 'Illegal destinations must not train the command recognizer');
  assert.ok(!phrases.some(p => p.split(' ').includes('f')), 'Do not train on the missing f vocabulary entry');
  const next = 'rnbqkbnr/pppppppp/8/8/5P2/8/PPPPP1PP/RNBQKBNR w KQkq - 0 2';
  cg.set({ fen: next, movable: { dests: new Map([['f4', ['f5']]]) } });
  move.update({ fen: next, canMove: true });
  assert.ok(!grammars.get('default')!.includes('ép hai ép bốn'));
  assert.ok(grammars.get('default')!.includes('ép bốn ép năm'));
});

test('Vietnamese direct submission bypasses the old countdown and never repeats on its timeout', async t => {
  const { say, sent } = await setup(t, start, [['e2', ['e3', 'e4']]], '3');
  t.mock.timers.enable({ apis: ['setTimeout'] });
  say('e hai e bốn');
  assert.deepEqual(sent, [['e2', 'e4', undefined, true]]);
  t.mock.timers.tick(10000);
  assert.equal(sent.length, 1);
});

test('cancelling after a direct move cannot repeat or undo that submitted move', async t => {
  const { move, say, sent } = await setup(t);
  say('e hai e bốn');
  say('huỷ bỏ');
  say('xác nhận');
  assert.deepEqual(sent, [['e2', 'e4', undefined, true]]);
  assert.equal(move.question(), false);
});

test('stopping continuous input clears unresolved arrows while push-to-talk release preserves them', async t => {
  const { cg, say, sent, voice } = await setup(t, '7k/8/8/8/8/5N2/8/1N5K w - - 0 1', [
    ['b1', ['d2']],
    ['f3', ['d2']],
  ]);
  say('mã đê hai');
  voice.mic.stop();
  assert.equal(cg.state.drawable.shapes.length, 2);
  voice.pushTalk = () => false;
  voice.mic.stop();
  say('xanh');
  assert.equal(cg.state.drawable.shapes.length, 0);
  assert.deepEqual(sent, []);
});

test('a board update invalidates arrow choices even at the same FEN', async t => {
  const fen = '7k/8/8/8/8/5N2/8/1N5K w - - 0 1';
  const { move, say, sent } = await setup(t, fen, [
    ['b1', ['d2']],
    ['f3', ['d2']],
  ]);
  say('mã đê hai');
  move.update({ fen, canMove: true });
  say('xanh');
  assert.deepEqual(sent, []);
});

test('an authoritative board update permits a new move after suppressing duplicate results', async t => {
  const { move, say, sent, cg } = await setup(t);
  say('tốt e hai e bốn');
  say('tốt e hai e ba');
  assert.equal(sent.length, 1);
  const fen = 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2';
  cg.set({ fen, movable: { dests: new Map([['e4', ['e5']]]) } });
  move.update({ fen, canMove: true });
  say('tốt e bốn e năm');
  assert.deepEqual(sent, [
    ['e2', 'e4', undefined, true],
    ['e4', 'e5', undefined, true],
  ]);
});

test('a source-square selection can be followed by a direct destination move', async t => {
  const { move, say, sent } = await setup(t, start, [['f2', ['f3', 'f4']]]);
  say('ép hai');
  assert.equal(move.question(), false);
  assert.deepEqual(sent, []);
  say('ép bốn');
  assert.deepEqual(sent, [['f2', 'f4', undefined, true]]);
});

test('a direct move never accepts a pending opponent request', async t => {
  const { move, say, sent } = await setup(t);
  const drawAnswers: boolean[] = [];
  move.listenForResponse('draw', answer => drawAnswers.push(answer));
  say('e hai e bốn');
  assert.deepEqual(sent, [['e2', 'e4', undefined, true]]);
  assert.deepEqual(drawAnswers, []);
});

test('out-of-turn and completed positions reject Vietnamese moves', async t => {
  const { move, say, sent } = await setup(t);
  move.update({ fen: start, canMove: false });
  say('e hai e bốn');
  say('xác nhận');
  assert.deepEqual(sent, []);
});

test('an illegal coordinate or unknown speech cannot be shortened into a legal move', async t => {
  const { say, sent } = await setup(t);
  for (const phrase of ['e hai e năm', 'đừng đi e hai e bốn', 'xin chào']) {
    say(phrase);
    say('xác nhận');
  }
  assert.deepEqual(sent, []);
});

test('two knights require disambiguation and then execute without confirmation', async t => {
  const { say, sent, cg } = await setup(t, '7k/8/8/8/8/5N2/8/1N5K w - - 0 1', [
    ['b1', ['d2']],
    ['f3', ['d2']],
  ]);
  say('mã d hai');
  say('xác nhận');
  assert.deepEqual(sent, []);
  assert.equal(cg.state.drawable.shapes.length, 2);
  say('xanh');
  assert.deepEqual(sent, [['b1', 'd2', undefined, true]]);
});

test('Vietnamese castling and promotion preserve the intended legal move', async t => {
  const castle = await setup(t, '4k3/8/8/8/8/8/8/R3K2R w KQ - 0 1', [['e1', ['a1', 'h1']]]);
  castle.say('nhập thành cánh vua');
  castle.say('xác nhận');
  assert.deepEqual(castle.sent, [['e1', 'h1', undefined, true]]);
  const promotion = await setup(t, '7k/4P3/8/8/8/8/8/7K w - - 0 1', [['e7', ['e8']]]);
  promotion.say('e tám phong mã');
  promotion.say('xác nhận');
  assert.deepEqual(promotion.sent, [['e7', 'e8', 'knight', true]]);
});

test('Vietnamese letter-name ép addresses the f-file without losing its coordinate', async t => {
  const { say, sent } = await setup(t, start, [['g1', ['f3', 'h3']]]);
  say('mã ép ba');
  say('xác nhận');
  assert.deepEqual(sent, [['g1', 'f3', undefined, true]]);
});

test('misheard dờ as giờ is a file only in explicit chess coordinates', async t => {
  for (const [phrase, from, to] of [
    ['tốt giờ hai tới giờ bốn', 'd2', 'd4'],
    ['tốt gờ hai tới gờ bốn', 'g2', 'g4'],
  ] as const) {
    const { say, sent } = await setup(t, start, [
      ['d2', ['d4']],
      ['g2', ['g4']],
    ]);
    say(phrase);
    assert.deepEqual(sent, [[from, to, undefined, true]], phrase);
  }
  for (const text of [
    'giờ hai tới giờ bốn',
    'tốt giờ bốn',
    'bây giờ tốt đê hai tới đê bốn',
    'không tốt giờ hai tới giờ bốn',
  ]) {
    const { say, sent } = await setup(t, start, [
      ['d2', ['d4']],
      ['g2', ['g4']],
    ]);
    say(text);
    assert.deepEqual(sent, [], text);
  }
});

test('incomplete numeric columns and misplaced từ still cannot propose a move', async t => {
  const { say, sent, move } = await setup(t, start, [['b2', ['b3', 'b4']]]);
  for (const text of ['tốt từ cột hàng hai đến cột hàng bốn', 'tốt bê hai từ bê bốn']) {
    say(text);
    assert.equal(move.question(), false);
    say('xác nhận');
  }
  assert.deepEqual(sent, []);
});

test('direct Vietnamese moves submit immediately with no confirmation question', async t => {
  const { say, sent, move } = await setup(t);
  assert.equal(say('tốt trắng e hai e bốn'), true);
  assert.deepEqual(sent, [['e2', 'e4', undefined, true]]);
  assert.equal(move.question(), false);
  say('xác nhận');
  assert.equal(sent.length, 1);
});

test('direct Vietnamese secondary recognition submits a legal move immediately', async t => {
  const { say, fallback, sent, move } = await setup(t, start, [['b2', ['b3', 'b4']]]);
  assert.equal(say('tốt từ cột hai a hai đến cột hai a bốn'), false);
  assert.equal(fallback('tốt từ cột hai hàng hai đến cột hai hàng bốn'), true);
  assert.deepEqual(sent, [['b2', 'b4', undefined, true]]);
  assert.equal(move.question(), false);
});

test('direct Vietnamese duplicate results cannot send twice before a position update', async t => {
  const { say, fallback, sent } = await setup(t);
  say('tốt e hai tới e bốn');
  say('tốt e hai tới e bốn');
  fallback('tốt e hai tới e ba');
  assert.deepEqual(sent, [['e2', 'e4', undefined, true]]);
});

test('direct Vietnamese illegal final recognition reports feedback without moving', async t => {
  const { say, fallback, sent, notices, move } = await setup(t);
  assert.equal(say('tốt e hai tới e năm'), false, 'Allow secondary ASR to recover primary errors');
  assert.deepEqual(notices, []);
  fallback('tốt e hai tới e năm');
  assert.match(notices.at(-1) ?? '', /không hợp lệ/u);
  assert.deepEqual(sent, []);
  assert.equal(move.question(), false);
});

test('direct Vietnamese unrecognized final speech reports feedback without dropping words', async t => {
  const { fallback, sent, notices } = await setup(t);
  fallback('đừng đi tốt e hai tới e bốn');
  assert.ok(notices.at(-1)?.length);
  assert.deepEqual(sent, []);
});

test('direct Vietnamese ambiguity asks for a source before executing the clarified move', async t => {
  const { say, sent, notices, move } = await setup(t, '7k/8/8/8/8/5N2/8/1N5K w - - 0 1', [
    ['b1', ['d2']],
    ['f3', ['d2']],
  ]);
  say('mã đê hai');
  assert.deepEqual(sent, []);
  assert.ok(notices.at(-1)?.length);
  assert.equal(move.question(), false);
  say('mã bê một tới đê hai');
  assert.deepEqual(sent, [['b1', 'd2', undefined, true]]);
});

test('direct Vietnamese incomplete one-word speech still shows final feedback', async t => {
  const { fallback, notices, sent } = await setup(t);
  fallback('mã');
  assert.ok(notices.at(-1)?.length);
  assert.deepEqual(sent, []);
});
