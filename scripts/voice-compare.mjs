// Export one shared PCM corpus and score both ASRs with the unchanged production parser.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createInterface } from 'node:readline';
import { audioCases, positions } from './voice-matrix-cases.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const lila = resolve(root, 'infra/lila-docker/repos/lila');
const target = resolve(root, process.env.VOICE_COMPARE_DIR || 'artifacts/voice-comparison');
const manifestFile = resolve(root, process.env.VOICE_COMPARE_MANIFEST || `${target}/dataset.json`);
const engines = (process.env.VOICE_COMPARE_ENGINES || 'vosk-open,vosk-position,phowhisper').split(',');
assert.ok(engines.every(name => /^[a-z0-9-]+$/.test(name)));
const fixtureRoot = resolve(root, 'scripts/fixtures/voice');
const hash = data => createHash('sha256').update(data).digest('hex');
const pnpm = resolve(lila, 'node_modules/.pnpm');
const core = (await readdir(pnpm)).find(name => /^playwright-core@\d/.test(name));
process.env.PLAYWRIGHT_BROWSERS_PATH ??= resolve(root, '.cache/playwright');
const { chromium } = await import(pathToFileURL(resolve(pnpm, core, 'node_modules/playwright-core/index.mjs')));
const { Chess } = await import(pathToFileURL(resolve(lila, 'node_modules/chessops/dist/esm/chess.js')));
const { parseFen } = await import(pathToFileURL(resolve(lila, 'node_modules/chessops/dist/esm/fen.js')));
const { chessgroundDests } = await import(pathToFileURL(resolve(lila, 'node_modules/chessops/dist/esm/compat.js')));
const base = process.env.BASE_URL || 'http://localhost:8080';
assert.ok(['localhost', '127.0.0.1'].includes(new URL(base).hostname));
const mode = process.argv[2] || 'prepare';
assert.ok(['prepare', 'score', 'serve', 'selfcheck'].includes(mode));
const states = Object.fromEntries(Object.entries(positions).map(([id, fen]) => {
  const pos = Chess.fromSetup(parseFen(fen).unwrap()).unwrap();
  return [id, { fen, turn: pos.turn, dests: [...chessgroundDests(pos)] }];
}));
const profiles = ['clean', 'quiet', 'loud', 'faster', 'noise20db'];
await mkdir(resolve(target, 'pcm'), { recursive: true });
const browser = await chromium.launch({ headless: true, args: ['--autoplay-policy=no-user-gesture-required'] });
const page = await browser.newPage();
const errors = [];
page.on('pageerror', e => errors.push(e.message));
await page.route('**/voice-comparison/*.wav', route => {
  const name = new URL(route.request().url()).pathname.split('/').at(-1);
  assert.match(name, /^[a-z0-9-]+\.wav$/);
  return route.fulfill({ path: resolve(fixtureRoot, name === 'bon.wav' ? name : `commands/${name}`), contentType: 'audio/wav' });
});

// The parser and grammar are taken from the production bundle. Legality comes
// from Chessops and the real Chessground; only the final application actions are captured.
const parserSession = async ({ item, state, texts = [], grammarOnly = false, measure = false, probeOnly = false }) => {
  const cg = window.lichess.chessground();
  cg.set({ fen: state.fen, turnColor: state.turn, orientation: state.turn,
    movable: { free: false, color: state.turn, dests: new Map(state.dests) } });
  cg.cancelMove(); cg.setShapes([]);
  localStorage.setItem('voice.useColors', item.numbers ? 'false' : 'true');
  const listeners = new Map(), grammars = new Map(), sent = [], actions = [], feedback = [];
  const mic = {
    initRecognizer: (words, opts = {}) => {
      grammars.set(opts.recId || 'default', words);
      if (opts.listener) listeners.set(opts.recId || 'default', opts.listener);
    },
    addListener: (listener, opts = {}) => listeners.set(opts.listenerId || 'default', listener),
    removeListener: id => listeners.delete(id), setRecognizer() {}, stopPropagation() {},
    setStatus: text => feedback.push(text),
    stop: () => listeners.get('default')?.('', 'stop'), isListening: true,
  };
  const root = {
    pluginMove: (from, to, role) => sent.push(from + to + ({ queen: 'q', rook: 'r', bishop: 'b', knight: 'n' }[role] || '')),
    redraw() {}, flipNow: () => actions.push('flip'), offerDraw: () => actions.push('draw'),
    resign: () => actions.push('resign'), takebackYes: () => actions.push('takeback'),
    rematch: () => { actions.push('rematch'); return false; },
  };
  const voice = { mic, lang: () => 'vi', enabled: () => true, pushTalk: () => true, flash() {} };
  const move = await site.asset.loadEsm('voice.move', { init: { root, voice,
    initial: { cg, fen: state.fen, canMove: true } } });
  await move.initGrammar();
  if (grammarOnly) return grammars.get('default');
  const say = text => listeners.get('default')?.(text, 'full');
  const started = performance.now();
  for (const text of texts) if (text) say(text);
  const candidates = [...new Set(cg.state.drawable.shapes.filter(s => s.dest).map(s => s.orig + s.dest))].sort();
  const ambiguous = !move.question() && candidates.length > 1;
  if (probeOnly) return { proposed: move.question() ? String(move.question().prompt) : null,
    ambiguous, candidates, automatic: { moves: sent.slice(), actions: actions.slice() }, feedback };
  if (item.choose) say(item.choose);
  const proposed = move.question() ? String(move.question().prompt) : null;
  const proposal_ms = performance.now() - started;
  const automatic = { moves: sent.slice(), actions: actions.slice() };
  // Confirm every proposal, including wrong ones. Do not use the expected UCI
  // to decide whether to confirm: this exposes valid-but-unintended moves.
  say('xác nhận');
  if (!item.uci) say('xác nhận');
  const correct = (!automatic.moves.length || !proposed) && !automatic.actions.length && !actions.length && (item.uci
    ? sent.length === 1 && sent[0] === item.uci && (!item.candidates || ambiguous && JSON.stringify(candidates) === JSON.stringify([...item.candidates].sort()))
    : !sent.length && !proposed);
  return { proposed, candidates, ambiguous, automatic, sent, actions, feedback, correct,
    execution: sent.length ? (automatic.moves.length ? 'direct' : 'confirmed') : 'none',
    wrongConfirmed: sent.some(uci => uci !== item.uci) || actions.length > 0,
    ...(measure ? { proposal_ms, proposal_and_confirmation_ms: performance.now() - started } : {}) };
};

