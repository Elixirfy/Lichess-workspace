import { hl, type LooseVNode } from 'lib/view/snabbdom';

import type RoundController from '../ctrl';
import { expectedScorePercentages } from '../winProbability';

export default function winProbability(ctrl: RoundController): LooseVNode {
  if (!ctrl.winProbability) return undefined;
  const prediction = ctrl.winProbability.data;
  const replay = ctrl.replaying();
  const ready = !replay && (prediction?.status === 'ready' || prediction?.status === 'finished');
  const human =
    ready && prediction.source === 'engine' && prediction.human?.status === 'ready'
      ? prediction.human
      : undefined;
  const p = ready && (human?.probabilities ?? prediction.probabilities);
  const source = prediction?.source === 'official' ? 'official' : human?.probabilities ? 'human' : 'engine';
  const officialDraw = !!(ready && source === 'official' && p && p.draw === 1 && !p.white && !p.black);
  const values = p && !officialDraw && expectedScorePercentages(p);
  const result = !!values || officialDraw;
  const label =
    source === 'official'
      ? 'Kết quả chính thức'
      : source === 'human'
        ? 'Ưu thế người chơi · thử nghiệm'
        : 'Ưu thế theo engine';
  const description =
    source === 'official'
      ? 'Kết quả ván đấu đã được xác nhận.'
      : source === 'human'
        ? 'Điểm kỳ vọng từ thế cờ, rating và đồng hồ; hòa tính nửa điểm cho mỗi bên. Mô hình thử nghiệm, chưa hiệu chỉnh cho cộng đồng máy chủ này.'
        : 'Điểm kỳ vọng từ thế cờ theo engine; hòa tính nửa điểm cho mỗi bên. Chưa xét trình độ người chơi hay cấp độ bot.';
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
          ready && source === 'official' ? 'Kết quả ván đấu' : 'Ưu thế Trắng/Đen theo điểm kỳ vọng',
        'data-state': replay ? 'replay' : (prediction?.status ?? 'pending'),
        'data-source': result ? source : false,
        'data-metric': result ? (source === 'official' ? 'result' : 'expected-score') : false,
        'data-model': values && human ? (human.model_id ?? false) : false,
        title:
          values && source !== 'official'
            ? `${label}. 50% = cân bằng · Hòa tính nửa điểm. ${description}`
            : false,
      },
    },
    [
      values
        ? [
            hl(
              'div.win-probability__bar',
              { attrs: { 'aria-hidden': 'true' } },
              ['white', 'black'].map((color, i) =>
                hl(`span.win-probability__${color}`, {
                  attrs: { style: `width:${values[i]}%` },
                }),
              ),
            ),
            hl(
              'div.win-probability__values',
              { attrs: { 'aria-live': 'polite' } },
              ['Trắng', 'Đen'].map((color, i) => hl('span', `${color} ${values[i].toFixed(1)}%`)),
            ),
          ]
        : hl(
            'div.win-probability__status',
            { attrs: { role: 'status' } },
            officialDraw ? 'Ván đấu kết thúc hòa.' : p ? 'Chưa có đánh giá ưu thế cho vị trí này.' : status,
          ),
      result && source === 'official'
        ? hl('div.win-probability__source', { attrs: { title: description } }, label)
        : undefined,
    ],
  );
}
