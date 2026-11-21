// Read-only review of local regression games with the real browser Stockfish engine.
import assert from 'node:assert/strict';
import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { expectedWhiteWinPercent } from './win-percent-reference.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const lila = resolve(root, 'infra/lila-docker/repos/lila');
const pnpm = resolve(lila, 'node_modules/.pnpm');
const core = (await readdir(pnpm)).find(n => /^playwright-core@\d/.test(n));
process.env.PLAYWRIGHT_BROWSERS_PATH ??= resolve(root, '.cache/playwright');
const { chromium } = await import(pathToFileURL(resolve(pnpm, core, 'node_modules/playwright-core/index.mjs')));
const { Chess } = await import(pathToFileURL(resolve(lila, 'node_modules/chessops/dist/esm/chess.js')));
const { makeFen } = await import(pathToFileURL(resolve(lila, 'node_modules/chessops/dist/esm/fen.js')));
const { parseSan } = await import(pathToFileURL(resolve(lila, 'node_modules/chessops/dist/esm/san.js')));
const { parseUci } = await import(pathToFileURL(resolve(lila, 'node_modules/chessops/dist/esm/util.js')));
const base = process.env.BASE_URL ?? 'http://localhost:8080';
const out = resolve(root, 'artifacts/replay-advantage', new Date().toISOString().replaceAll(':', '-'));
await mkdir(out, { recursive: true });
const arg = name => process.argv[process.argv.indexOf(name) + 1];
assert.ok(process.argv.includes('--ai-report'), 'Pass the fresh ai-smoke report.json');
const ai = JSON.parse(await readFile(resolve(arg('--ai-report')), 'utf8'));
assert.ok(!ai.failure && ai.cases.length === 2 && ai.cases.every(c => c.passed && c.officialResultPassed));
const pvpReport = process.argv.includes('--pvp-report') ? arg('--pvp-report') : 'artifacts/human-browser-smoke.json';
const pvp = JSON.parse(await readFile(resolve(root, pvpReport), 'utf8'));
const fixtures = [
  ...ai.cases.map(c => ({ id: c.id, kind: `bot-${c.color}-resignation`, variation: true })),
  { id: pvp.endingGames.checkmate, kind: 'checkmate' },
  { id: pvp.endingGames.draw, kind: 'agreed-draw' },
];
const browser = await chromium.launch({ headless: true });
// Lila intentionally serves static crawler HTML to HeadlessChrome.
const userAgent = `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${browser.version()} Safari/537.36`;
const report = { started: new Date().toISOString(), metric: 'lichess-win-percent', realBrowserEngine: 'Stockfish 19 smallnet', cases: [], errors: [], noServerMoves: true };

function positionList(pgn) {
  assert.ok(!pgn.includes('[SetUp '), 'These fixtures start at the normal chess position');
  const san = pgn.replace(/^\[.*\]\s*$/gm, '').replace(/\{[^}]*\}/g, '')
    .replace(/\d+\.(?:\.\.)?/g, '').split(/\s+/).filter(s => s && !['*', '1-0', '0-1', '1/2-1/2'].includes(s));
  const position = Chess.default();
  const placements = [makeFen(position.toSetup()).split(' ')[0]];
  for (const moveSan of san) {
    const move = parseSan(position, moveSan);
    assert.ok(move, `Invalid fixture SAN ${moveSan}`);
    position.play(move);
    placements.push(makeFen(position.toSetup()).split(' ')[0]);
  }
  return { placements, san, result: /\[Result "([^"]+)"\]/.exec(pgn)?.[1] };
}

async function engine(page, enabled) {
  if (await page.evaluate(() => !!window.site.analysis.cevalEnabled()) !== enabled) {
    await page.keyboard.press('l');
    await page.waitForFunction(expected => !!window.site.analysis.cevalEnabled() === expected, enabled);
  }
}

async function sample(page, result, phase, source) {
  await page.waitForFunction(expected => document.querySelector('.eval-gauge')?.getAttribute('data-source') === expected, source);
  const data = await page.locator('.eval-gauge').evaluate(el => ({
    source: el.dataset.source, metric: el.dataset.metric, tooltip: el.title,
    whiteText: el.querySelector('.eval-gauge__white .eval-gauge__value').textContent,
    blackText: el.querySelector('.eval-gauge__black .eval-gauge__value').textContent,
    style: el.getAttribute('style'), reverse: el.classList.contains('reverse'),
    fen: window.lichess.chessground().getFen(),
    nodeFen: window.site.analysis.getNode().fen,
    ply: window.site.analysis.getNode().ply,
    path: window.site.analysis.path,
    cp: window.site.analysis.getNode().ceval?.cp,
    mate: window.site.analysis.getNode().ceval?.mate,
    rawWdl: window.site.analysis.getNode().ceval?.wdl,
  }));
  assert.match(data.whiteText, /^\d+%$/);
  assert.match(data.blackText, /^\d+%$/);
  data.white = Number.parseInt(data.whiteText, 10);
  data.black = Number.parseInt(data.blackText, 10);
  assert.equal(data.white + data.black, 100);
  assert.equal(data.style, `--eval-percent: ${data.black}%`);
  if (source === 'engine-score') {
    assert.equal(data.metric, 'lichess-win-percent');
    assert.match(data.tooltip, /Win% của Lichess/);
    const white = expectedWhiteWinPercent(data.cp, data.mate);
    assert.deepEqual([data.white, data.black], [white, 100 - white]);
  }
  result.samples.push({ phase, ...data });
  return data;
}

