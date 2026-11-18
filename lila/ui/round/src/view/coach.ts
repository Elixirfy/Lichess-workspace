import { Chessground } from '@lichess-org/chessground';
import { makeSquare } from 'chessops/util';

import { hl, bind, bindSubmit, onInsert, type VNode } from 'lib/view';

import type CoachCtrl from '../coach';
import type { CoachCard, CoachSummary, QuestionKind } from '../coach';
import type CoachPractice from '../coachPractice';
import { colorNames, pieceNames } from '../coachPracticeFeedback';

export function renderCoach(coach?: CoachCtrl, nvui = false): VNode | undefined {
  if (!coach) return undefined;
  const s = coach.snapshot;
  const t = i18n.aicoach;
  const position = coach.position();
  const card = coach.currentCard();
  const practice = coach.activePractice();
  const analysing = s?.support === 'proactive' && s.coverage.analysed + s.coverage.failed < s.coverage.total;
  const openingAdvice =
    position.live && coach.connection === 'ready' && coach.matchesPosition() && s?.openingAdvice;
  const question = (kind: QuestionKind, label: string) =>
    hl(
      'button.button',
      {
        attrs: { type: 'button', disabled: !coach.canAsk(kind) },
        hook: bind('click', () => void coach.ask(kind)),
      },
      label,
    );
  return hl('section.round__coach', { attrs: { 'aria-label': t.coach, lang: 'vi' } }, [
    hl('header.coach-header', [hl('h2', t.coach), s && hl('small', t[s.support])]),
    hl(
      'div.coach-cards',
      { attrs: { role: 'status', 'aria-live': 'polite', 'aria-atomic': 'true' } },
      card
        ? [renderCard(card)]
        : [hl('p.coach-empty', coach.pending || analysing ? t.pending : openingAdvice || t.noCards)],
    ),
    practice
      ? nvui && renderCoachPractice(coach, true)
      : card &&
        coach.canPractice(card) &&
        coach.matchesPosition() &&
        hl(
          'button.button.coach-try-again',
          { key: card.id, attrs: { type: 'button' }, hook: bind('click', () => coach.startPractice(card)) },
          'Thử lại từ thế này',
        ),
    hl('div.coach-status', { attrs: { role: 'status', 'aria-live': 'polite', 'aria-atomic': 'true' } }, [
      coach.connection !== 'ready' &&
        hl('p', t[coach.connection === 'loading' ? 'connecting' : coach.connection]),
      coach.pending && !!card && hl('p', t.pending),
      s && !coach.matchesPosition() && hl('p', t.connecting),
      coach.error && hl('p', t[coach.error]),
      s && hl('small.coach-coverage', t.coverage(s.coverage.analysed, s.coverage.total)),
      !!s?.coverage.failed && hl('p', t.failedCoverage(s.coverage.failed)),
      s?.questions.some(q => q.state === 'failed') && hl('p', t.failedQuestion),
    ]),
    coach.connection === 'unavailable' &&
      hl('button.button', { hook: bind('click', coach.refresh) }, t.retry),
    !position.live && hl('p', t.historyView),
    !position.live && hl('button.button', { hook: bind('click', coach.goLive) }, t.backToLive),
    s && s.phase !== 'abandoned' && s.status === 'started' && !s.capabilities.hint && hl('p', t.waiting),
    s?.phase === 'abandoned' &&
      hl('div.coach-abandoned', [
        hl('p', t.abandoned),
        hl(
          'button.button',
          { attrs: { disabled: coach.posting }, hook: bind('click', coach.resumeLesson) },
          t.resume,
        ),
        hl('a.button', { attrs: { href: '/ai-coach' } }, t.newLesson),
      ]),
    hl('div.coach-questions', [
      question('hint', s ? t.hintStage(Math.min(s.hintLevel + 1, 3)) : t.hint),
      question('explain', t.explain),
      question('threat', t.threat),
    ]),
    coach.retry &&
      !coach.posting &&
      hl('button.button', { hook: bind('click', coach.retryQuestion) }, t.retryQuestion),
    s &&
      s.status !== 'started' &&
      hl('div.coach-finished', [
        hl('p', t.finished),
        hl('a.button', { attrs: { href: '/ai-coach' } }, t.newLesson),
      ]),
    s?.summary &&
      coach.matchesPosition() &&
      s.summary.positionRevision === s.positionRevision &&
      s.summary.status === s.status &&
      renderSummary(s.summary),
  ]);
}

const action = (label: string, click: () => void, primary = false, disabled = false) =>
  hl(
    'button.button.button-no-upper' + (primary ? '' : '.button-metal'),
    { attrs: { type: 'button', disabled }, hook: bind('click', click) },
    label,
  );

export function renderCoachPractice(coach?: CoachCtrl, nvui = false): VNode | undefined {
  if (!coach) return undefined;
  const practice = coach.activePractice();
  if (!practice) return undefined;
  return renderPractice(
    practice,
    () => {
      coach.closePractice();
      requestAnimationFrame(() => document.querySelector<HTMLButtonElement>('.coach-try-again')?.focus());
    },
    nvui,
  );
}

