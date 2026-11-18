import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { audioCases, positions, textCases } from './voice-matrix-cases.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const lila = resolve(root, 'infra/lila-docker/repos/lila');
const pnpm = resolve(lila, 'node_modules/.pnpm');
const core = (await readdir(pnpm)).find(name => /^playwright-core@\d/.test(name));
process.env.PLAYWRIGHT_BROWSERS_PATH ??= resolve(root, '.cache/playwright');
const { chromium } = await import(pathToFileURL(resolve(pnpm, core, 'node_modules/playwright-core/index.mjs')));
const { Chess } = await import(pathToFileURL(resolve(lila, 'node_modules/chessops/dist/esm/chess.js')));
const { parseFen } = await import(pathToFileURL(resolve(lila, 'node_modules/chessops/dist/esm/fen.js')));
const { chessgroundDests } = await import(pathToFileURL(resolve(lila, 'node_modules/chessops/dist/esm/compat.js')));
const base = process.env.BASE_URL || 'http://localhost:8080';
assert.ok(['localhost', '127.0.0.1'].includes(new URL(base).hostname));
const fixtures = JSON.parse(await readFile(resolve(root, 'scripts/fixtures/voice/matrix-commands.json'), 'utf8'));
for (const item of fixtures.cases) assert.equal(createHash('sha256').update(
  await readFile(resolve(root, 'scripts/fixtures/voice', item.file))).digest('hex'), item.sha256);
const states = Object.fromEntries(Object.entries(positions).map(([id, fen]) => {
  const pos = Chess.fromSetup(parseFen(fen).unwrap()).unwrap();
  return [id, { fen, turn: pos.turn, dests: [...chessgroundDests(pos)] }];
}));
const profiles = process.env.VOICE_MATRIX_QUICK === '1' ? ['clean']
  : ['clean', 'quiet', 'loud', 'faster', 'noise20db'];
const rates = [16000, 44100, 48000];
const artifacts = resolve(root, 'artifacts/voice');
await mkdir(artifacts, { recursive: true });
const report = { base, kind: 'Production Vosk + parser + real Chessground; move submission captured at the root boundary',
  fixtures: fixtures.kind, profiles, rates, errors: [], audio: [], text: [] };
