import { expectedScoreDisplay } from 'lib/ceval/wdl';
import { lichessWinPercentages } from 'lib/ceval/winningChances';
import { hl, type LooseVNode } from 'lib/view/snabbdom';

import type RoundController from '../ctrl';

export default function winProbability(ctrl: RoundController): LooseVNode {
  if (!ctrl.winProbability) return undefined;
  const prediction = ctrl.winProbability.data;
  const replay = ctrl.replaying();
  const ready = !replay && (prediction?.status === 'ready' || prediction?.status === 'finished');
  const official = prediction?.source === 'official';
  const p = ready ? prediction.probabilities : undefined;
  const winPercent =
    ready && !official
      ? lichessWinPercentages({ cp: prediction.evaluation_cp, mate: prediction.mate })
      : undefined;
  const officialDraw = !!(official && p && p.draw === 1 && !p.white && !p.black);
  const display =
    winPercent ?? (p && !officialDraw && expectedScoreDisplay(p, official ? 'result' : 'estimate'));
  const result = !!display || officialDraw;
  const metric = official ? 'result' : winPercent ? 'lichess-win-percent' : 'expected-score';
  const description = winPercent
    ? 'Ưu thế theo Win% của Lichess từ điểm Stockfish.'
    : 'Ưu thế theo WDL của Stockfish. Hòa tính nửa điểm.';
  const status = replay
    ? 'Trở về nước mới nhất để xem ưu thế.'
    : prediction?.status === 'stale'
      ? 'Mất kết nối · đang chờ thế cờ mới nhất.'
      : prediction?.status === 'aborted'
        ? 'Ván đã hủy · không có kết quả.'
        : prediction?.status === 'unavailable'
          ? 'Tạm thời chưa có đánh giá.'
          : prediction?.status === 'busy'
            ? 'Đang chờ đánh giá…'
            : 'Đang tính…';
  return hl(
    'section.win-probability',
    {
      attrs: {
        'aria-label':
          ready && official
            ? 'Kết quả ván đấu'
            : `Ưu thế Trắng/Đen theo ${winPercent ? 'Win% của Lichess' : 'điểm kỳ vọng'}`,
        'data-state': replay ? 'replay' : (prediction?.status ?? 'pending'),
        'data-source': result ? (official ? 'official' : 'engine') : false,
        'data-metric': result ? metric : false,
        title:
          display && !official
            ? `${description} 50% = cân bằng. Chưa xét trình độ người chơi hay cấp độ bot. Tỷ lệ đã làm tròn.`
            : false,
      },
    },
    [
      display
        ? [
            hl(
              'div.win-probability__bar',
              { attrs: { 'aria-hidden': 'true' } },
              ['white', 'black'].map((color, i) =>
                hl(`span.win-probability__${color}`, {
                  attrs: { style: `width:${display[i]}%` },
                }),
              ),
            ),
            hl(
              'div.win-probability__values',
              { attrs: { 'aria-live': 'polite' } },
              ['Trắng', 'Đen'].map((color, i) => hl('span', `${color} ${display[i]}%`)),
            ),
          ]
        : hl(
            'div.win-probability__status',
            { attrs: { role: 'status' } },
            officialDraw ? 'Ván đấu kết thúc hòa.' : p ? 'Chưa có đánh giá ưu thế cho vị trí này.' : status,
          ),
      result && official
        ? hl(
            'div.win-probability__source',
            { attrs: { title: 'Kết quả ván đấu đã được xác nhận.' } },
            'Kết quả chính thức',
          )
        : undefined,
    ],
  );
}