try {
  for (const fixture of fixtures) {
    assert.match(fixture.id, /^[a-zA-Z0-9]{8}$/);
    const context = await browser.newContext({ baseURL: base, userAgent, viewport: { width: 1365, height: 950 } });
    const page = await context.newPage();
    page.on('pageerror', e => report.errors.push(e.message));
    const result = { ...fixture, samples: [], modelResponses: [] };
    report.cases.push(result);
    page.on('response', response => {
      if (response.url().includes('nn-61e7af4bb97d.nnue')) result.modelResponses.push(response.status());
    });
    await page.addInitScript(() => {
      localStorage.setItem('engine.enabled', 'true');
      localStorage.setItem('analyse.show-engine', 'true');
      localStorage.setItem('ceval.engine.standard', '__sf_19_smallnet');
    });
    const originalPgn = await (await context.request.get(`/game/export/${fixture.id}`)).text();
    const positions = positionList(originalPgn);
    assert.ok(['1-0', '0-1', '1/2-1/2'].includes(positions.result));
    await page.goto(`/game/${fixture.id}/white`);
    await page.waitForFunction(() => typeof window.site?.analysis?.getNode === 'function');
    await page.keyboard.press('End');
    const final = await sample(page, result, 'official-end', 'official');
    assert.equal(final.metric, 'result');
    assert.equal(final.fen, positions.placements.at(-1));
    assert.equal(final.white, positions.result === '1-0' ? 100 : positions.result === '0-1' ? 0 : 50);

    await page.keyboard.press('Home');
    await page.waitForFunction(() => document.querySelector('.eval-gauge')?.dataset.source === 'engine-score');
    await engine(page, false);
    const initial = await sample(page, result, 'initial', 'engine-score');
    assert.equal(initial.fen, positions.placements[0]);
    await page.keyboard.press('ArrowRight');
    // With the engine stopped, an uncached node cannot keep the previous percentages.
    await page.waitForFunction(() => !document.querySelector('.eval-gauge__value'));
    result.missingEvaluationCleared = true;
    assert.equal(await page.evaluate(() => window.lichess.chessground().getFen()), positions.placements[1]);
    await engine(page, true);
    await page.waitForFunction(() => document.querySelector('.eval-gauge')?.dataset.source === 'engine-score');
    await engine(page, false);
    const first = await sample(page, result, 'first-ply-black-to-move', 'engine-score');
    assert.equal(first.fen, positions.placements[1]);
    await page.keyboard.press('f');
    await page.waitForSelector('.eval-gauge.reverse');
    const flipped = await sample(page, result, 'flipped', 'engine-score');
    assert.equal(flipped.fen, first.fen);
    assert.equal(flipped.path, first.path);
    if (flipped.cp === first.cp && flipped.mate === first.mate)
      assert.deepEqual([flipped.white, flipped.black], [first.white, first.black]);
    // A final in-flight engine update may arrive after stop. Both snapshots must
    // match their own White-oriented engine score; static input flip equality is unit tested.
    const labelPositions = await page.evaluate(() => ({
      white: document.querySelector('.eval-gauge__white').getBoundingClientRect().top,
      black: document.querySelector('.eval-gauge__black').getBoundingClientRect().top,
    }));
    assert.ok(labelPositions.white < labelPositions.black, 'White label moves to the top when Black is at the bottom');
    await page.screenshot({ path: resolve(out, `${fixture.kind}-black.png`), fullPage: true });
    await page.keyboard.press('f');

    if (fixture.variation) {
      await page.keyboard.press('Home');
      const variation = Chess.default();
      const uciMoves = ['a2a3', 'h7h6', 'a3a4', 'h6h5'].slice(0, positions.san.length);
      for (const uci of uciMoves) {
        const move = parseUci(uci);
        assert.ok(variation.isLegal(move));
        variation.play(move);
        await page.evaluate(moveUci => window.lichess.analysis.playUci(moveUci), uci);
      }
      assert.equal(await page.evaluate(() => window.lichess.chessground().getFen()), makeFen(variation.toSetup()).split(' ')[0]);
      await engine(page, true);
      await page.waitForFunction(() => document.querySelector('.eval-gauge')?.dataset.source === 'engine-score');
      await engine(page, false);
      await sample(page, result, 'variation-at-same-final-ply', 'engine-score');
      result.variationDoesNotInheritFinalResult = true;
    }
    await engine(page, true);
    await page.reload();
    await page.waitForFunction(() => typeof window.site?.analysis?.getNode === 'function');
    await page.keyboard.press('Home');
    await page.waitForFunction(() => document.querySelector('.eval-gauge')?.dataset.source === 'engine-score');
    await engine(page, false);
    await sample(page, result, 'reload-initial', 'engine-score');
    await page.waitForTimeout(1100);
    await page.screenshot({ path: resolve(out, `${fixture.kind}-white.png`), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    assert.equal(await page.locator('.eval-gauge').isVisible(), false, 'Keep upstream single-column behavior');
    await page.screenshot({ path: resolve(out, `${fixture.kind}-mobile.png`), fullPage: true });
    assert.equal(await (await context.request.get(`/game/export/${fixture.id}`)).text(), originalPgn);
    result.passed = true;
    result.serverPgnUnchanged = true;
    console.log('PASS review', fixture.kind, fixture.id, result.samples.length, 'samples');
    await context.close();
  }
  assert.deepEqual(report.errors, []);
} catch (error) {
  report.failure = String(error.stack || error);
  process.exitCode = 1;
  console.log(report.failure);
} finally {
  report.finished = new Date().toISOString();
  await writeFile(resolve(out, 'report.json'), JSON.stringify(report, null, 2));
  await browser.close();
  console.log('Report:', out);
}
