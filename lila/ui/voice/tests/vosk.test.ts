import assert from 'node:assert/strict';
import { mock, test } from 'node:test';

import type { RecognizerOpts } from '../src/interfaces';

const recognizers: FakeRecognizer[] = [];
class FakeRecognizer {
  handlers = new Map<string, (msg: any) => void>();
  removed = false;
  constructor() {
    recognizers.push(this);
  }
  on(event: string, handler: (msg: any) => void) {
    this.handlers.set(event, handler);
  }
  remove() {
    this.removed = true;
  }
  retrieveFinalResult() {}
  acceptWaveform() {}
  acceptWaveformFloat() {}
  emit(text: string) {
    this.handlers.get('result')!({ result: { text } });
  }
}
class FakeClient {
  KaldiRecognizer = FakeRecognizer;
  handlers = new Map<string, (msg: any) => void>();
  terminated = false;
  constructor() {
    const load = loadClient;
    queueMicrotask(() => load(this));
  }
  on(event: string, handler: (msg: any) => void) {
    this.handlers.set(event, handler);
  }
  emit(event: string, message: any) {
    this.handlers.get(event)?.(message);
  }
  terminate() {
    this.terminated = true;
  }
}
const loaded = (client: FakeClient) => client.emit('load', { result: true });
let loadClient: (client: FakeClient) => void = loaded;
mock.module('@lichess-org/vosk-browser', { namedExports: { VoskClient: FakeClient } });
const { initModule } = await import('../src/voice.vosk');

test('late results from replaced position recognizers are discarded', async () => {
  Object.assign(site, { asset: { url: (path: string) => path } });
  const vosk = initModule();
  await vosk.initModel('/model.tar.gz', 'vi');
  const heard: string[] = [];
  const opts = {
    words: ['e', 'hai', 'bốn'],
    recId: 'default',
    partial: false,
    audioCtx: { sampleRate: 16000, createScriptProcessor: () => ({}) },
    broadcast: (text: string) => heard.push(text),
  } as unknown as RecognizerOpts;
  vosk.initRecognizer(opts);
  const old = recognizers.at(-1)!;
  vosk.initRecognizer(opts);
  assert.equal(old.removed, true, 'Replacing an inactive recognizer must release its model resources');
  old.emit('e hai e bốn');
  recognizers.at(-1)!.emit('mã f ba');
  assert.deepEqual(heard, ['mã f ba']);
});

test('full results carry only audio acknowledged for that utterance, including an empty transcript', async () => {
  Object.assign(site, { asset: { url: (path: string) => path } });
  const vosk = initModule();
  await vosk.initModel('/model.tar.gz', 'vi');
  const packets: number[][] = [];
  const node = {} as ScriptProcessorNode;
  vosk.initRecognizer({
    words: ['ép', 'bốn'],
    recId: 'default',
    partial: false,
    audioCtx: { sampleRate: 16000, createScriptProcessor: () => node },
    broadcast() {},
    audioResult: (_text: string, samples: Float32Array) => packets.push([...samples]),
  } as unknown as RecognizerOpts);
  vosk.select('default');
  const rec = recognizers.at(-1)!;
  for (const samples of [
    [1, 2],
    [3, 4],
    [5, 6],
  ])
    node.onaudioprocess!({ inputBuffer: { getChannelData: () => new Float32Array(samples) } } as any);
  rec.handlers.get('partialresult')?.({ result: { partial: '' } });
  rec.emit('');
  assert.deepEqual(packets, [[1, 2, 3, 4]]);
  rec.handlers.get('partialresult')?.({ result: { partial: '' } });
  vosk.select(false);
  rec.emit('ép bốn');
  assert.deepEqual(packets, [
    [1, 2, 3, 4],
    [5, 6],
  ]);
});

