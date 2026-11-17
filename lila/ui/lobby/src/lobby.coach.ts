import { randomId } from 'lib/algo';
import * as xhr from 'lib/xhr';

// The key lives only for this form and is reused after uncertain HTTP failures.
export function initModule(): void {
  const form = document.querySelector<HTMLFormElement>('.coach-setup__form');
  if (!form) return;
  const status = form.querySelector<HTMLElement>('[role=status]')!;
  const submit = form.querySelector<HTMLButtonElement>('button[type=submit]')!;
  let key = randomId(32);
  let previous = '';
  let busy = false;
  form.addEventListener('submit', async e => {
    e.preventDefault();
    if (busy || submit.disabled) return;
    const values = new FormData(form);
    const body = JSON.stringify({
      color: values.get('color'),
      level: Number(values.get('level')),
      support: values.get('support'),
    });
    if (previous && previous !== body) key = randomId(32);
    previous = body;
    busy = true;
    submit.disabled = true;
    status.textContent = i18n.aicoach.creating;
    try {
      const response = await xhr.jsonAnyResponse('/ai-coach/sessions', {
        method: 'POST',
        headers: {
          ...xhr.jsonHeader,
          ...xhr.xhrHeader,
          'Content-Type': 'application/json',
          'Idempotency-Key': key,
        },
        body,
      });
      const result = await response.json();
      if (!response.ok) {
        status.textContent =
          result.error === 'activeLessonExists' ? i18n.aicoach.activeExists : i18n.aicoach.createError;
        return;
      }
      location.assign(result.playUrl);
    } catch {
      status.textContent = i18n.aicoach.createError;
    } finally {
      busy = false;
      submit.disabled = false;
    }
  });
}
