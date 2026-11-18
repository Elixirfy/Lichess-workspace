// Real local AI games through the normal setup endpoint and browser board.
// Anonymous cookies stay in memory. No moves are made on the user's game.
import assert from 'node:assert/strict';
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
        await moveByMouse(page, 'd2d4', color);
        result.checks.push(await awaitPly(context, id, 2));
        await moveByMouse(page, 'g1f3', color);
        result.checks.push(await awaitPly(context, id, 4));
      } else {
        result.checks.push(await awaitPly(context, id, 1));
        await moveByMouse(page, 'e7e5', color);
        result.checks.push(await awaitPly(context, id, 3));
      }
      const final = result.checks.at(-1);
      assert.match(final.pgn, new RegExp(`\\[${color === 'white' ? 'Black' : 'White'} "lichess AI level 1"\\]`));
      assert.ok(result.socketMoves.some(m => m.ply === final.moves.length), 'Browser must receive the AI move');
      await page.screenshot({ path: resolve(out, `${color}.png`) });
      result.passed = true;
      console.log('PASS', color, id, final.moves.join(' '));
      await context.close();
    }
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
