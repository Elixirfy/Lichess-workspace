import assert from 'node:assert/strict';
import { mock, test } from 'node:test';

import type { RecognizerOpts } from '../src/interfaces';

// IndexedDB and physical audio devices are the external boundaries in this test.
mock.module('lib/objectStorage', { namedExports: { objectStorage: async () => ({ count: async () => 1 }) } });
const { Mic } = await import('../src/mic');

function environment(denied = false, brokenModel = false) {
  const captures: RecognizerOpts[] = [];
  const connections = new Set<AudioNode>();
  let loaded = false;
  const retries: { samples: Float32Array; rate: number; words: string[]; signal: AbortSignal }[] = [];
  const track = { enabled: true, getSettings: () => ({ sampleRate: 16000 }) };
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: {
      getUserMedia: async () => {
        if (denied) throw new DOMException('Permission denied', 'NotAllowedError');
        return { getAudioTracks: () => [track] };
      },
    },
  });
  Object.assign(globalThis, {
    AudioContext: class {
      state = 'running';
      sampleRate = 16000;
      destination = {};
      createMediaStreamSource() {
        return {
          connect(node: AudioNode) {
            connections.add(node);
          },
          disconnect(node: AudioNode) {
            connections.delete(node);
          },
        };
      }
    },
  });
  Object.assign(site, {
    sound: { listeners: new Set() },
    asset: {
      url: (path: string) => path,
      loadEsm: async () => ({
        isLoaded: () => loaded,
        initModel: async () => {
          if (brokenModel) throw new Error('Invalid model archive');
          loaded = true;
        },
        initRecognizer: (opts: RecognizerOpts) => {
          captures.push(opts);
          return { connect() {}, disconnect() {} };
        },
        select() {},
        transcribe: async (samples: Float32Array, rate: number, words: string[], signal: AbortSignal) => {
          retries.push({ samples, rate, words, signal });
          return 'tốt bi hai bi bốn';
        },
      }),
    },
  });
  const mic = new Mic();
  mic.setLang('vi');
  mic.initRecognizer(['e', 'hai', 'bốn']);
  return { mic, track, captures, connections, retries };
}

test('unhandled short chess speech retries captured audio with all matching legal role phrases', async t => {
  const { mic, captures, retries } = environment();
  let requests = 0;
  t.mock.method(globalThis, 'fetch', async () => {
    requests++;
    return Response.json({ text: 'tốt bê hai từ bê bốn', speech: true });
  });
  const heard: string[] = [];
  mic.initRecognizer(
    [
      'tốt từ cột bi hàng hai đến cột bi hàng bốn',
      'tốt từ cột a hàng hai đến cột a hàng ba',
      'tốt từ cột hai hàng hai đến cột hai hàng bốn',
      'mã từ cột bê hàng một đến cột xê hàng ba',
    ],
    {
      fallback: true,
      listener: (text, type) => {
        if (type === 'fallback') heard.push(text);
        return text === 'tốt bi hai bi bốn';
      },
    },
  );
  await mic.start();
  const samples = new Float32Array(16000).fill(0.1);
  captures.at(-1)!.audioResult!('tốt bi hai từ bê bốn', samples, 16000);
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(retries.length, 1, 'The same audio must be decoded again, not repaired as text');
  assert.deepEqual(retries[0].samples, samples);
  assert.equal(retries[0].rate, 16000);
  assert.ok(retries[0].words.includes('tốt bi hai bi bốn'));
  assert.ok(
    retries[0].words.includes('tốt a hai tới a ba'),
    'The retry must include other legal files and destinations',
  );
  assert.ok(retries[0].words.includes('[unk]') && retries[0].words.includes('không'));
  assert.ok(!retries[0].words.some(phrase => phrase.includes('cột') || phrase.startsWith('mã')));
  assert.deepEqual(heard, ['tốt bi hai bi bốn']);
  assert.equal(requests, 0, 'An accepted local decode does not need HTTP ASR');
  mic.stop();
});