test('a failed language load cannot report the terminated previous model as ready', async () => {
  const vosk = initModule();
  loadClient = loaded;
  await vosk.initModel('/vi.tar.gz', 'vi');
  let failed!: FakeClient;
  loadClient = client => {
    failed = client;
    client.emit('error', { error: 'Invalid archive' });
  };
  await assert.rejects(vosk.initModel('/bad.tar.gz', 'fr'), /Invalid archive/);
  assert.equal(vosk.isLoaded(), false);
  assert.equal(failed.terminated, true);
  loadClient = loaded;
  await vosk.initModel('/vi.tar.gz', 'vi');
  assert.equal(vosk.isLoaded('vi'), true);
});

test('a slow old model load cannot replace a newly selected language', async () => {
  const vosk = initModule();
  let finish!: () => void;
  loadClient = client => {
    finish = () => loaded(client);
  };
  const old = vosk.initModel('/slow.tar.gz', 'fr');
  loadClient = loaded;
  await vosk.initModel('/vi.tar.gz', 'vi');
  finish();
  await old;
  assert.equal(vosk.isLoaded('vi'), true);
  assert.equal(vosk.isLoaded('fr'), false);
});

test('an unresponsive model load times out and releases its worker', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  let pending!: FakeClient;
  loadClient = client => {
    pending = client;
  };
  const vosk = initModule();
  const loading = vosk.initModel('/unresponsive.tar.gz', 'vi');
  const rejected = assert.rejects(loading, /timed out/);
  await Promise.resolve();
  t.mock.timers.tick(30000);
  await rejected;
  assert.equal(pending.terminated, true);
  assert.equal(vosk.isLoaded(), false);
  loadClient = loaded;
});

test('one-shot decoding waits for worker acknowledgements, accepts a full grammar phrase and cleans up', async () => {
  const vosk = initModule();
  await vosk.initModel('/vi.tar.gz', 'vi');
  assert.equal(typeof vosk.transcribe, 'function');
  const samples = new Float32Array(16000).fill(0.2);
  const pending = vosk.transcribe(
    samples,
    16000,
    ['tốt bi hai bi bốn', '[unk]', 'không'],
    new AbortController().signal,
  );
  const rec = recognizers.at(-1)!;
  let resolved = false;
  void pending.then(() => {
    resolved = true;
  });
  rec.handlers.get('partialresult')?.({ result: { partial: '' } });
  await Promise.resolve();
  assert.equal(resolved, false);
  rec.emit('tốt bi hai bi bốn');
  assert.equal(await pending, 'tốt bi hai bi bốn');
  assert.equal(rec.removed, true);
  assert.equal(samples[0], Math.fround(0.2));
});

test('one-shot decoding rejects word-loop guesses and is released on abort, timeout and model replacement', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const vosk = initModule();
  await vosk.initModel('/vi.tar.gz', 'vi');
  assert.equal(typeof vosk.transcribe, 'function');
  const grammar = ['tốt bi hai bi bốn', '[unk]', 'không'];
  const run = (signal = new AbortController().signal) =>
    vosk.transcribe(new Float32Array(16000), 16000, grammar, signal);
  const invalid = run();
  const invalidRec = recognizers.at(-1)!;
  invalidRec.emit('tốt tốt bi hai bi bốn');
  invalidRec.emit('');
  assert.equal(await invalid, undefined);
  const controller = new AbortController();
  const aborted = run(controller.signal);
  const abortedRec = recognizers.at(-1)!;
  controller.abort();
  assert.equal(await aborted, undefined);
  assert.equal(abortedRec.removed, true);
  abortedRec.emit('tốt bi hai bi bốn');
  const timed = run();
  const timedRec = recognizers.at(-1)!;
  t.mock.timers.tick(2000);
  assert.equal(await timed, undefined);
  assert.equal(timedRec.removed, true);
  const old = run();
  const oldRec = recognizers.at(-1)!;
  await vosk.initModel('/fr.tar.gz', 'fr');
  assert.equal(await old, undefined);
  assert.equal(oldRec.removed, true);
});