function renderPractice(practice: CoachPractice, close: () => void, nvui: boolean): VNode {
  return hl(
    'section.coach-practice',
    {
      key: practice.cardId,
      attrs: { 'aria-label': 'Thử lại nước đi', lang: 'vi' },
      hook: onInsert(el => {
        el.querySelector('h2')?.focus({ preventScroll: true });
        el.scrollIntoView({ block: 'nearest' });
      }),
    },
    [
      hl('h2', { attrs: { tabindex: -1 } }, 'Bàn luyện'),
      hl('div.coach-practice-workspace', [
        hl('div.coach-practice-play', [
          nvui
            ? hl('details', [
                hl('summary', 'Bố trí quân'),
                ...(['white', 'black'] as const).map(color =>
                  hl(
                    'p',
                    [
                      colorNames[color],
                      ...[...practice.position.board]
                        .filter(([, piece]) => piece.color === color)
                        .map(([square, piece]) => `${pieceNames[piece.role]} ${makeSquare(square)}`),
                    ].join(', '),
                  ),
                ),
              ])
            : hl('div.coach-practice-board.cg-wrap', {
                hook: {
                  ...onInsert(element => {
                    practice.ground = Chessground(element, practice.config());
                  }),
                  postpatch: () => practice.ground?.set(practice.config()),
                  destroy: () => practice.ground?.destroy(),
                },
              }),
          renderPracticeControls(practice, close),
        ]),
        hl('div.coach-practice-guide', { attrs: { role: 'status', 'aria-atomic': 'true' } }, [
          practice.feedback
            ? hl(
                'p.coach-practice-feedback',
                (practice.foundAlternative ? 'Đúng hướng. ' : '') + practice.feedback,
              )
            : hl('p', practice.data.prompt),
          practice.inSolution &&
            !practice.canFollowSolution &&
            !practice.ended &&
            hl('p', 'Đã hết biến mẫu. Bạn có thể tự đi tiếp.'),
        ]),
      ]),
    ],
  );
}

function renderPracticeControls(practice: CoachPractice, close: () => void): VNode {
  const moves = practice.moveHistory;
  const disabled = practice.ended || !!practice.promotion;
  return hl('div.coach-practice-controls', [
    hl('div.coach-practice-position', [
      hl('strong', practice.ended ? 'Nhánh đã kết thúc' : `${colorNames[practice.position.turn]} đi`),
      moves.length > 0 && hl('p.coach-practice-moves', moves.join(' ')),
    ]),
    practice.promotionOptions.length > 0 &&
      hl(
        'div.coach-practice-actions',
        practice.promotionOptions.map(([role, name]) => action(name, () => practice.promote(role))),
      ),
    hl(
      'form.coach-practice-input',
      {
        hook: bindSubmit(event => {
          const form = event.target as HTMLFormElement;
          const value = new FormData(form).get('move');
          if (typeof value === 'string') practice.play(value);
          form.reset();
        }),
      },
      [
        hl('label', [
          'Nhập nước thử',
          hl('input', {
            attrs: { name: 'move', placeholder: 'e2e4', autocomplete: 'off', required: true, disabled },
          }),
        ]),
        hl('button.button.button-no-upper', { attrs: { type: 'submit', disabled } }, 'Đi thử'),
      ],
    ),
    hl('div.coach-practice-actions', [
      action('Lùi 1 nước', () => practice.undo(), false, !practice.canUndo),
      action('Về thế ban đầu', () => practice.reset()),
      action('Nước đã đi', () => practice.show(practice.data.played)),
      action('Xem gợi ý', () => practice.show(practice.data.alternatives[0])),
      practice.inSolution &&
        action('Xem nước tiếp', () => practice.followSolution(), true, !practice.canFollowSolution),
      practice.capture && action('Xem nước bắt', () => practice.showCapture(), true),
    ]),
    hl('div.coach-practice-return', [action('Về ván đang chơi', close)]),
  ]);
}

function renderCard(card: CoachCard): VNode {
  const t = i18n.aicoach;
  // Render public fields only; no JSON payload or model data in DOM attributes.
  return hl('article.coach-card', { key: card.id }, [
    hl('small.coach-context', `${card.moveLabel} · ${card.scope === 'live' ? t.live : t.history}`),
    hl('p.coach-sentence', card.text),
    card.hintLevel === 3 &&
      card.moves.length > 0 &&
      hl('details', [hl('summary', t.variation), hl('p', card.moves.map(m => m.san).join(' '))]),
  ]);
}

function renderSummary(summary: CoachSummary): VNode {
  const t = i18n.aicoach;
  return hl('details.coach-summary', { attrs: { 'aria-label': t.summary } }, [
    hl('summary', t.summary),
    hl(
      'p.summary-state',
      t[
        ('summary' + summary.state[0].toUpperCase() + summary.state.slice(1)) as
          | 'summaryPending'
          | 'summaryReady'
          | 'summaryPartial'
          | 'summaryFailed'
      ],
    ),
    hl('p', summary.message),
    hl('p', t.coverage(summary.coverage.analysed, summary.coverage.total)),
    summary.moments.map(renderCard),
    summary.advice && hl('p.summary-advice', [hl('strong', t.advice + ': '), summary.advice]),
  ]);
}
