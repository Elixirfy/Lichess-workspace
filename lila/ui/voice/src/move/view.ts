import { h, type VNode } from 'snabbdom';

import type { Prop } from 'lib';
import { bind, rangeConfig } from 'lib/view';

export function settingNodes(
  colors: Prop<boolean>,
  clarity: Prop<number>,
  timer: Prop<number>,
  redraw: () => void,
  vietnamese = false,
): VNode[] {
  if (vietnamese)
    return [
      colorsSetting(colors, redraw),
      h(
        'p',
        'Có thể nói “tốt trắng e hai e bốn”, “đưa tốt từ e hai đến e bốn”, “mã nhảy lên ép ba” hoặc “nhập thành ngắn”. Cột B đọc “bê”, “bờ” hoặc “bi”; D đọc “đê”, “dê”, “dờ”, “đờ” hoặc “đi”; F đọc “ép”. Có thể đọc rõ “tốt từ cột bê hàng hai đến cột bê hàng bốn”. D đọc kiểu Anh nên nói rõ “cột đi hàng hai”, hoặc đọc đủ cả ô đi và ô đến, để phân biệt với động từ “đi”. Khi tên cột khó nghe, dùng số từ A = một đến H = tám, ví dụ “tốt từ cột hai hàng hai đến cột hai hàng bốn”. Số 4 đọc “bốn” hoặc “tư”. Nước đi rõ ràng và hợp lệ sẽ được đi ngay, không cần xác nhận. Nước sai hoặc chưa rõ sẽ có thông báo; khi có nhiều nước phù hợp, hãy nói rõ ô xuất phát hoặc chọn mũi tên. Giữ Shift để nói nếu bật chế độ nhấn giữ.',
      ),
    ];
  return [colorsSetting(colors, redraw), claritySetting(clarity, redraw), timerSetting(timer, redraw)];
}

export function colorsSetting(colors: Prop<boolean>, redraw: () => void): VNode {
  return h('div.voice-choices', [
    'Label with',
    h(
      'span.btn-rack',
      ['Colors', 'Numbers'].map(pref =>
        h(
          `span.btn-rack__btn`,
          {
            class: { active: colors() === (pref === 'Colors') },
            hook: bind('click', () => colors(pref === 'Colors'), redraw),
          },
          pref,
        ),
      ),
    ),
  ]);
}

export function claritySetting(clarity: Prop<number>, redraw: () => void): VNode {
  return h('div.voice-setting', [
    h('label', { attrs: { for: 'voice-clarity' } }, 'Clarity'),
    h('input#voice-clarity', {
      attrs: { type: 'range', min: 0, max: 2, step: 1 },
      hook: rangeConfig(clarity, val => {
        clarity(val);
        redraw();
      }),
    }),
    h('div.range_value', ['Fuzzy', 'Average', 'Clear'][clarity()]),
  ]);
}

export function timerSetting(timer: Prop<number>, redraw: () => void): VNode {
  return h('div.voice-setting', [
    h('label', { attrs: { for: 'voice-timer' } }, 'Timer'),
    h('input#voice-timer', {
      attrs: { type: 'range', min: 0, max: 5, step: 1 },
      hook: rangeConfig(timer, val => {
        timer(val);
        redraw();
      }),
    }),
    h('div.range_value', ['Off', '1.5s', '2s', '2.5s', '3s', '5s'][timer()]),
  ]);
}
