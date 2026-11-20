#!/usr/bin/env node

// Phase 1 evaluation of the AI coach (modules/aiCoach): asks a fixed question set through the real
// endpoint, checks the answers against lila's own Stockfish export, and reads latency, tokens and
// model from db.ai_coach_chat. Prints the phase 2 decision criteria; writes a CSV to rate by hand.

import { MongoClient } from 'mongodb';
import fs from 'node:fs';

const usage = `
usage: AI_COACH_EVAL_PASSWORD=... ./ai-coach-eval.mjs --user=<name> [options] <gameId> ...
       ./ai-coach-eval.mjs --rated=<csv>       # mean of the hand-filled "rating" column (1-5)

  The user must have played every game, and every game needs a finished server analysis.
  Existing coach conversations of that user on those games are deleted first (--keep to append).

options:
  --base=<url>              lila (default http://localhost:9663)
  --host=<mongodb host>     (default 127.0.0.1:27017)    --db=<name> (default lichess)
  --out=<csv>               (default ai-coach-eval.csv)
  --price-in=4 --price-out=20 --price-cache-read=0.2 --price-cache-write=5
                            USD per million tokens (default: the answering model's Anthropic list
                            price; Opus 5.5 for a model not in the table)
  --budget=0.01             max mean USD per question
`;

const args = Object.fromEntries(
  process.argv
    .slice(2)
    .filter(a => a.startsWith('--'))
    .map(a => {
      const [k, ...v] = a.slice(2).split('=');
      return [k, v.length ? v.join('=') : true];
    }),
);
const gameIds = process.argv.slice(2).filter(a => !a.startsWith('--'));
const num = (k, d) => (args[k] === undefined ? d : parseFloat(args[k]));
const base = args.base || 'http://localhost:9663';
// Anthropic list prices, USD per million tokens: input, output, cache read, cache write (5 minutes)
const listPrices = {
  'claude-opus-5-5': [4, 20, 0.2, 5],
  'claude-sonnet-5': [2, 10, 0.2, 2.5],
  'claude-sonnet-4-6': [3, 15, 0.3, 3.75],
  'claude-haiku-4-5': [1, 5, 0.1, 1.25],
};
const priceOf = model => {
  const known = Object.keys(listPrices).find(k => model === k || model?.startsWith(`${k}-2`)); // or a dated id
  const [input, output, cacheRead, cacheWrite] = listPrices[known || 'claude-opus-5-5'];
  return {
    input: num('price-in', input),
    output: num('price-out', output),
    cacheRead: num('price-cache-read', cacheRead),
    cacheWrite: num('price-cache-write', cacheWrite),
  };
};
const criteria = { keyMoves: 0.9, invented: 0.05, p95ms: 10_000, budget: num('budget', 0.01), rating: 4 };

// ---- lichess winning chances and move references, as in chess.eval.WinPercent / GameFacts.scala
const winPercent = cp =>
  50 + 50 * (2 / (1 + Math.exp(-0.00368208 * Math.max(-1000, Math.min(1000, cp)))) - 1);
