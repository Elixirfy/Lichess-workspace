import assert from 'node:assert/strict';
import { createHash, randomBytes } from 'node:crypto';
import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const out = resolve(root, process.env.VOICE_LIVE_OUTPUT || 'artifacts/voice-live');
await mkdir(out, { recursive: true });
const pnpm = resolve(root, 'infra/lila-docker/repos/lila/node_modules/.pnpm');
const core = (await readdir(pnpm)).find(n => /^playwright-core@\d/.test(n));
process.env.PLAYWRIGHT_BROWSERS_PATH ??= resolve(root, '.cache/playwright');
const { chromium } = await import(pathToFileURL(resolve(pnpm, core, 'node_modules/playwright-core/index.mjs')));
const base = 'http://localhost:8080';
const report = { base, checks: [], errors: [], responses: [], heard: [], textCommands: [] };
const fixture = JSON.parse(await readFile(resolve(root, 'scripts/fixtures/voice/live.json'), 'utf8'));
const fixturePath = resolve(root, 'scripts/fixtures/voice', fixture.file);
assert.equal(createHash('sha256').update(await readFile(fixturePath)).digest('hex'), fixture.sha256);
const check = (ok, name) => { assert.ok(ok, name); report.checks.push(name); console.log(name); };
const browser = await chromium.launch({ headless: true, args: [
  '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream',
  '--autoplay-policy=no-user-gesture-required',
  `--use-file-for-fake-audio-capture=${resolve(root, 'scripts/fixtures/voice/commands/f2f4.wav')}`,
] });
function observeVoice() {
  let state;
  Object.defineProperty(window, 'site', { configurable: true, get: () => state, set(value) {
    state = value;
    let asset;
    Object.defineProperty(value, 'asset', { configurable: true, get: () => asset, set(original) {
      asset = { ...original, async loadEsm(name, opts) {
        const result = await original.loadEsm(name, opts);
        if (name === 'voice.move') {
          window.__voice = opts.init.voice;
          window.__round = opts.init.root;
          window.__voiceMove = result;
        }
        return result;
      } };
    } });
  } });
  localStorage.setItem('voice.lang', 'vi');
  localStorage.setItem('voice.pushTalk', 'true');
  localStorage.setItem('voice.on', 'true');
  localStorage.setItem('voice.rtfm', Date.now().toString());
}
const context = await browser.newContext({ baseURL: base, permissions: ['microphone'], viewport: { width: 1400, height: 950 } });
await context.addInitScript(observeVoice);
const page = await context.newPage();
page.on('pageerror', e => report.errors.push(e.message));
page.on('response', async response => {
  if (response.url().endsWith('/voice-asr/transcribe'))
    report.responses.push({ status: response.status(), result: await response.json().catch(() => null) });
});
page.setDefaultTimeout(30000);
await page.route('**/live-fixture.wav', route => route.fulfill({ path: fixturePath, contentType: 'audio/wav' }));

async function feed() {
  await page.evaluate(async () => {
    const mic = window.__voice.mic;
    await mic.start();
    const node = mic.recs.items.get('default').node;
    node.disconnect(); // pause physical input; feed the real worker with this recorded utterance
    const pcm = await mic.audioCtx.decodeAudioData(await (await fetch('/live-fixture.wav')).arrayBuffer());
    const samples = pcm.getChannelData(0);
    for (let i = 0; i < samples.length; i += 2048) {
      const frame = mic.audioCtx.createBuffer(1, Math.min(2048, samples.length - i), pcm.sampleRate);
      frame.copyToChannel(samples.subarray(i, i + 2048), 0);
      node.onaudioprocess({ inputBuffer: frame });
    }
    mic.finish();
  });
}

// These are transcript-to-server checks, not measurements of spoken recognition.
async function say(text, type = 'full') {
  return page.evaluate(({ text, type }) => {
    const mic = window.__voice.mic;
    return mic.recs.items.get('default').listenerMap.get('default')(text, type);
  }, { text, type });
}

