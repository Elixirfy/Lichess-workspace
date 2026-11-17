import { hl, bind, type VNode } from 'lib/view';

import type CoachCtrl from '../coach';
import type { CoachCard, CoachSummary, QuestionKind } from '../coach';

export function renderCoach(coach?: CoachCtrl): VNode | undefined {
  if (!coach) return undefined;
  const s = coach.snapshot;
  const t = i18n.aicoach;
  const position = coach.position();
  const card = coach.currentCard();
  const analysing = s?.support === 'proactive' && s.coverage.analysed + s.coverage.failed < s.coverage.total;
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
      card ? [renderCard(card)] : [hl('p.coach-empty', coach.pending || analysing ? t.pending : t.noCards)],
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

function renderCard(card: CoachCard): VNode {
  const t = i18n.aicoach;
  // Render public fields only; no JSON payload or model data in DOM attributes.
  return hl('article.coach-card', { key: card.id }, [
    hl('small.coach-context', `${card.moveLabel} · ${card.scope === 'live' ? t.live : t.history}`),
    hl('p.coach-sentence', card.text),
    card.hintLevel === 3 &&
      card.moves.length > 0 &&
      hl('p', `${t.variation}: ${card.moves.map(m => m.san).join(' ')}`),
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