const evalCp = e => (e.mate === undefined ? e.eval : Math.sign(e.mate) * 1000);
const moveRef = /\b(\d{1,3})\.(\.\.)?\s?([NBRQK]?[a-h]?[1-8]?x?[a-h][1-8](?:=[NBRQ])?|O-O(?:-O)?)[+#]?/g;
const label = (ply, san) => `${Math.ceil(ply / 2)}${ply % 2 ? '.' : '...'} ${san}`;
const strip = html =>
  html
    .replace(/<[^>]+>/g, ' ')
    .replace(/&#39;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ')
    .trim();

/** Ground truth from lila's own export of the game, independent of GameFacts.scala. */
function truth(game, userId) {
  const color = game.players.white.user?.id === userId ? 'white' : 'black';
  const sans = game.moves.split(' ');
  // evals[ply]: position after ply. The export gives a checkmate position as {mate: 0}: count it as won.
  const evals = [{ eval: 15 }, ...game.analysis].map(e =>
    e.mate === 0 ? { mate: game.winner === 'white' ? 1 : -1 } : e,
  );
  const mover = ply => (ply % 2 ? 'white' : 'black');
  const pov = (e, c) => (c === 'white' ? winPercent(evalCp(e)) : 100 - winPercent(evalCp(e)));
  const judged = sans
    .map((san, i) => ({ ply: i + 1, san, a: game.analysis[i] }))
    .filter(m => m.a?.judgment && mover(m.ply) === color)
    .map(m => ({ ...m, drop: pov(evals[m.ply - 1], color) - pov(evals[m.ply], color) }))
    .sort((x, y) => y.drop - x.drop);
  const biggest = judged.length ? judged.filter(m => m.drop >= judged[0].drop - 2) : [];
  let decisive;
  if (game.winner)
    for (let ply = sans.length; ply > 0 && pov(evals[ply], game.winner) >= 80; ply--) decisive = ply;
  const lines = game.analysis.map(a => a.variation || '').join(' ');
  return {
    color,
    sans,
    biggest,
    decisive: decisive && { ply: decisive, san: sans[decisive - 1] },
    accuracy: game.players[color].analysis?.accuracy,
    known: san => sans.includes(san) || lines.split(' ').includes(san),
  };
}

const mentions = (text, ply, san) =>
  [...text.matchAll(moveRef)].some(
    m => parseInt(m[1]) * 2 - (m[2] ? 0 : 1) === ply && m[3] === san.replace(/[+#]/g, ''),
  );

/** [question, ply to view, automatic check or undefined for human-only] */
function questions(t) {
  const big = t.biggest[0];
  const best = big?.a.judgment.comment.match(/(\S+) was best/)?.[1];
  return [
    ['What was my biggest mistake?', undefined, big && (a => t.biggest.some(m => mentions(a, m.ply, m.san)))],
    [
      'Which move decided the game?',
      undefined,
      t.decisive && (a => mentions(a, t.decisive.ply, t.decisive.san)),
    ],
    [
      'Why was this move a mistake?',
      big?.ply,
      best && (a => a.split(/[\s,.;:()]+/).includes(best.replace(/[+#]/g, '')) || a.includes(best)),
    ],
    [
      'How accurate was I compared to my opponent?',
      undefined,
      t.accuracy !== undefined && (a => a.includes(`${t.accuracy}`)),
    ],
    ['What should I work on after this game?', undefined, undefined],
  ];
}

/** The streamed answer: `{"d": text}` lines, then `{"turn": ...}` or `{"error": ...}`. */
async function readAnswer(res, onText) {
  const decoder = new TextDecoder();
  let buf = '';
  let last = {};
  const read = line => {
    if (!line.trim()) return; // keep-alive
    const json = JSON.parse(line);
    if (json.d) onText();
    else last = json;
  };
  for await (const chunk of res.body) {
    buf += decoder.decode(chunk, { stream: true });
    const lines = buf.split('\n');
    buf = lines.pop();
    lines.forEach(read);
  }
  read(buf);
  return last.turn ? { html: last.turn.html } : { error: last.error || 'answer interrupted' };
}

async function login() {
  const res = await fetch(`${base}/login`, {
    method: 'POST',
    redirect: 'manual',
    headers: { Origin: base, 'X-Requested-With': 'XMLHttpRequest' },
    body: new URLSearchParams({ username: args.user, password: process.env.AI_COACH_EVAL_PASSWORD || '' }),
  });
  const cookie = res.headers.getSetCookie().find(c => c.startsWith('lila2='));
  if (!cookie || res.status >= 400) throw new Error(`login failed: ${res.status}`);
  return cookie.split(';')[0];
}

async function run() {
  const mongo = new MongoClient(`mongodb://${args.host || '127.0.0.1:27017'}`);
  const chats = mongo.db(args.db || 'lichess').collection('ai_coach_chat');
  const cookie = await login();
  const userId = args.user.toLowerCase();
  const rows = [];
  for (const id of gameIds) {
    const game = await fetch(
      `${base}/game/export/${id}?evals=true&literate=true&accuracy=true&clocks=false`,
      {
        headers: { Accept: 'application/json' },
      },
    ).then(r => r.json());
    if (!game.analysis) {
      console.log(`${id}: no server analysis, skipped`);
      continue;
    }
    const t = truth(game, userId);
    if (!args.keep) await chats.deleteOne({ _id: `${id}/${userId}` });
    for (const [q, ply, check] of questions(t)) {
      const started = Date.now();
      const res = await fetch(`${base}/game/${id}/ai-coach`, {
        method: 'POST',
        headers: {
          Origin: base,
          Cookie: cookie,
          'X-Requested-With': 'XMLHttpRequest',
          Accept: 'application/x-ndjson',
        },
        body: new URLSearchParams(ply ? { q, ply: `${ply}` } : { q }),
      }).catch(e => ({ ok: false, status: e.cause?.code || e.message, json: async () => ({}) }));
      let clientFirstMs;
      const body = res.ok
        ? await readAnswer(res, () => (clientFirstMs ??= Date.now() - started)).catch(e => ({
            error: e.message,
          }))
        : await res.json().catch(() => ({}));
      const clientMs = Date.now() - started;
      if (!res.ok || body.error) {
        console.log(`${id} "${q}": HTTP ${res.status} ${body.error || ''}`);
        rows.push({ game: id, q, error: body.error || res.status });
        continue;
      }
      const answer = strip(body.html);
      const turn = (await chats.findOne({ _id: `${id}/${userId}` }))?.turns.at(-1) || {};
      const u = turn.usage || {};
      const price = priceOf(turn.model);
      const cost =
        ((u.input || 0) * price.input +
          (u.output || 0) * price.output +
          (u.cacheRead || 0) * price.cacheRead +
          (u.cacheWrite || 0) * price.cacheWrite) /
        1e6;
      const refs = [...answer.matchAll(moveRef)];
      const invented = refs.filter(
        m => !t.known(m[3]) && !t.known(m[3] + '+') && !t.known(m[3] + '#'),
      ).length;
      rows.push({
        game: id,
        color: t.color,
        q,
        viewing: ply ? label(ply, t.sans[ply - 1]) : '',
        pass: check ? (check(answer) ? 1 : 0) : '',
        invented,
        clientFirstMs,
        clientMs,
        serverFirstMs: turn.firstMillis,
        serverMs: turn.millis,
        model: turn.model,
        prompt: turn.prompt,
        ...u,
        cost: cost.toFixed(5),
        answer,
        rating: '',
      });
      console.log(
        `${id} ${check ? (check(answer) ? 'PASS' : 'FAIL') : '----'} first text ${turn.firstMillis}ms, ${turn.millis}ms $${cost.toFixed(4)} ${q}`,
      );
    }
  }
  await mongo.close();
  writeCsv(args.out || 'ai-coach-eval.csv', rows);
  summary(
    rows.filter(r => !r.error),
    rows.length,
  );
}

function summary(ok, total) {
  const checked = ok.filter(r => r.pass !== '');
  const keyRate = checked.length ? checked.filter(r => r.pass === 1).length / checked.length : NaN;
  const inventedRate = ok.length ? ok.filter(r => r.invented > 0).length / ok.length : NaN;
  const sorted = key =>
    ok
      .map(r => r[key])
      .filter(Boolean)
      .sort((a, b) => a - b);
  const ms = sorted('serverMs');
  const firstMs = sorted('serverFirstMs');
  const pct = (xs, q) => xs[Math.min(xs.length - 1, Math.floor(q * xs.length))];
  const p = q => pct(ms, q);
  const meanCost = ok.reduce((s, r) => s + parseFloat(r.cost), 0) / (ok.length || 1);
  const line = (name, value, pass) => console.log(`${pass ? 'PASS' : 'FAIL'}  ${name}: ${value}`);
  console.log(`\n${ok.length}/${total} answered, models: ${[...new Set(ok.map(r => r.model))].join(', ')}`);
  line(
    `key-move checks >= ${criteria.keyMoves * 100}%`,
    `${(keyRate * 100).toFixed(1)}% of ${checked.length}`,
    keyRate >= criteria.keyMoves,
  );
  line(
    `answers with invented moves <= ${criteria.invented * 100}%`,
    `${(inventedRate * 100).toFixed(1)}%`,
    inventedRate <= criteria.invented,
  );
  line(
    `p95 latency <= ${criteria.p95ms / 1000}s`,
    `p50 ${p(0.5)}ms, p95 ${p(0.95)}ms`,
    p(0.95) <= criteria.p95ms,
  );
  console.log(`----  time to first text (streamed): p50 ${pct(firstMs, 0.5)}ms, p95 ${pct(firstMs, 0.95)}ms`);
  line(
    `mean cost per question <= $${criteria.budget}`,
    `$${meanCost.toFixed(4)}`,
    meanCost <= criteria.budget,
  );
  console.log(`----  human rating >= ${criteria.rating}: fill the "rating" column, then --rated=<csv>`);
  console.log('Phase 2 (fine-tuning) only if a criterion still fails after prompt and model changes.');
}

function writeCsv(file, rows) {
  const cols = [
    'game',
    'color',
    'q',
    'viewing',
    'pass',
    'invented',
    'clientFirstMs',
    'clientMs',
    'serverFirstMs',
    'serverMs',
    'model',
    'prompt',
    'input',
    'output',
    'cacheRead',
    'cacheWrite',
    'cost',
    'error',
    'answer',
    'rating',
  ];
  const cell = v =>
    v === undefined ? '' : /[",\n]/.test(`${v}`) ? `"${`${v}`.replace(/"/g, '""')}"` : `${v}`;
  fs.writeFileSync(
    file,
    [cols.join(','), ...rows.map(r => cols.map(c => cell(r[c])).join(','))].join('\n') + '\n',
  );
  console.log(`wrote ${file}`);
}

function rated(file) {
  // "rating" is the last column, and answers are written on a single line
  const ratings = fs
    .readFileSync(file, 'utf8')
    .trim()
    .split('\n')
    .slice(1)
    .map(l => parseFloat(l.split(',').at(-1)))
    .filter(n => n >= 1 && n <= 5);
  const mean = ratings.reduce((s, n) => s + n, 0) / (ratings.length || 1);
  console.log(
    `${mean >= criteria.rating ? 'PASS' : 'FAIL'}  human rating >= ${criteria.rating}: ${mean.toFixed(2)} over ${ratings.length} answers`,
  );
}

// entry point last: the helpers above are consts, unusable before their declaration runs
if (args.rated) rated(args.rated);
else if (!args.user || !gameIds.length || args.help) {
  console.log(usage);
  process.exit(1);
} else await run();