test('negation, controls and incomplete labelled columns never select the short acoustic retry', async t => {
  const { mic, captures, retries } = environment();
  t.mock.method(globalThis, 'fetch', async () => Response.json({ text: '', speech: false }));
  mic.initRecognizer(['tốt từ cột bê hàng hai đến cột bê hàng bốn'], {
    fallback: true,
    listener: () => false,
  });
  await mic.start();
  for (const text of [
    'không tốt bê hai từ bê bốn',
    'sai nhận',
    'tốt từ cột hàng hai đến cột hàng bốn',
    '[unk]',
  ]) {
    captures.at(-1)!.audioResult!(text, new Float32Array(16000), 16000);
    await new Promise(resolve => setTimeout(resolve, 0));
  }
  assert.equal(retries.length, 0);
  mic.stop();
});

test('a modal listener that consumed speech prevents secondary recognition', async t => {
  const { mic, captures } = environment();
  let requests = 0;
  t.mock.method(globalThis, 'fetch', async () => {
    requests++;
    return Response.json({ text: '', speech: false });
  });
  mic.initRecognizer(['ép'], { fallback: true, listener: () => mic.stopPropagation() });
  await mic.start();
  captures.at(-1)!.audioResult!('ép', new Float32Array(16000), 16000);
  assert.equal(requests, 0);
  assert.equal(mic.status, 'ép');
  mic.stop();
});

test('replacing a recognizer and stopping mic disconnect old source nodes', async () => {
  const { mic, connections } = environment();
  await mic.start();
  assert.equal(connections.size, 1);
  mic.initRecognizer(['mã', 'ép', 'ba']);
  assert.equal(connections.size, 1);
  mic.stop();
  assert.equal(connections.size, 0);
});

test('push-to-talk release accepts its final result, hard stop ignores it', async () => {
  const { mic, captures } = environment();
  const heard: string[] = [];
  mic.initRecognizer(['ép'], {
    listener: (text, type) => {
      if (type === 'full') heard.push(text);
      return true;
    },
  });
  await mic.start();
  mic.finish();
  captures.at(-1)!.broadcast('ép', 'full', 0);
  assert.deepEqual(heard, ['ép']);
  await mic.start();
  mic.stop();
  captures.at(-1)!.broadcast('mã', 'full', 0);
  assert.deepEqual(heard, ['ép']);
});

test('an empty final flush cannot replace the pending fallback for a spoken utterance', async t => {
  const { mic, captures } = environment();
  const replies: ((r: Response) => void)[] = [];
  const heard: string[] = [];
  t.mock.method(globalThis, 'fetch', () => new Promise<Response>(resolve => replies.push(resolve)));
  mic.initRecognizer(['ép'], {
    fallback: true,
    listener: (text, type) => {
      if (type === 'fallback') heard.push(text);
      return false;
    },
  });
  await mic.start();
  const receive = captures.at(-1)!.audioResult!;
  receive('[unk]', new Float32Array(16000), 16000);
  receive('', new Float32Array(3200), 16000);
  assert.equal(replies.length, 1, 'Trailing silence must not cancel the speech request');
  replies[0](Response.json({ text: 'ép hai ép bốn', speech: true }));
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.deepEqual(heard, ['ép hai ép bốn']);
  mic.stop();
});

test('denied microphone permission is displayed without an unhandled rejection', async () => {
  const { mic } = environment(true);
  await assert.doesNotReject(mic.start());
  assert.equal(mic.isListening, false);
  assert.equal(mic.isBusy, false);
  assert.equal(mic.status, 'No permission');
});

test('promotion context applies only to the current utterance with a whole promotion keyword', async t => {
  const { mic, captures } = environment();
  const requests: RequestInit[] = [];
  t.mock.method(globalThis, 'fetch', async (_url: string, init: RequestInit) => {
    requests.push(init);
    return Response.json({ text: '', speech: false });
  });
  mic.initRecognizer(['phong', 'xác nhận'], { fallback: true, listener: () => false });
  await mic.start();
  const receive = captures.at(-1)!.audioResult!;
  const audio = new Float32Array(16000).fill(0.1);
  for (const [text, context] of [
    ['tốt e bảy tới e tám phong tịnh hậu', 'promotion'],
    ['sai nhận', 'general'],
    ['đồng di', 'general'],
    ['phongx', 'general'],
    ['[unk]', 'general'],
  ]) {
    receive(text, audio, 16000);
    await new Promise(resolve => setTimeout(resolve, 0));
    const request = requests.at(-1)!;
    assert.equal(new Headers(request.headers).get('X-Voice-Context'), context, text);
    assert.deepEqual(new Float32Array(request.body as ArrayBuffer), audio);
  }
  assert.equal(requests.length, 5);
  mic.stop();
});

