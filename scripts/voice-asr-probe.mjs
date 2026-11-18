// Legacy word-list diagnostic through the shipped WASM decoder. Full commands
// with the current position's production grammar are tested by voice-browser-smoke.mjs.
import assert from 'node:assert/strict';
import { readFile, readdir, mkdir, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const pnpm = resolve(root, 'infra/lila-docker/repos/lila/node_modules/.pnpm');
const core = (await readdir(pnpm)).find(name => /^playwright-core@\d/.test(name));
process.env.PLAYWRIGHT_BROWSERS_PATH ??= resolve(root, '.cache/playwright');
const { chromium } = await import(pathToFileURL(resolve(pnpm, core, 'node_modules/playwright-core/index.mjs')));
const base = process.env.BASE_URL || 'http://localhost:8080';
assert.ok(['localhost', '127.0.0.1'].includes(new URL(base).hostname));
const browser = await chromium.launch({ args: ['--autoplay-policy=no-user-gesture-required'] });
const page = await browser.newPage();
const warnings = [];
page.on('console', msg => { if (msg.type() === 'warning' || msg.type() === 'error') warnings.push(msg.text()); });
await page.route('**/voice-test/*.wav', route => route.fulfill({
  path: resolve(root, 'scripts/fixtures/voice', new URL(route.request().url()).pathname.split('/').at(-1)), contentType: 'audio/wav',
}));
try {
  let response;
  for (let attempt = 0; attempt < 45; attempt++) {
    response = await page.goto(base);
    if (response.status() === 200) break;
    await page.waitForTimeout(1000);
  }
  assert.equal(response.status(), 200, 'Local homepage is available');
  await page.waitForFunction(() => window.site?.asset?.loadEsm);
  const grammar = JSON.parse(await readFile(resolve(root, 'infra/lila-docker/repos/lila/ui/voice/grammar/move-vi.json'), 'utf8'));
  const results = await page.evaluate(async grammar => {
    const vosk = await site.asset.loadEsm('voice.vosk');
    await vosk.initModel(site.asset.url('lifat/vosk/model-vi-0.4.tar.gz'), 'vi');
    const results = [];
    for (const rate of [48000, 16000]) {
      const ctx = new AudioContext({ sampleRate: rate });
      for (const file of ['bon', 'ep']) {
        const original = await ctx.decodeAudioData(await (await fetch(`/voice-test/${file}.wav`)).arrayBuffer());
        for (const omitFillers of [false, true]) {
          const words = grammar.entries.filter(e => !e.tags.includes('puzzle') && (!omitFillers || !e.tags.includes('ignore'))).map(e => e.in);
          const heard = [];
          let finish;
          const done = new Promise(resolve => { finish = resolve; });
          const node = vosk.initRecognizer({ audioCtx: ctx, recId: 'probe', partial: false, words,
            broadcast: text => { heard.push(text); finish(); },
          });
          vosk.select('probe');
          const samples = new Float32Array(Math.ceil(rate * 2.5) + original.length);
          samples.set(original.getChannelData(0), Math.floor(rate * 0.5));
          for (let offset = 0; offset < samples.length; offset += 2048) {
            const frame = ctx.createBuffer(1, 2048, rate);
            frame.copyToChannel(samples.subarray(offset, offset + 2048), 0);
            node.onaudioprocess({ inputBuffer: frame });
          }
          vosk.select(false);
          await Promise.race([done, new Promise(resolve => setTimeout(resolve, 2500))]);
          results.push({ file, rate, omitFillers, heard });
        }
      }
      await ctx.close();
    }
    return results;
  }, grammar);
  await mkdir(resolve(root, 'artifacts/voice'), { recursive: true });
  await writeFile(resolve(root, 'artifacts/voice/asr-probe.json'), JSON.stringify({
    grammarKind: 'legacy word-list diagnostic, not the production position grammar', results, warnings,
  }, null, 2));
  console.log(JSON.stringify(results, null, 2));
} finally { await browser.close(); }