try {
  const response = await page.goto(`${base}/analysis`);
  assert.equal(response.status(), 200);
  await page.waitForFunction(() => window.lichess?.chessground?.() && window.site?.asset?.loadEsm);
  if (mode === 'selfcheck') {
    const ambiguous = await page.evaluate(parserSession, { item: {}, state: states.start, texts: ['ép ba'] });
    assert.equal(ambiguous.ambiguous, true);
    assert.equal(ambiguous.correct, false, 'An ambiguous proposal is not a successful rejection');
    const rejected = await page.evaluate(parserSession, { item: {}, state: states.start, texts: ['đừng đi ép hai ép bốn'] });
    assert.equal(rejected.correct, true);
    const valid = await page.evaluate(parserSession, { item: { uci: 'f2f4' }, state: states.start, texts: ['ép hai ép bốn'] });
    assert.equal(valid.correct, true);
    assert.deepEqual(errors, []);
    console.log('Parser scorer self-check passed: ambiguous is not rejected; valid/unknown behave correctly.');
  } else if (mode === 'serve') {
    console.log(JSON.stringify({ ready: true }));
    for await (const line of createInterface({ input: process.stdin, crlfDelay: Infinity })) {
      const request = JSON.parse(line);
      assert.ok(typeof request.fen === 'string' || Object.hasOwn(states, request.position));
      const position = request.fen && Chess.fromSetup(parseFen(request.fen).unwrap()).unwrap();
      const state = position ? { fen: request.fen, turn: position.turn, dests: [...chessgroundDests(position)] } : states[request.position];
      assert.ok(request.grammar || Array.isArray(request.texts) && request.texts.every(t => typeof t === 'string'));
      const result = await page.evaluate(parserSession, { item: { numbers: !!request.numbers },
        state, texts: request.texts, probeOnly: true, grammarOnly: !!request.grammar });
      assert.deepEqual(errors, []);
      console.log(JSON.stringify(result));
    }
  } else if (mode === 'prepare') {
    const source = JSON.parse(await readFile(resolve(fixtureRoot, 'matrix-commands.json'), 'utf8'));
    const dataset = { sample_rate_hz: 16000, format: 'little-endian float32 mono PCM', profiles,
      source_kind: source.kind,
      browser_version: await browser.version(), node_version: process.version,
      production_manifest_sha256: hash(await readFile(resolve(lila, 'public/compiled/manifest.json'))),
      feature_patch_sha256: hash(await readFile(resolve(root, 'patches/lila-vietnamese-voice.patch'))),
      grammars: {}, audio: [], scenarios: [], diagnostics: [], parser_baseline: [], errors };
    for (const item of audioCases) {
      dataset.grammars[item.id] = await page.evaluate(parserSession, { item, state: states[item.position], grammarOnly: true });
      const text = source.cases.find(f => f.file === `commands/${item.clip}.wav`).text;
      const result = await page.evaluate(parserSession, { item, state: states[item.position], texts: [text] });
      assert.ok(result.correct, `Reference transcript must satisfy parser contract: ${item.id}`);
      dataset.parser_baseline.push({ id: item.id, text, ...result });
    }
    const files = [...source.cases, { file: 'bon.wav', text: 'bốn', sha256: '5cbf7e3e08afb3d5016b502e37348e58df27e7d6497d08af1be06818d0208e0d' }];
    for (const file of files) {
      assert.equal(hash(await readFile(resolve(fixtureRoot, file.file))), file.sha256);
      const clip = file.file.split('/').at(-1).replace('.wav', '');
      for (const profile of file.file === 'bon.wav' ? ['clean'] : profiles) {
        const encoded = await page.evaluate(async ({ clip, profile }) => {
          if (new Uint8Array(new Uint16Array([1]).buffer)[0] !== 1) throw new Error('Expected little-endian PCM');
          const audio = new AudioContext({ sampleRate: 16000 });
          const buffer = await audio.decodeAudioData(await (await fetch(`/voice-comparison/${clip}.wav`)).arrayBuffer());
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
            if (profile === 'noise20db') {
              seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
              value += (seed / 2 ** 32 * 2 - 1) * noiseScale;
            }
            samples[i] = Math.max(-1, Math.min(1, value));
          }
          const bytes = new Uint8Array(samples.buffer);
          let binary = '';
          for (let offset = 0; offset < bytes.length; offset += 32768)
            binary += String.fromCharCode(...bytes.subarray(offset, offset + 32768));
          await audio.close();
          return btoa(binary);
        }, { clip, profile });
        const bytes = Buffer.from(encoded, 'base64'), id = `${clip}:${profile}`;
        const pcm_file = `pcm/${clip}-${profile}.f32`;
        await writeFile(resolve(target, pcm_file), bytes);
        dataset.audio.push({ id, clip, profile, source_file: file.file, source_sha256: file.sha256,
          pcm_file, pcm_sha256: hash(bytes), frames: bytes.length / 4, duration_s: bytes.length / 4 / 16000,
          text: file.text, diagnostic: file.file === 'bon.wav' });
      }
    }
    for (const item of audioCases) for (const profile of profiles) {
      const audio_id = `${item.clip}:${profile}`, audio = dataset.audio.find(a => a.id === audio_id);
      dataset.scenarios.push({ ...item, id: `${item.id}:${profile}`, audio_id, profile,
        grammar_id: item.id, text: audio.text });
    }
    dataset.diagnostics.push({ id: 'isolated-bon:clean', audio_id: 'bon:clean',
      profile: 'clean', grammar_id: 'start-f4', text: 'bốn', diagnostic: true });
    assert.equal(dataset.audio.length, 66);
    assert.equal(dataset.scenarios.length, 95);
    assert.deepEqual(errors, []);
    await writeFile(resolve(target, 'dataset.json'), JSON.stringify(dataset, null, 2));
    console.log('Prepared 66 shared PCM inputs and 95 position scenarios.', hash(await readFile(resolve(target, 'dataset.json'))));
  } else {
    const rawDataset = await readFile(manifestFile);
    const dataset = JSON.parse(rawDataset);
    const scores = { dataset_sha256: hash(rawDataset), base, engines: {}, errors };
    for (const engine of engines) {
      const results = JSON.parse(await readFile(resolve(target, `${engine}.json`), 'utf8'));
      assert.equal(results.dataset_sha256, scores.dataset_sha256);
      assert.equal(results.configuration.diagnostic_limit, null);
      const rows = new Map(results.rows.map(r => [`${r.id}|${r.repeat}`, r]));
      scores.engines[engine] = [];
      for (let repeat = 0; repeat < results.configuration.repeats; repeat++) for (const item of dataset.scenarios) {
        const answer = rows.get(`${results.mode === 'sweep' ? item.audio_id : item.id}|${repeat}`);
        assert.ok(answer, `${engine} missing ${item.id}`);
        const fragments = answer.fragments || [answer.text];
        const canonicalFragments = answer.canonical_fragments || [answer.canonical_text];
        const started = performance.now();
        const raw = await page.evaluate(parserSession, { item, state: states[item.position], texts: fragments, measure: true });
        const canonical = await page.evaluate(parserSession, { item, state: states[item.position], texts: canonicalFragments, measure: true });
        scores.engines[engine].push({ id: item.id, repeat, audio_id: item.audio_id, profile: item.profile,
          expected_uci: item.uci, text: answer.text, canonical_text: answer.canonical_text, raw, canonical,
          parser_and_browser_roundtrips_ms: performance.now() - started });
      }
      console.log(engine, JSON.stringify(Object.fromEntries(['raw', 'canonical'].map(kind => [kind, {
        correct: scores.engines[engine].filter(r => r[kind].correct).length, total: scores.engines[engine].length,
        wrongConfirmed: scores.engines[engine].filter(r => r[kind].wrongConfirmed).length,
      }]))));
    }
    assert.deepEqual(errors, []);
    await writeFile(resolve(target, 'move-scores.json'), JSON.stringify(scores, null, 2));
  }
} finally { await browser.close(); }