test('invalid model is displayed and leaves microphone stopped', async () => {
  const { mic, track } = environment(false, true);
  await assert.doesNotReject(mic.start());
  assert.equal(mic.isBusy, false);
  assert.equal(track.enabled, false);
  assert.match(mic.status, /Invalid model archive/);
});

test('coordinate context is utterance-scoped and promotion keeps priority', async t => {
  const { mic, captures } = environment();
  const requests: RequestInit[] = [];
  t.mock.method(globalThis, 'fetch', async (_url: string, init: RequestInit) => {
    requests.push(init);
    return Response.json({ text: '', speech: false });
  });
  mic.initRecognizer(['cột', 'phong', 'xác nhận'], { fallback: true, listener: () => false });
  await mic.start();
  const receive = captures.at(-1)!.audioResult!;
  const audio = new Float32Array(16000).fill(0.1);
  for (const [text, context] of [
    ['tốt từ cột hai a hai đến cột hai a bốn', 'coordinates'],
    ['sai nhận', 'general'],
    ['đồng di', 'general'],
    ['hủy nước đi', 'general'],
    ['tốt từ ô hàng hai đến cột hàng bốn', 'coordinates'],
    ['tốt e bảy tới e tám phong đến cột', 'promotion'],
    ['cộtx', 'general'],
  ]) {
    receive(text, audio, 16000);
    await new Promise(resolve => setTimeout(resolve, 0));
    assert.equal(new Headers(requests.at(-1)!.headers).get('X-Voice-Context'), context, text);
    assert.deepEqual(new Float32Array(requests.at(-1)!.body as ArrayBuffer), audio);
  }
  assert.equal(requests.length, 7);
  mic.stop();
});

test('overlapping site sounds keep input muted until all sounds finish', async () => {
  const { mic, track } = environment();
  await mic.start();
  const sound = (event: 'start' | 'stop') => site.sound.listeners.forEach(listener => listener(event));
  sound('start');
  sound('start');
  sound('stop');
  assert.equal(track.enabled, false);
  sound('stop');
  assert.equal(track.enabled, true);
  mic.stop();
  assert.equal(track.enabled, false);
});

test('move feedback updates the voice bar without sending text to recognition listeners', async () => {
  const { mic } = environment();
  const display: string[] = [];
  const heard: string[] = [];
  mic.setController(text => display.push(text));
  mic.addListener(text => {
    heard.push(text);
  });
  assert.equal(typeof mic.setStatus, 'function');
  mic.setStatus('Nước đi không hợp lệ. Hãy nói lại.');
  assert.equal(mic.status, 'Nước đi không hợp lệ. Hãy nói lại.');
  assert.equal(display.at(-1), mic.status);
  assert.deepEqual(heard, []);
});

test('a grammar replacement discards pending fallback before it can deliver a direct move', async t => {
  const { mic, captures } = environment();
  let reply!: (r: Response) => void;
  t.mock.method(
    globalThis,
    'fetch',
    () =>
      new Promise<Response>(resolve => {
        reply = resolve;
      }),
  );
  const heard: string[] = [];
  mic.initRecognizer(['ép'], { fallback: true, listener: () => false });
  await mic.start();
  captures.at(-1)!.audioResult!('[unk]', new Float32Array(16000), 16000);
  mic.initRecognizer(['mã'], {
    fallback: true,
    listener: (text, type) => {
      if (type === 'fallback') heard.push(text);
      return true;
    },
  });
  reply(Response.json({ text: 'tốt e hai e bốn', speech: true }));
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.deepEqual(heard, []);
  mic.stop();
});
