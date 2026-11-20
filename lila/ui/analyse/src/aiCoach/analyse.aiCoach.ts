import { form, jsonAnyResponse, readNdJson, xhrHeader } from 'lib/xhr';

// AI Coach tab of a finished game (modules/aiCoach). Loaded by serverSideUnderboard when the tab opens.
import type AnalyseCtrl from '../ctrl';

interface Turn {
  q: string;
  html: string; // sanitized server-side markdown rendering
  viewing?: string;
}

// one line of the streamed answer: a text delta, then the stored turn, or an error. On a game without the
// server analysis, the first question starts it: "analysing" comes first.
interface Line {
  status?: 'analysing';
  d?: string;
  turn?: Turn;
  error?: string;
}

// texts in the site language, from CoachText.scala
interface I18n {
  thinking: string;
  willAnalyse: string;
  analysing: string;
  unavailable: string;
  tooMany: string;
  interrupted: string;
  error: string;
}

// a game move as the coach writes it: "12. Nf3", "12... Nxe4", "12...O-O"
const moveRef = /\b(\d{1,3})\.(\.\.)?\s?([NBRQK]?[a-h]?[1-8]?x?[a-h][1-8](?:=[NBRQ])?|O-O(?:-O)?)[+#]?/g;

// what the server's CoachLlm.clean removes, so the text being written does not flash reasoning or tags
const draft = (raw: string): string =>
  raw
    .replace(/<think>[\s\S]*?(<\/think>|$)/g, '')
    .replace(/<\/?[a-zA-Z][\w-]*(\s[^<>]*)?\/?>/g, '')
    .replace(/<[^>]*$/, '')
    .trimStart();

export function initModule(ctrl: AnalyseCtrl): void {
  const root = document.querySelector<HTMLElement>('.analyse__underboard__panels .ai-coach');
  if (!root || root.dataset.state === 'ready' || root.dataset.state === 'loading') return;
  const url = root.dataset.url!;
  const i18n: I18n = JSON.parse(root.dataset.i18n!);
  const log = root.querySelector<HTMLElement>('.ai-coach__log')!;
  const formEl = root.querySelector<HTMLFormElement>('.ai-coach__form')!;
  const input = formEl.querySelector<HTMLTextAreaElement>('textarea')!;

  const setEnabled = (on: boolean) =>
    root.querySelectorAll<HTMLButtonElement | HTMLTextAreaElement>('button, textarea').forEach(el => {
      el.disabled = !on;
    });

  // follows the answer as it grows, unless the student scrolled up to read
  const scroll = (force = false) => {
    if (force || log.scrollHeight - log.scrollTop - log.clientHeight < 60) log.scrollTop = log.scrollHeight;
  };

  const add = (cls: string, content: string | Node): HTMLElement => {
    const el = document.createElement('div');
    el.className = `ai-coach__${cls}`;
    el.append(content);
    log.append(el);
    scroll(true);
    return el;
  };

  const question = (q: string, viewing?: string) => {
    root.classList.add('ai-coach--started'); // the suggestions make room for the conversation
    const el = add('q', q);
    if (viewing) el.dataset.viewing = viewing;
  };

  const answer = (el: HTMLElement, html: string) => {
    el.innerHTML = html;
    linkMoves(el, ctrl);
    scroll();
  };

  const fail = (el: HTMLElement, message: string) => {
    el.classList.remove('ai-coach__pending', 'ai-coach__draft');
    el.classList.add('ai-coach__error');
    el.textContent = message;
  };

  // the move on the board, so "this move" means something to the coach
  const viewingPly = (): number | undefined =>
    ctrl.onMainline && ctrl.node.ply > ctrl.tree.root.ply ? ctrl.node.ply : undefined;

  const ask = async (q: string) => {
    setEnabled(false);
    const ply = viewingPly();
    const san = ply && ctrl.mainline.find(n => n.ply === ply)?.san;
    question(q, san ? `${Math.ceil(ply / 2)}${ply % 2 ? '.' : '...'} ${san}` : undefined);
    const el = add('a', i18n.thinking);
    el.classList.add('ai-coach__pending');
    try {
      const res = await fetch(url, {
        method: 'post',
        body: form({ q, ply }),
        headers: { ...xhrHeader, Accept: 'application/x-ndjson' },
        credentials: 'same-origin',
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        fail(el, res.status === 429 ? i18n.tooMany : body.error || i18n.error);
      } else {
        let raw = '';
        let done = false;
        await readNdJson<Line>(res, line => {
          if (line.status === 'analysing') el.textContent = i18n.analysing;
          else if (line.d) {
            raw += line.d;
            el.classList.remove('ai-coach__pending');
            el.classList.add('ai-coach__draft');
            el.textContent = draft(raw);
            scroll();
          } else if (line.turn) {
            done = true;
            el.classList.remove('ai-coach__pending', 'ai-coach__draft');
            log.querySelector('.ai-coach__notice')?.remove(); // the analysis is there now
            answer(el, line.turn.html);
          } else if (line.error) {
            done = true;
            fail(el, line.error);
          }
        });
        if (!done) fail(el, i18n.interrupted);
      }
    } catch {
      fail(el, i18n.unavailable);
    }
    setEnabled(true);
    input.focus();
  };

  if (!root.dataset.state) {
    formEl.addEventListener('submit', e => {
      e.preventDefault();
      const q = input.value.trim();
      if (!q || root.dataset.state !== 'ready') return;
      input.value = '';
      ask(q);
    });
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        formEl.requestSubmit();
      }
    });
    root.querySelectorAll<HTMLButtonElement>('.ai-coach__suggestions button').forEach(btn =>
      btn.addEventListener('click', () => {
        input.value = btn.textContent || '';
        formEl.requestSubmit();
      }),
    );
  }

  root.dataset.state = 'loading';
  setEnabled(false);
  jsonAnyResponse(url)
    .then(res => (res.ok ? res.json() : Promise.reject(res.status)))
    .then((data: { ready: boolean; turns: Turn[] }) => {
      log.querySelector('.ai-coach__notice')?.remove();
      if (!data.ready && !data.turns.length) add('notice', i18n.willAnalyse);
      for (const turn of data.turns) {
        question(turn.q, turn.viewing);
        answer(add('a', ''), turn.html);
      }
      root.dataset.state = 'ready';
      setEnabled(true);
    })
    .catch(() => {
      add('notice', i18n.unavailable);
      root.dataset.state = 'waiting';
    });
}

// Make "12... Nxe4" in an answer clickable, when it is the move actually played at that point.
function linkMoves(el: HTMLElement, ctrl: AnalyseCtrl) {
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  const texts: Text[] = [];
  while (walker.nextNode()) texts.push(walker.currentNode as Text);
  for (const text of texts) {
    const value = text.data;
    const frag = document.createDocumentFragment();
    let last = 0;
    for (const m of value.matchAll(moveRef)) {
      const ply = parseInt(m[1]) * 2 - (m[2] ? 0 : 1);
      const node = ctrl.mainline.find(n => n.ply === ply);
      if (!node?.san || node.san.replace(/[+#]/g, '') !== m[3]) continue;
      frag.append(value.slice(last, m.index));
      const link = document.createElement('a');
      link.className = 'ai-coach__move';
      link.textContent = m[0];
      link.addEventListener('click', () => {
        ctrl.jumpToMain(ply);
        ctrl.redraw();
      });
      frag.append(link);
      last = m.index + m[0].length;
    }
    if (last === 0) continue;
    frag.append(value.slice(last));
    text.replaceWith(frag);
  }
}
