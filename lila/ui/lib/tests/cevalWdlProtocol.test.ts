import assert from 'node:assert/strict';
import { test } from 'node:test';

import { Protocol } from '../src/ceval/protocol';
import type { Work, EngineInfo } from '../src/ceval/types';
import type { LocalEval } from '../src/tree/types';

function engine(ply: number, wdlOption = true, threatMode = false) {
  const sent: string[] = [];
  const emitted: LocalEval[] = [];
  const protocol = new Protocol({ id: 'fixture', name: 'Stockfish', tech: 'NNUE' } as EngineInfo);
  protocol.connected(command => sent.push(command));
  if (wdlOption) protocol.received('option name UCI_ShowWDL type check default false');
  protocol.received('uciok');
  protocol.compute({
    variant: 'chess',
    ply,
    path: 'test',
    threatMode,
    multiPv: 1,
    threads: 1,
    initialFen: 'startpos',
    currentFen: 'fixture',
    moves: [],
    search: { depth: 1 },
    emit: (ev: LocalEval | undefined) => {
      if (ev) emitted.push(ev);
    },
  } as Work);
  return { protocol, sent, emitted };
}

test('only engines advertising WDL are asked to emit it', () => {
  assert.ok(engine(0).sent.includes('setoption name UCI_ShowWDL value true'));
  assert.ok(!engine(0, false).sent.some(command => command.includes('UCI_ShowWDL')));
});

test('UCI WDL is normalized to White at both sides to move and in threat mode', () => {
  for (const [ply, threat, expected] of [
    [0, false, { white: 0.1, draw: 0.8, black: 0.1 }],
    [1, false, { white: 0.03, draw: 0.77, black: 0.2 }],
    [1, true, { white: 0.2, draw: 0.77, black: 0.03 }],
  ] as const) {
    const { protocol, emitted } = engine(ply, true, threat);
    protocol.received(
      `info depth 1 nodes 10 time 1 score cp 20 wdl ${ply ? '200 770 30' : '100 800 100'} pv e2e4`,
    );
    assert.equal(emitted.length, 1);
    assert.deepEqual((emitted[0] as LocalEval & { wdl?: unknown }).wdl, expected);
  }
});

test('invalid and missing WDL never reuse the previous search WDL', () => {
  for (const input of ['', 'wdl 100 800 101', 'wdl -1 1000 1', 'wdl nope 800 200']) {
    const { protocol, emitted } = engine(0);
    protocol.received(`info depth 1 nodes 10 time 1 score cp 20 ${input} pv e2e4`);
    assert.equal(emitted.length, 1);
    assert.equal((emitted[0] as LocalEval & { wdl?: unknown }).wdl, undefined);
  }
});

test('a stopped search cannot deliver WDL for the newly selected position', () => {
  const { protocol, emitted } = engine(0);
  protocol.compute(undefined);
  protocol.received('info depth 1 nodes 10 time 1 score cp 20 wdl 900 100 0 pv e2e4');
  assert.deepEqual(emitted, []);
});
