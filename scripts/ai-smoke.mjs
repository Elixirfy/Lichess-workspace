// Real local AI games through the normal setup endpoint and browser board.
// Anonymous cookies stay in memory. No moves are made on the user's game.
import assert from 'node:assert/strict';
import { randomBytes } from 'node:crypto';
import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const base = 'http://localhost:8080';
const out = resolve(root, 'artifacts/ai-smoke', new Date().toISOString().replaceAll(':', '-'));
await mkdir(out, { recursive: true });
const pnpm = resolve(root, 'infra/lila-docker/repos/lila/node_modules/.pnpm');
const core = (await readdir(pnpm)).find(n => /^playwright-core@\d/.test(n));
process.env.PLAYWRIGHT_BROWSERS_PATH ??= resolve(root, '.cache/playwright');
const { chromium } = await import(pathToFileURL(resolve(pnpm, core, 'node_modules/playwright-core/index.mjs')));
const report = { started: new Date().toISOString(), cases: [], errors: [] };
const browser = await chromium.launch({ headless: true });
const argument = name => process.argv[process.argv.indexOf(name) + 1];
const timeoutMs = process.argv.includes('--timeout-ms') ? Number(argument('--timeout-ms')) : 25000;
const withProbability = process.argv.includes('--probability');
const signedIn = process.argv.includes('--signed-in');
report.probability = withProbability;
report.signedIn = signedIn;

async function register(page) {
  const config = await readFile(resolve(root, 'infra/lila.conf'), 'utf8');
  assert.match(config, /^mailer\.primary\.mock = true$/m);
  const suffix = randomBytes(5).toString('hex'), username = `AiWdl${suffix}`;
  await page.goto(base + '/signup');
  await page.locator('[name="username"]').fill(username);
  await page.locator('[name="password"]').fill(`${randomBytes(18).toString('hex')}!aA3`);
  await page.locator('[name="email"]').fill(`ai-wdl-${suffix}@gmail.com`);
  for (const checkbox of await page.locator('#signup-form input[type="checkbox"]').all()) {
    const id = await checkbox.getAttribute('id');
    await page.locator(`label.form-check__label[for="${id}"]`).click();
    assert.ok(await checkbox.isChecked());
  }
  await page.locator('#signup-form button[type="submit"]').click();
  await page.waitForURL(url => !url.pathname.startsWith('/signup'));
  assert.equal((await page.locator('#user_tag').innerText()).toLowerCase(), username.toLowerCase());
}

async function probability(page, context, result, ply, phase) {
  const sample = { phase, expectedPly: ply };
  (result.probabilities ??= []).push(sample);
  const started = Date.now();
  let prediction;
  do {
    const response = await context.request.get(`/game/${result.id}/win-probability`);
    sample.http = response.status();
    assert.equal(response.status(), 200, 'The AI player must be allowed by the server');
    prediction = await response.json();
    if (prediction.status === 'ready' && prediction.ply === ply) break;
    await page.waitForTimeout(100);
  } while (Date.now() - started < timeoutMs);
  assert.equal(prediction.status, 'ready');
  assert.equal(prediction.ply, ply);
  const p = prediction.probabilities;
  assert.ok(p.white + p.black > 0);
  await page.waitForFunction(({ p }) => {
    const panel = document.querySelector('.win-probability');
    const values = [...(panel?.querySelector('.win-probability__values')?.textContent ?? '').matchAll(/(\d+\.\d)%/g)]
      .map(m => Number(m[1]));
    return panel?.getAttribute('data-source') === 'engine' && values.length === 2 &&
      Math.abs(values[0] + values[1] - 100) < 0.00001 &&
      [p.white, p.black].every((x, i) => Math.abs(values[i] - 100 * x / (p.white + p.black)) <= 0.050001);
  }, { p });
  const panel = page.locator('.win-probability');
  assert.equal(await panel.locator('.win-probability__bar > span').count(), 2);
  assert.equal(await panel.locator('.win-probability__draw').count(), 0);
  assert.match(await panel.locator('.win-probability__source').innerText(), /không tính hòa/);
  Object.assign(sample, { revision: prediction.revision, rawWdl: p,
    displayed: await panel.locator('.win-probability__values').innerText(), source: 'engine', passed: true });
}

