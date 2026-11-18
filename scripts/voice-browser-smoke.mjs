import assert from 'node:assert/strict';
import { createHash, randomBytes } from 'node:crypto';
import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const pnpm = resolve(root, 'infra/lila-docker/repos/lila/node_modules/.pnpm');
const core = (await readdir(pnpm)).find(name => /^playwright-core@\d/.test(name));
process.env.PLAYWRIGHT_BROWSERS_PATH ??= resolve(root, '.cache/playwright');
const { chromium } = await import(pathToFileURL(resolve(pnpm, core, 'node_modules/playwright-core/index.mjs')));
const base = process.env.BASE_URL || 'http://localhost:8080';
assert.ok(['localhost', '127.0.0.1'].includes(new URL(base).hostname), 'Local acceptance only');
assert.match(await readFile(resolve(root, 'infra/lila.conf'), 'utf8'), /^mailer\.primary\.mock = true$/m);
const artifacts = resolve(root, 'artifacts/voice');
await mkdir(artifacts, { recursive: true });
const report = { base, assertions: [], errors: [], modelRequests: [], failedResponses: [], console: [] };
const commandFixtures = JSON.parse(await readFile(resolve(root, 'scripts/fixtures/voice/commands.json'), 'utf8'));
const legacyWords = JSON.parse(await readFile(resolve(root,
  'infra/lila-docker/repos/lila/ui/voice/grammar/move-vi.json'), 'utf8')).entries
  .filter(entry => !entry.tags.includes('puzzle')).map(entry => entry.in);
for (const item of commandFixtures.cases) {
  const bytes = await readFile(resolve(root, 'scripts/fixtures/voice', item.file));
  assert.equal(createHash('sha256').update(bytes).digest('hex'), item.sha256, `Fixture checksum: ${item.file}`);
}
const check = (value, label) => { assert.ok(value, label); report.assertions.push(label); console.log(label); };
const browser = await chromium.launch({ headless: true, args: [
  '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream', '--autoplay-policy=no-user-gesture-required',
] });
const sessionPath = resolve(artifacts, 'local-test-session.json');
const savedSession = await readFile(sessionPath, 'utf8').then(JSON.parse).catch(() => undefined);
const context = await browser.newContext({ baseURL: base, permissions: ['microphone'], storageState: savedSession, viewport: { width: 1365, height: 900 } });

// Observe the real controller at its module-loading boundary, without changing production exports.
const observeVoice = () => {
  let state;
  Object.defineProperty(window, 'site', {
    configurable: true, get: () => state,
    set(value) {
      state = value;
      let asset;
      Object.defineProperty(value, 'asset', {
        configurable: true, get: () => asset,
        set(original) {
          asset = { ...original, async loadEsm(name, opts) {
            const result = await original.loadEsm(name, opts);
            if (name === 'voice.move') {
              window.__voice = opts.init.voice;
              window.__round = opts.init.root;
              window.__voiceMove = result;
            }
            return result;
          } };
        },
      });
    },
  });
};
await context.addInitScript(observeVoice);
const page = await context.newPage();
page.setDefaultTimeout(20000);
page.on('pageerror', error => report.errors.push(error.message));
page.on('console', message => {
  if (['error', 'warning'].includes(message.type())) report.console.push(message.text());
});
page.on('request', request => {
  if (request.url().includes('/vosk/model-')) report.modelRequests.push(request.url());
});
page.on('response', response => {
  if (response.status() >= 400) report.failedResponses.push({ url: response.url(), status: response.status() });
});