// Deterministically exercise the HTTP fallback even when the improved Vosk
// grammar now handles this fixture. Only the primary parser decision is mocked;
// PCM capture, both ASRs, HTTP, fallback parsing and server submission stay real.
async function rejectPrimaryForFallbackCheck() {
  await page.evaluate(() => {
    const listeners = window.__voice.mic.recs.items.get('default').listenerMap;
    const original = listeners.get('default');
    listeners.set('default', (text, type) => type === 'full' ? false : original(text, type));
    window.__restorePrimary = () => listeners.set('default', original);
  });
  report.forcedPrimaryRejections = (report.forcedPrimaryRejections || 0) + 1;
}

try {
  let homepage;
  // Lila's lazy warmup filter delays crawler requests for 20 seconds after its first use.
  for (let attempt = 0; attempt < 45; attempt++) {
    homepage = await page.goto('/');
    if (homepage.status() === 200) break;
    await page.waitForTimeout(1000);
  }
  report.homepageStatus = homepage.status();
  check(homepage.status() === 200, 'Local homepage available');
  assert.match(await readFile(resolve(root, 'infra/lila.conf'), 'utf8'), /^mailer\.primary\.mock = true$/m);
  const suffix = randomBytes(5).toString('hex');
  await page.goto('/signup');
  await page.locator('[name="username"]').fill(`VoiceLive${suffix}`);
  await page.locator('[name="password"]').fill(`${randomBytes(18).toString('hex')}!aA3`);
  await page.locator('[name="email"]').fill(`voice-live-${suffix}@gmail.com`);
  for (const checkbox of await page.locator('#signup-form input[type="checkbox"]').all())
    await page.locator(`label.form-check__label[for="${await checkbox.getAttribute('id')}"]`).click();
  await page.locator('#signup-form button[type="submit"]').click();
  await page.waitForURL(url => !url.pathname.startsWith('/signup'), { timeout: 30000 });
  check((await page.locator('#user_tag').innerText()).toLowerCase() === `voicelive${suffix}`, 'Created a new local test account through the regular signup UI');
  check((await page.request.post('/pref/voice', { form: { voice: '1' } })).ok(), 'Voice preference works');
  const made = await page.request.post('/api/challenge/open', { form: {
    rated: 'false', variant: 'standard', 'clock.limit': '1800', 'clock.increment': '5', name: 'Voice live test',
  } });
  assert.ok(made.ok());
  const game = await made.json();
  report.gameId = game.challenge?.id ?? game.id;
  await page.goto(game.urlWhite);
  await page.locator('form.accept button').click();
  const opponentContext = await browser.newContext({ baseURL: base });
  const opponent = await opponentContext.newPage();
  await opponent.goto(game.urlBlack);
  await opponent.locator('form.accept button').click();
  console.log('Both players joined; waiting for the voice model');
  await page.waitForFunction(() => window.__voiceMove && window.__voice.mic.vosk?.isLoaded('vi'), null, { timeout: 180000 });
  console.log('Voice model ready');
  await page.evaluate(() => {
    window.__heard = [];
    window.__voice.mic.addListener((text, type) => window.__heard.push({ text, type }), { listenerId: 'acceptance' });
  });
  await feed();
  await page.waitForFunction(() => !!window.__voiceMove.question(), null, { timeout: 20000 });
  const proposal = await page.evaluate(() => ({ question: window.__voiceMove.question().prompt,
    ply: window.__round.ply, rate: window.__voice.mic.audioCtx.sampleRate, heard: window.__heard }));
  report.proposal = proposal;
  check(/f2.*f4/.test(proposal.question), 'Recorded noisy command proposes f2f4');
  check(proposal.ply === 0, 'Proposal does not automatically submit a move');
  report.recordedRoute = proposal.heard.some(r => r.type === 'fallback') ? 'fallback' : 'primary';
  await page.screenshot({ path: resolve(out, 'recorded-proposal.png') });
  await say('hủy nước đi');
  await rejectPrimaryForFallbackCheck();
  await feed();
  await page.waitForFunction(() => !!window.__voiceMove.question(), null, { timeout: 20000 });
  check(await page.evaluate(() => /f2.*f4/.test(window.__voiceMove.question()?.prompt) && window.__round.ply === 0),
    'Forced primary rejection routes recorded PCM to a correct unsubmitted fallback proposal');
  check(report.responses.some(r => r.status === 200 && r.result?.text === 'ép hai ép bốn'), 'Real PhoWhisper response used through same-origin HTTP');
  check(await page.evaluate(() => window.__heard.some(r => r.type === 'fallback')), 'Fallback transcript reached the production move parser');
  await page.evaluate(() => window.__restorePrimary());
  await page.screenshot({ path: resolve(out, 'proposal.png') });
  await page.locator('.rcontrols .question a.yes').click();
  await page.waitForFunction(() => window.__round.ply === 1 && window.__round.data.steps.at(-1)?.uci === 'f2f4');
  check(true, 'Explicit confirmation sends f2f4 to the game server');

  // A separate game exercises the natural commands from the user's report.
  const naturalMade = await page.request.post('/api/challenge/open', { form: {
    rated: 'false', variant: 'standard', 'clock.limit': '1800', 'clock.increment': '5', name: 'Vietnamese natural commands',
  } });
  assert.ok(naturalMade.ok());
  const naturalGame = await naturalMade.json();
  report.naturalGameId = naturalGame.challenge?.id ?? naturalGame.id;
  await page.goto(naturalGame.urlWhite);
  await page.locator('form.accept button').click();
  await opponent.goto(naturalGame.urlBlack);
  await opponent.locator('form.accept button').click();
  await page.waitForFunction(() => window.__voiceMove && window.__voice.mic.vosk?.isLoaded('vi'), null, { timeout: 180000 });
  for (const [text, uci] of [
    ['tốt trắng e hai e bốn', 'e2e4'],
    ['quân tốt trắng từ e hai đến e bốn', 'e2e4'],
    ['đưa tốt trắng từ e2 tới e4', 'e2e4'],
    ['cho con tốt trắng đi từ ê hai sang ê bốn', 'e2e4'],
    ['di chuyển tốt màu trắng e 2 e 4', 'e2e4'],
    ['e hai sang e bốn', 'e2e4'],
    ['đi từ e hai đến e bốn', 'e2e4'],
    ['tốt trắng lên e tư', 'e2e4'],
    ['đẩy tốt trắng từ ô e hai lên ô e bốn', 'e2e4'],
    ['tốt ở e hai đi e bốn', 'e2e4'],
    ['quân tốt trắng ở ô e hai đi đến ô e bốn', 'e2e4'],
    ['tốt trắng tiến lên e bốn', 'e2e4'],
    ['di chuyển quân tốt từ e2 sang ô e4', 'e2e4'],
    ['mã nhảy lên ô ép ba', 'g1f3'],
    ['ngựa trắng gờ một đi tới f3', 'g1f3'],
    ['đưa con ngựa trắng lên ép ba', 'g1f3'],
  ]) {
    assert.equal(await say(text), true, text);
    const state = await page.evaluate(() => ({ prompt: window.__voiceMove.question()?.prompt, ply: window.__round.ply }));
    assert.ok(state.prompt?.includes(`${uci.slice(0, 2)} → ${uci.slice(2)}`), text);
    assert.equal(state.ply, 0);
    report.textCommands.push({ text, expected: uci, ...state, passed: true });
    await say('hủy nước đi');
    assert.equal(await page.evaluate(() => window.__voiceMove.question()), false);
  }
  check(report.textCommands.length === 16, 'Sixteen natural transcripts propose the expected move and cancel without submission');
  for (const text of ['mã trắng e hai e bốn', 'tốt đen e hai e bốn', 'tốt trắng e hai e năm',
    'tốt trắng e hai ăn e bốn', 'đừng đi tốt trắng e hai e bốn', 'tốt trắng từ e hai đến e bốn rồi xác nhận']) {
    assert.equal(await say(text), false, text);
    assert.equal(await page.evaluate(() => window.__voiceMove.question()), false);
    report.textCommands.push({ text, expected: null, passed: true });
  }
  check(true, 'Wrong piece, color, capture, illegal destination, negation and concatenated confirmation rejected');
  await say('tốt trắng e hai e bốn', 'fallback');
  await say('đồng ý', 'fallback');
  check(await page.evaluate(() => window.__round.ply === 0 && /e2.*e4/.test(window.__voiceMove.question()?.prompt)),
    'Natural fallback transcript proposes e2e4 but cannot confirm it');
  await page.screenshot({ path: resolve(out, 'natural-proposal.png') });
  await say('xác nhận nước đi');
  await page.waitForFunction(() => window.__round.ply === 1 && window.__round.data.steps.at(-1)?.uci === 'e2e4');
  await opponent.waitForFunction(() => document.querySelector('z7yx.a1t')?.textContent === 'e4');
  check(true, 'Natural e2e4 command reaches the game server and opposing client after explicit confirmation');
  await page.screenshot({ path: resolve(out, 'natural-confirmed.png') });

  // Discard a delayed legal response after a real network disconnect/reconnect.
  // Use a fresh game at the same starting position, preserving the source of truth.
  const made2 = await page.request.post('/api/challenge/open', { form: {
    rated: 'false', variant: 'standard', 'clock.limit': '1800', 'clock.increment': '5', name: 'Voice stale-response test',
  } });
  assert.ok(made2.ok());
  const game2 = await made2.json();
  await page.goto(game2.urlWhite);
  await page.locator('form.accept button').click();
  await opponent.goto(game2.urlBlack);
  await opponent.locator('form.accept button').click();
  await page.waitForFunction(() => window.__voiceMove && window.__voice.mic.vosk?.isLoaded('vi'), null, { timeout: 180000 });
  let release;
  const held = new Promise(resolve => { release = resolve; });
  let received;
  const requested = new Promise(resolve => { received = resolve; });
  await page.route('**/voice-asr/transcribe', async route => {
    const response = await route.fetch();
    received();
    await held;
    await route.fulfill({ response }).catch(() => {});
  });
  await rejectPrimaryForFallbackCheck();
  await feed();
  await Promise.race([requested, new Promise((_, reject) => setTimeout(() => reject(new Error('No fallback request')), 15000))]);
  await context.setOffline(true);
  check(await page.evaluate(() => !navigator.onLine), 'Browser reports the network offline');
  await page.waitForTimeout(2000);
  check(await page.evaluate(() => !window.__voiceMove.question()), 'Voice proposal cleared while offline before the delayed response');
  release();
  await page.waitForTimeout(500);
  await context.setOffline(false);
  await page.waitForTimeout(2500);
  check(await page.evaluate(() => !window.__voiceMove.question() && window.__round.ply === 0), 'Delayed response discarded across disconnect and reconnect at same position');
  await page.unroute('**/voice-asr/transcribe');

  // Exercise getUserMedia -> MediaStream -> ScriptProcessor -> Vosk with a microphone file.
  // Chrome reads a prerecorded voice, not a physical microphone or new speaker.
  await page.keyboard.down('Shift');
  await page.waitForFunction(() => !!window.__voiceMove.question(), null, { timeout: 30000 });
  await page.keyboard.up('Shift');
  await page.waitForTimeout(750);
  check(await page.evaluate(() => /f2.*f4/.test(String(window.__voiceMove.question()?.prompt))), 'Browser MediaStream microphone path recognizes the recorded full command');
  check(await page.evaluate(() => window.__round.ply === 0), 'Releasing Shift retains proposal without sending it');
  await page.screenshot({ path: resolve(out, 'microphone.png') });
  check(report.errors.length === 0, 'No uncaught browser errors');
  report.readyForManualTest = true;
} catch (error) {
  report.failure = String(error.stack || error);
  report.heard = await page.evaluate(() => ({ status: window.__voice?.mic.status, heard: window.__heard,
    question: window.__voiceMove?.question()?.prompt, ply: window.__round?.ply })).catch(() => null);
  await page.screenshot({ path: resolve(out, 'failure.png') }).catch(() => {});
  throw error;
} finally {
  await writeFile(resolve(out, 'report.json'), JSON.stringify(report, null, 2));
  await browser.close();
}