function moves(pgn) {
  return pgn.replace(/^\[.*\]\s*$/gm, '').replace(/\{[^}]*\}/g, '')
    .replace(/\d+\.(?:\.\.)?/g, '').split(/\s+/).filter(s => s && !['*', '1-0', '0-1', '1/2-1/2'].includes(s));
}

async function awaitPly(context, id, ply) {
  const started = Date.now();
  let pgn = '', played = [];
  do {
    const response = await context.request.get(`/game/export/${id}`, { headers: { Accept: 'application/x-chess-pgn' } });
    assert.ok(response.ok(), `PGN export returned ${response.status()}`);
    pgn = await response.text(); played = moves(pgn);
    if (played.length >= ply) return { elapsedMs: Date.now() - started, moves: played, pgn };
    await new Promise(resolve => setTimeout(resolve, 250));
  } while (Date.now() - started < timeoutMs);
  throw new Error(`AI did not reach ply ${ply} in ${timeoutMs}ms; actual moves: ${played.join(' ')}`);
}

async function moveByMouse(page, uci, color) {
  const board = await page.locator('cg-board').first().boundingBox();
  assert.ok(board);
  for (const square of [uci.slice(0, 2), uci.slice(2, 4)]) {
    const file = square.charCodeAt(0) - 97, rank = Number(square[1]) - 1;
    const x = color === 'white' ? file : 7 - file, y = color === 'white' ? 7 - rank : rank;
    await page.mouse.click(board.x + (x + 0.5) * board.width / 8, board.y + (y + 0.5) * board.height / 8);
  }
}

