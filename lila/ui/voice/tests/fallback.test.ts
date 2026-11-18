import assert from 'node:assert/strict';
import { test } from 'node:test';

import { SpeechFallback, UtteranceAudio } from '../src/fallback';

test('worker acknowledgements keep later audio out of an earlier utterance', () => {
  const audio = new UtteranceAudio(16000);
  for (const samples of [
    [1, 2],
    [3, 4],
    [5, 6],
  ])
    audio.push(new Float32Array(samples));
  assert.equal(audio.acknowledge(false), undefined);
  const first = audio.acknowledge(true);
  assert.ok(first);
  assert.deepEqual([...first], [1, 2, 3, 4]);
  assert.equal(audio.acknowledge(false), undefined);
  audio.flush();
  assert.deepEqual([...audio.acknowledge(true)!], [5, 6]);
});

test('overlong utterances are discarded instead of submitting a truncated command', () => {
  const audio = new UtteranceAudio(16000);
  audio.push(new Float32Array(16000 * 13));
  assert.equal(audio.acknowledge(true), undefined);
  audio.push(new Float32Array([1, 2, 3]));
  const next = audio.acknowledge(true);
  assert.ok(next);
  assert.deepEqual([...next], [1, 2, 3]);
});

test('overflow in later queued audio does not corrupt a completed earlier utterance', () => {
  const audio = new UtteranceAudio(16000);
  for (const samples of [new Float32Array([1, 2]), new Float32Array(16000 * 13)]) audio.push(samples);
  const first = audio.acknowledge(true);
  assert.ok(first);
  assert.deepEqual([...first], [1, 2]);
  assert.equal(audio.acknowledge(true), undefined);
});

test('late fallback cannot deliver after cancellation or a newer utterance', async t => {
  const responses: ((r: Response) => void)[] = [];
  t.mock.method(globalThis, 'fetch', () => new Promise<Response>(resolve => responses.push(resolve)));
  const fallback = new SpeechFallback();
  const heard: string[] = [];
  const status: string[] = [];
  const run = () =>
    fallback.run(
      new Float32Array(16000),
      16000,
      text => heard.push(text),
      s => status.push(s),
    );
  const old = run();
  assert.equal(responses.length, 1);
  fallback.cancel();
  responses[0](Response.json({ text: 'ép hai ép bốn', speech: true }));
  await old;
  assert.deepEqual(heard, []);
  const a = run();
  const b = run();
  responses[2](Response.json({ text: 'mã ép ba', speech: true }));
  await b;
  responses[1](Response.json({ text: 'ép hai ép bốn', speech: true }));
  await a;
  assert.deepEqual(heard, ['mã ép ba']);
});

test('non-speech and service failure do not inject a command', async t => {
  const fallback = new SpeechFallback();
  const heard: string[] = [];
  const status: string[] = [];
  t.mock.method(globalThis, 'fetch', async () => Response.json({ text: '', speech: false }));
  await fallback.run(
    new Float32Array(16000),
    16000,
    t => heard.push(t),
    t => status.push(t),
  );
  assert.deepEqual(heard, []);
  assert.ok(status.at(-1)?.length);
  t.mock.method(globalThis, 'fetch', async () => new Response('', { status: 429 }));
  await assert.doesNotReject(
    fallback.run(
      new Float32Array(16000),
      16000,
      t => heard.push(t),
      t => status.push(t),
    ),
  );
  assert.deepEqual(heard, []);
});

test('a rejected local decode proceeds to HTTP ASR, cancellation cannot start HTTP or deliver', async t => {
  const fallback = new SpeechFallback();
  const heard: string[] = [];
  let requests = 0;
  t.mock.method(globalThis, 'fetch', async () => {
    requests++;
    return Response.json({ text: 'tốt giờ hai tới giờ bốn', speech: true });
  });
  const run = (recognize: (signal: AbortSignal) => Promise<string | undefined>) =>
    fallback.run(
      new Float32Array(16000),
      16000,
      text => heard.push(text),
      () => {},
      'general',
      { recognize, accept: () => false },
    );
  let decode!: (text: string) => void;
  const old = run(
    () =>
      new Promise(resolve => {
        decode = resolve;
      }),
  );
  assert.equal(requests, 0);
  fallback.cancel();
  decode('tốt bi hai bi bốn');
  await old;
  assert.equal(requests, 0);
  assert.deepEqual(heard, []);
  await run(async () => 'invalid');
  assert.equal(requests, 1);
  assert.deepEqual(heard, ['tốt giờ hai tới giờ bốn']);
});