const browser = await chromium.launch({ headless: true, args: ['--autoplay-policy=no-user-gesture-required'] });
const context = await browser.newContext();
// Observe the real Worker protocol so silence/OOV tests wait for the flush reply,
// rather than passing early before a late recognition result arrives.
await context.addInitScript(() => {
  const NativeWorker = window.Worker;
  window.__voiceReplies = new Map();
  window.Worker = class extends NativeWorker {
    constructor(...args) {
      super(...args);
      this.addEventListener('message', ({ data }) => {
        const record = window.__voiceReplies.get(data?.recognizerId);
        if (record && ['result', 'partialresult'].includes(data.event)) {
          record.received++;
          if (record.flushed && record.received >= record.sent) record.finish?.();
        }
      });
    }
    postMessage(message, ...args) {
      if (message.action === 'create') {
        window.__latestVoiceRec = message.recognizerId;
        window.__voiceReplies.set(message.recognizerId, { sent: 0, received: 0, flushed: false });
      }
      const record = window.__voiceReplies.get(message.recognizerId);
      if (record && ['audioChunk', 'retrieveFinalResult'].includes(message.action)) {
        record.sent++;
        if (message.action === 'retrieveFinalResult') record.flushed = true;
      }
      return super.postMessage(message, ...args);
    }
  };
});
const page = await context.newPage();
page.on('pageerror', error => report.errors.push(error.message));
await page.route('**/voice-matrix/*.wav', route => route.fulfill({
  path: resolve(root, 'scripts/fixtures/voice/commands', new URL(route.request().url()).pathname.split('/').at(-1)),
  contentType: 'audio/wav',
}));
try {
  let response;
  for (let attempt = 0; attempt < 45; attempt++) {
    response = await page.goto(`${base}/analysis`);
    if (response.status() === 200) break;
    await page.waitForTimeout(1000);
  }
  assert.equal(response.status(), 200);
  await page.waitForFunction(() => window.lichess?.chessground?.() && window.site?.asset?.loadEsm);
  await page.evaluate(async () => {
    window.__matrixVosk = await site.asset.loadEsm('voice.vosk');
    await window.__matrixVosk.initModel(site.asset.url('lifat/vosk/model-vi-0.4.tar.gz'), 'vi');
    window.__matrixAudio = new Map();
  });
  const run = async (item, rate, profile, orientation) => {
    const result = await page.evaluate(async ({ item, state, rate, profile, orientation }) => {
      const cg = window.lichess.chessground();
      cg.set({ fen: state.fen, turnColor: state.turn, orientation,
        movable: { free: false, color: state.turn, dests: new Map(state.dests) } });
      cg.cancelMove();
      cg.setShapes([]);
      localStorage.setItem('voice.useColors', item.numbers ? 'false' : 'true');
      const listeners = new Map(), grammars = new Map(), sent = [], actions = [];
      const microphone = {
        initRecognizer: (words, opts = {}) => {
          grammars.set(opts.recId || 'default', words);
          if (opts.listener) listeners.set(opts.recId || 'default', opts.listener);
        },
        addListener: (listener, opts = {}) => listeners.set(opts.listenerId || 'default', listener),
        removeListener: id => listeners.delete(id), setRecognizer() {}, stopPropagation() {},
        stop: () => listeners.get('default')?.('', 'stop'), isListening: true,
      };
      const say = text => listeners.get('default')?.(text, 'full');
      const root = { pluginMove: (from, to, role) => sent.push(from + to + ({ queen: 'q', rook: 'r', bishop: 'b', knight: 'n' }[role] || '')),
        redraw() {}, flipNow: () => actions.push('flip'), offerDraw: () => actions.push('draw'),
        resign: () => actions.push('resign'), takebackYes: () => actions.push('takeback'),
        rematch: () => { actions.push('rematch'); return false; } };
      const voice = { mic: microphone, lang: () => 'vi', enabled: () => true, pushTalk: () => true, flash() {} };
      const move = await site.asset.loadEsm('voice.move', { init: { root, voice,
        initial: { cg, fen: state.fen, canMove: item.canMove !== false } } });
      await move.initGrammar();
      const heard = [];
      if (item.clip) {
        let audio = window.__matrixAudio.get(rate);
        if (!audio) { audio = new AudioContext({ sampleRate: rate }); window.__matrixAudio.set(rate, audio); }
        const buffer = await audio.decodeAudioData(await (await fetch(`/voice-matrix/${item.clip}.wav`)).arrayBuffer());
        const original = buffer.getChannelData(0);
        const speed = profile === 'faster' ? 1.15 : 1;
        const samples = new Float32Array(Math.ceil(original.length / speed));
        let energy = 0;
        for (const value of original) energy += value * value;
        const noiseScale = Math.sqrt(energy / original.length) / 10 * Math.sqrt(3);
        let seed = 0x12345678;
        for (let i = 0; i < samples.length; i++) {
          const pos = i * speed, left = Math.floor(pos), fraction = pos - left;
          let value = (original[left] || 0) * (1 - fraction) + (original[left + 1] || 0) * fraction;
          if (profile === 'quiet') value *= 0.5;
          if (profile === 'loud') value *= 1.8;
          if (profile === 'noise20db') { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; value += (seed / 2 ** 32 * 2 - 1) * noiseScale; }
          samples[i] = Math.max(-1, Math.min(1, value));
        }
        const vosk = window.__matrixVosk;
        const node = vosk.initRecognizer({ recId: 'matrix', words: grammars.get('default'), audioCtx: audio, partial: false,
          broadcast: text => { heard.push(text); say(text); } });
        const record = window.__voiceReplies.get(window.__latestVoiceRec);
        vosk.select('matrix');
        for (let offset = 0; offset < samples.length; offset += node.bufferSize) {
          const frame = audio.createBuffer(1, Math.min(node.bufferSize, samples.length - offset), rate);
          frame.copyToChannel(samples.subarray(offset, offset + frame.length), 0);
          node.onaudioprocess({ inputBuffer: frame });
        }
        vosk.select(false);
        await new Promise((resolve, reject) => {
          const timeout = setTimeout(() => reject(new Error('Vosk flush did not complete')), 15000);
          record.finish = () => { clearTimeout(timeout); resolve(); };
          if (record.flushed && record.received >= record.sent) record.finish();
        });
      } else say(item.text);
      const before = sent.slice(), automaticActions = actions.slice();
      const candidates = [...new Set(cg.state.drawable.shapes.filter(s => s.dest).map(s => s.orig + s.dest))].sort();
      const ambiguous = !move.question() && candidates.length > 1;
      if (item.choose) say(item.choose);
      if (item.cancel) { say(item.cancel); say('xác nhận'); }
      if (!item.uci && !item.action && !item.cancel) { say('xác nhận'); say('xác nhận'); }
      const question = move.question();
      const proposed = question && String(question.prompt);
      const intended = item.uci && proposed && proposed.includes(`${item.uci.slice(0, 2)} → ${item.uci.slice(2, 4)}`);
      if (intended && !item.cancel) say('xác nhận');
      if (item.action && question && !item.cancel) say('xác nhận');
      const passed = before.length === 0 && automaticActions.length === 0 && (item.action
        ? sent.length === 0 && actions.length === 1 && actions[0] === item.action
        : item.uci
        ? sent.length === 1 && sent[0] === item.uci && (!item.candidates || ambiguous && JSON.stringify(candidates) === JSON.stringify([...item.candidates].sort()))
        : sent.length === 0 && actions.length === 0 && !proposed);
      return { heard, proposed, candidates, automaticSubmissions: before, automaticActions, sent, actions, passed,
        grammarSize: grammars.get('default')?.length };
    }, { item, state: states[item.position], rate, profile, orientation });
    const expectedText = item.clip && fixtures.cases.find(f => f.file === `commands/${item.clip}.wav`)?.text;
    return { ...item, rate, profile, orientation, expectedText, ...result,
      ...(expectedText ? { transcriptExact: result.heard.join(' ') === expectedText } : {}) };
  };
  for (const item of textCases) for (const orientation of ['white', 'black']) {
    const result = await run(item, 0, 'text', orientation);
    report.text.push(result);
    if (!result.passed) console.log('TEXT FAIL', result.id, result.orientation, result.proposed, result.sent);
  }
  for (const rate of rates) for (const profile of profiles) {
    for (const item of audioCases) {
      const result = await run(item, rate, profile, states[item.position].turn);
      report.audio.push(result);
      if (!result.passed) console.log('AUDIO FAIL', result.id, rate, profile, result.heard, result.proposed);
    }
    console.log('Completed', rate, profile);
  }
  const summarize = rows => ({ passed: rows.filter(r => r.passed).length, total: rows.length });
  report.summary = { text: summarize(report.text), cleanAudio: summarize(report.audio.filter(r => r.profile === 'clean')),
    audioByProfile: Object.fromEntries(profiles.map(p => [p, summarize(report.audio.filter(r => r.profile === p))])),
    rawTranscriptExact: report.audio.filter(r => r.transcriptExact).length,
    unexpectedProposals: report.audio.filter(r => !r.passed && r.proposed).length,
    unexpectedConfirmedMoves: report.audio.filter(r => !r.uci && r.sent.length).length,
    automaticSubmissions: [...report.text, ...report.audio].reduce((n, r) => n + r.automaticSubmissions.length + r.automaticActions.length, 0) };
  report.status = [...report.text, ...report.audio].every(r => r.passed) && !report.errors.length ? 'passed' : 'failed';
  if (report.status !== 'passed') process.exitCode = 1;
  console.log(JSON.stringify(report.summary));
} catch (error) { report.status = 'failed'; report.failure = error.stack; process.exitCode = 1; console.error(error); }
finally {
  await writeFile(resolve(artifacts, 'matrix-report.json'), JSON.stringify(report, null, 2));
  await browser.close();
}