try {
  const warmup = await browser.newContext({ baseURL: base });
  const warmupDeadline = Date.now() + 60000;
  let homepage;
  do {
    homepage = await warmup.request.get('/');
    if (![502, 503].includes(homepage.status())) break;
    await new Promise(resolve => setTimeout(resolve, 1000));
  } while (Date.now() < warmupDeadline);
  assert.equal(homepage.status(), 200, 'Local Lichess must finish startup before acceptance');
  await warmup.close();
  if (process.argv.includes('--observe')) {
    const id = argument('--observe');
    assert.match(id, /^[a-zA-Z0-9]{8}$/);
    const context = await browser.newContext({ baseURL: base });
    const result = { id, kind: 'Read-only observation of existing game' };
    report.cases.push(result);
    Object.assign(result, await awaitPly(context, id, 2), { passed: true });
    console.log('PASS existing game AI reply', id, result.moves.join(' '));
  } else {
    for (const color of ['white', 'black']) {
      const context = await browser.newContext({ baseURL: base, viewport: { width: 1280, height: 900 } });
      const page = await context.newPage();
      page.on('pageerror', e => report.errors.push(e.message));
      const result = { color, aiLevel: 1, checks: [], socketMoves: [] };
      report.cases.push(result);
      if (signedIn) await register(page);
      page.on('websocket', ws => ws.on('framereceived', frame => {
        try {
          const receive = message => {
            if (message.t === 'b' && Array.isArray(message.d)) message.d.forEach(receive);
            if (message.t === 'move') result.socketMoves.push({ uci: message.d.uci, ply: message.d.ply });
          };
          receive(JSON.parse(String(frame.payload)));
        } catch { /* heartbeat */ }
      }));
      const created = await context.request.post('/setup/ai', {
        headers: { Origin: base, Accept: 'text/html' }, maxRedirects: 0,
        form: { variant: '1', timeMode: '0', time: '5', increment: '8', days: '2', level: '1', color },
      });
      assert.equal(created.status(), 303, await created.text());
      const location = created.headers().location;
      const id = /\/game\/([a-zA-Z0-9]{8})/.exec(location)?.[1];
      assert.ok(id, 'AI setup must return a game'); result.id = id;
      await page.goto(location);
      await page.waitForFunction(() => document.body.classList.contains('online') && document.querySelector('cg-board'));
      if (color === 'white') {
        if (withProbability) await probability(page, context, result, 0, 'initial');
        await moveByMouse(page, 'd2d4', color);
        result.checks.push(await awaitPly(context, id, 2));
        if (withProbability) await probability(page, context, result, 2, 'first-bot-reply');
        await moveByMouse(page, 'g1f3', color);
        result.checks.push(await awaitPly(context, id, 4));
        if (withProbability) await probability(page, context, result, 4, 'second-bot-reply');
      } else {
        result.checks.push(await awaitPly(context, id, 1));
        if (withProbability) await probability(page, context, result, 1, 'initial-bot-move');
        await moveByMouse(page, 'e7e5', color);
        result.checks.push(await awaitPly(context, id, 3));
        if (withProbability) await probability(page, context, result, 3, 'bot-reply');
      }
      const final = result.checks.at(-1);
      assert.match(final.pgn, new RegExp(`\\[${color === 'white' ? 'Black' : 'White'} "lichess AI level 1"\\]`));
      assert.ok(result.socketMoves.some(m => m.ply === final.moves.length), 'Browser must receive the AI move');
      await page.screenshot({ path: resolve(out, `${color}.png`) });
      if (withProbability) {
        await page.reload();
        await probability(page, context, result, final.moves.length, 'reload');
        await context.setOffline(true);
        await page.waitForFunction(() => document.querySelector('.win-probability')?.dataset.state === 'stale');
        assert.equal(await page.locator('.win-probability__values').count(), 0);
        await context.setOffline(false);
        await page.waitForFunction(() => document.body.classList.contains('online'));
        await probability(page, context, result, final.moves.length, 'reconnect');
        await page.setViewportSize({ width: 390, height: 844 });
        await page.locator('.win-probability').scrollIntoViewIfNeeded();
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
        await page.screenshot({ path: resolve(out, `${color}-mobile.png`), fullPage: true });
        await page.setViewportSize({ width: 1280, height: 900 });
        await page.locator('button.resign').click();
        const confirm = page.locator('.act-confirm button.yes');
        if (await confirm.isVisible()) await confirm.click();
        await page.waitForFunction(() => document.querySelector('.win-probability')?.dataset.source === 'official');
        assert.match(await page.locator('.win-probability__values').innerText(),
          color === 'white' ? /Trắng 0.0%.*Đen 100.0%/s : /Trắng 100.0%.*Đen 0.0%/s);
        result.officialResultPassed = true;
      }
      result.passed = true;
      console.log('PASS', color, id, final.moves.join(' '));
      await context.close();
    }
  }
  if (withProbability && !process.argv.includes('--observe')) {
    const context = await browser.newContext({ baseURL: base });
    const page = await context.newPage();
    page.on('pageerror', e => report.errors.push(e.message));
    const created = await context.request.post('/setup/ai', {
      headers: { Origin: base, Accept: 'text/html' }, maxRedirects: 0,
      form: { variant: '2', timeMode: '0', time: '5', increment: '8', days: '2', level: '1', color: 'white' },
    });
    assert.equal(created.status(), 303, 'Create a separate Chess960 game for the variant gate');
    const location = created.headers().location;
    const id = /\/game\/([a-zA-Z0-9]{8})/.exec(location)?.[1];
    assert.ok(id);
    assert.equal((await context.request.get(`/game/${id}/win-probability`)).status(), 404);
    assert.equal((await context.request.get(`/game/${id}/win-probability?variant=standard&winProbability=true`)).status(), 404);
    await page.goto(location);
    await page.waitForFunction(() => document.body.classList.contains('online') && document.querySelector('.round__app cg-board'));
    assert.equal(await page.locator('.win-probability').count(), 0);
    report.variantRestriction = { gameId: id, variant: 'chess960', endpointStatus: 404,
      clientFlagsCannotBypass: true, panelAbsent: true };
    await context.close();
  }
  assert.deepEqual(report.errors, []);
} catch (error) {
  report.failure = String(error.stack || error); process.exitCode = 1;
  console.log(report.failure);
} finally {
  report.finished = new Date().toISOString();
  await writeFile(resolve(out, 'report.json'), JSON.stringify(report, null, 2));
  await browser.close();
  console.log('Report:', out);
}