try {
  let response;
  for (let attempt = 0; attempt < 45; attempt++) {
    response = await page.goto('/');
    if (response.status() === 200) break;
    await page.waitForTimeout(1000);
  }
  check(response.status() === 200, 'Local homepage is available');
  if (await page.locator('#user_tag').count()) {
    check((await page.locator('#user_tag').innerText()).toLowerCase().startsWith('voice'), 'Reused the isolated local test account');
  } else {
  const suffix = randomBytes(5).toString('hex');
  await page.goto('/signup');
  await page.locator('[name="username"]').fill(`Voice${suffix}`);
  await page.locator('[name="password"]').fill(`${randomBytes(18).toString('hex')}!aA3`);
  await page.locator('[name="email"]').fill(`voice-${suffix}@gmail.com`);
  for (const checkbox of await page.locator('#signup-form input[type="checkbox"]').all())
    await page.locator(`label.form-check__label[for="${await checkbox.getAttribute('id')}"]`).click();
  await page.locator('#signup-form button[type="submit"]').click();
  await page.waitForURL(url => !url.pathname.startsWith('/signup'), { timeout: 30000 });
  check((await page.locator('#user_tag').innerText()).toLowerCase() === `voice${suffix}`, 'Registered local player');
  await context.storageState({ path: sessionPath });
  }
  check((await page.request.post('/pref/voice', { form: { voice: '1' } })).ok(), 'Voice preference enabled');
  await page.evaluate(() => { localStorage.setItem('voice.rtfm', Date.now().toString()); });
  const created = await page.request.post('/api/challenge/open', {
    form: { rated: 'false', variant: 'standard', 'clock.limit': '1800', 'clock.increment': '5', name: 'Vietnamese voice acceptance' },
  });
  assert.ok(created.ok());
  const challenge = await created.json();
  report.gameId = challenge.challenge?.id ?? challenge.id;
  await page.goto(challenge.urlWhite);
  await page.locator('form.accept button').click();
  const blackContext = await browser.newContext({ baseURL: base });
  const black = await blackContext.newPage();
  await black.goto(challenge.urlBlack);
  await black.locator('form.accept button').click();
  await page.locator('#voice-settings-button').click();
  check(await page.evaluate(() => !site.debug), 'Production UI has global debug disabled');
  check(await page.locator('#voice-lang option[value="vi"]').count() === 1, 'Vietnamese is selectable without global debug');
  await page.locator('#voice-lang').selectOption('vi');
  await page.waitForFunction(() => window.__voice?.lang() === 'vi');
  const started = Date.now();
  await page.locator('#microphone-button').click();
  await page.waitForFunction(() => window.__voice?.mic.isListening, null, { timeout: 180000 });
  report.coldLoadMs = Date.now() - started;
  check(await page.evaluate(() => window.__voice.mic.vosk.isLoaded('vi')), 'Vietnamese model loaded by the production WASM recognizer');
  check(report.modelRequests.length === 1, 'Model downloaded once on demand');
  await writeFile(resolve(artifacts, 'command-grammar.json'), JSON.stringify(await page.evaluate(
    () => window.__voice.mic.recs.items.get('default').words), null, 2));

  await page.route('**/voice-test/bon.wav', route => route.fulfill({
    path: resolve(root, 'scripts/fixtures/voice/bon.wav'), contentType: 'audio/wav',
  }));
  report.recordedAudio = await page.evaluate(async () => {
    const mic = window.__voice.mic;
    mic.stop();
    const buffer = await mic.audioCtx.decodeAudioData(await (await fetch('/voice-test/bon.wav')).arrayBuffer());
    const heard = [];
    let complete;
    const done = new Promise(resolve => { complete = resolve; });
    const node = mic.vosk.initRecognizer({
      recId: 'recording-smoke', audioCtx: mic.audioCtx, partial: false,
      words: mic.recs.items.get('default').words,
      broadcast: text => { heard.push(text); complete(); },
    });
    mic.vosk.select('recording-smoke');
    const rate = mic.audioCtx.sampleRate;
    const samples = new Float32Array(Math.ceil(rate * 2.5) + buffer.length);
    samples.set(buffer.getChannelData(0), Math.floor(rate * 0.5));
    for (let offset = 0; offset < samples.length; offset += 2048) {
      const frame = mic.audioCtx.createBuffer(1, 2048, rate);
      frame.copyToChannel(samples.subarray(offset, offset + 2048), 0);
      node.onaudioprocess({ inputBuffer: frame });
    }
    mic.vosk.select(false);
    await Promise.race([done, new Promise((_, reject) => setTimeout(() => reject(new Error('ASR recording timeout')), 15000))]);
    await mic.start();
    return { heard, sampleRate: rate, source: 'Human CC0 recording: bon.wav' };
  });
  console.log('Recorded audio result:', report.recordedAudio);

  // Complete commands use recorded PCM through production Vosk and the move parser.
  // Each command joins human word clips; these are not natural connected-speech recordings.
  await page.route('**/voice-test/commands/*.wav', route => route.fulfill({
    path: resolve(root, 'scripts/fixtures/voice/commands', new URL(route.request().url()).pathname.split('/').at(-1)),
    contentType: 'audio/wav',
  }));
  const playCommand = (file, sampleRate, words) => page.evaluate(async ({ file, sampleRate, words }) => {
    const mic = window.__voice.mic;
    mic.stop();
    const audioCtx = sampleRate && sampleRate !== mic.audioCtx.sampleRate
      ? new AudioContext({ sampleRate }) : mic.audioCtx;
    const buffer = await audioCtx.decodeAudioData(await (await fetch(`/voice-test/${file}`)).arrayBuffer());
    const heard = [];
    let finish;
    const done = new Promise(resolve => { finish = resolve; });
    const node = mic.vosk.initRecognizer({
      recId: 'command-smoke', audioCtx, partial: false,
      words: words || mic.recs.items.get('default').words,
      broadcast: (text, type, duration) => {
        heard.push(text);
        mic.broadcast(text, type, duration);
        finish();
      },
    });
    mic.vosk.select('command-smoke');
    const rate = audioCtx.sampleRate;
    for (let offset = 0; offset < buffer.length; offset += 2048) {
      const frame = audioCtx.createBuffer(1, 2048, rate);
      frame.copyToChannel(buffer.getChannelData(0).subarray(offset, offset + 2048), 0);
      node.onaudioprocess({ inputBuffer: frame });
    }
    mic.vosk.select(false);
    await Promise.race([done, new Promise((_, reject) => setTimeout(() => reject(new Error('Command ASR timeout')), 15000))]);
    const question = window.__voiceMove.question();
    if (audioCtx !== mic.audioCtx) await audioCtx.close();
    return { heard, prompt: question && question.prompt, sampleRate: rate };
  }, { file, sampleRate, words });
  const say = text => page.evaluate(text => window.__voice.mic.broadcast(text, 'full', 3000), text);
  report.commandAudio = { kind: commandFixtures.kind, results: [], baselineResults: [] };
  for (const sampleRate of [48000, 16000]) for (const item of commandFixtures.cases) {
    const result = await playCommand(item.file, sampleRate, legacyWords);
    report.commandAudio.baselineResults.push({ ...item, ...result,
      passed: item.uci ? result.heard.join(' ') === item.text
        && !!result.prompt?.includes(`${item.uci.slice(0, 2)} → ${item.uci.slice(2, 4)}`) : !result.prompt });
    await say('huỷ bỏ');
  }
  for (const sampleRate of [48000, 16000]) for (const item of commandFixtures.cases) {
    const result = await playCommand(item.file, sampleRate);
    report.commandAudio.results.push({ ...item, ...result });
    console.log('Command audio result:', item.file, result);
    if (item.uci) {
      const recorded = report.commandAudio.results.at(-1);
      recorded.passed = result.heard.join(' ') === item.text
        && !!result.prompt?.includes(`${item.uci.slice(0, 2)} → ${item.uci.slice(2, 4)}`);
      check(await page.evaluate(() => window.__round.data.game.turns === 0), 'PCM command cannot auto-submit');
      await say('huỷ bỏ');
    } else {
      report.commandAudio.results.at(-1).passed = !result.prompt;
      await say('huỷ bỏ');
    }
  }
  report.commandAudio.passed = report.commandAudio.results.filter(item => item.passed).length;
  report.commandAudio.total = report.commandAudio.results.length;
  report.commandAudio.baselinePassed = report.commandAudio.baselineResults.filter(item => item.passed).length;
  report.commandAudio.status = report.commandAudio.passed === report.commandAudio.total ? 'passed' : 'failed';
  await page.evaluate(() => window.__voice.mic.start());

  // Additional state tests inject transcripts; they are not acoustic accuracy tests.
  await say('e hai e bốn');
  await page.locator('.rcontrols .question').waitFor();
  check(await page.evaluate(() => window.__round.data.game.turns === 0), 'Recognized move waits for confirmation');
  await page.screenshot({ path: resolve(artifacts, 'confirm-e2-e4.png') });
  await say('huỷ bỏ');
  check(await page.locator('.rcontrols .question').count() === 0, 'Cancel removes the proposed move');
  await playCommand('commands/f2f4.wav', 16000);
  await page.screenshot({ path: resolve(artifacts, 'confirm-f2-f4-16khz.png') });
  await say('xác nhận');
  await page.waitForFunction(() => window.__round.data.game.turns === 1);
  check(await page.evaluate(() => window.__round.data.steps.at(-1).uci === 'f2f4'), '16kHz PCM command confirmed by transcript reaches the server as f2f4');
  await page.evaluate(() => window.__voice.mic.start());
  await say('d hai d bốn');
  await say('xác nhận');
  check(await page.evaluate(() => window.__round.data.game.turns === 1), 'Out-of-turn command sends no move');
  const board = await black.locator('cg-board').boundingBox();
  const blackSquare = square => [board.x + (7 - square.charCodeAt(0) + 97 + 0.5) * board.width / 8,
    board.y + (Number(square[1]) - 1 + 0.5) * board.height / 8];
  await black.mouse.click(...blackSquare('e7'));
  await black.mouse.click(...blackSquare('e5'));
  await page.waitForFunction(() => window.__round.data.game.turns === 2);
  await say('mã ép ba');
  await page.locator('.rcontrols .question').waitFor();
  await context.setOffline(true);
  await page.waitForFunction(() => !window.__voice.mic.isListening, null, { timeout: 45000 });
  check(await page.locator('.rcontrols .question').count() === 0, 'Disconnect cancels the proposed move and stops the microphone');
  await context.setOffline(false);
  await page.waitForFunction(() => !document.body.classList.contains('offline'));
  await say('xác nhận');
  check(await page.evaluate(() => window.__round.data.game.turns === 2), 'Reconnect does not submit the stale command');
  await page.evaluate(() => { window.__voice.enabled(false); window.__voice.mic.stop(); });
  await page.reload();
  await page.waitForFunction(() => window.__voice?.lang() === 'vi');
  const warm = Date.now();
  await page.locator('#microphone-button').click();
  await page.waitForFunction(() => window.__voice?.mic.isListening, null, { timeout: 120000 });
  report.warmLoadMs = Date.now() - warm;
  check(report.modelRequests.length === 1, 'Reload reuses the model extracted in IndexedDB');
  await page.screenshot({ path: resolve(artifacts, 'voice-ready.png') });

  report.errorRecovery = [];
  for (const fault of ['missing-model', 'corrupt-model', 'denied-microphone']) {
    const faultContext = await browser.newContext({ baseURL: base, permissions: ['microphone'], storageState: await context.storageState() });
    await faultContext.addInitScript(observeVoice);
    await faultContext.addInitScript(fault => {
      localStorage.setItem('voice.on', 'false');
      if (fault === 'denied-microphone') navigator.mediaDevices.getUserMedia = async () => {
        throw new DOMException('Permission denied by test', 'NotAllowedError');
      };
    }, fault);
    const faultPage = await faultContext.newPage();
    const uncaught = [];
    faultPage.on('pageerror', error => { uncaught.push(error.message); console.error(fault, error.message); });
    if (fault !== 'denied-microphone') await faultPage.route('**/vosk/model-vi-0.4.tar.gz', route => route.fulfill({
      status: fault === 'missing-model' ? 404 : 200, contentType: 'application/gzip', body: 'invalid archive',
    }));
    await faultPage.goto(page.url());
    await faultPage.locator('#microphone-button').click();
    await faultPage.waitForFunction(() => window.__voice && !window.__voice.mic.isBusy && !window.__voice.mic.isListening && window.__voice.mic.status.length > 0,
      null, { timeout: 45000 });
    const status = await faultPage.locator('#voice-status').innerText();
    report.errorRecovery.push({ fault, status, uncaught });
    check(uncaught.length === 0, `${fault}: failure is displayed without an uncaught rejection`);
    if (fault !== 'denied-microphone') {
      await faultPage.unroute('**/vosk/model-vi-0.4.tar.gz');
      await faultPage.locator('#microphone-button').click();
      await faultPage.waitForFunction(() => !window.__voice.mic.isBusy, null, { timeout: 60000 });
      check(await faultPage.evaluate(() => window.__voice.mic.isListening), `${fault}: retry loads the valid model`);
    }
    await faultContext.close();
  }

  await say('mã ép ba');
  await page.locator('.rcontrols .question').waitFor();
  await black.locator('button.resign').click();
  const resignConfirmation = black.locator('.act-confirm button.yes');
  if (await resignConfirmation.isVisible()) await resignConfirmation.click();
  await page.waitForFunction(() => window.__round.data.game.status.id >= 25);
  check(await page.evaluate(() => !window.__voiceMove.question() && !window.__voice.mic.isListening), 'Official game completion clears voice confirmation and stops input');
  await say('xác nhận');
  check(await page.evaluate(() => window.__round.data.game.turns === 2), 'No voice move is sent after game completion');
  check(report.errors.length === 0, 'No uncaught browser errors');
  report.functionalStatus = 'passed';
  report.wordAudioStatus = report.recordedAudio.heard.includes('bốn') ? 'passed' : 'failed';
  report.acousticStatus = report.wordAudioStatus === 'passed'
    && report.commandAudio.status === 'passed' ? 'passed' : 'failed';
  check(report.commandAudio.status === 'passed', 'All full-command acoustic cases pass');
  check(report.recordedAudio.heard.includes('bốn'), 'Real Vosk decodes the human recording as bốn');
  report.status = 'passed';
} catch (error) {
  report.status = 'failed';
  report.failure = error.stack;
  await page.screenshot({ path: resolve(artifacts, 'failure.png') }).catch(() => {});
  console.error(error);
  process.exitCode = 1;
} finally {
  await writeFile(resolve(artifacts, 'browser-report.json'), JSON.stringify(report, null, 2));
  await browser.close();
}
