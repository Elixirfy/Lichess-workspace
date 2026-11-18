'use strict';
const $ = id => document.getElementById(id);
const api = '/voice-asr';
const headers = { 'X-Voice-Recording': '1' };
let phrases = [], records = [], stream, context, source, processor, silence;
let frames = [], sampleCount = 0, rate = 0, pcm, capturedPhrase, previewUrl, timer, deadline;
let active = false, busy = false, current = 0;

function status(text, error = false) {
  $('status').textContent = text;
  $('status').classList.toggle('error', error);
}
function controls() {
  $('record').disabled = busy || active || !phrases.length;
  $('stop').disabled = !active;
  $('save').disabled = busy || active || !pcm;
  $('phrase').disabled = busy || active || !phrases.length;
  $('next').disabled = busy || active || current >= phrases.length - 1;
}
function discardPreview() {
  pcm = undefined;
  capturedPhrase = undefined;
  $('preview').pause();
  $('preview').removeAttribute('src');
  $('preview').hidden = true;
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = undefined;
}
function select(index) {
  discardPreview();
  current = index;
  $('phrase').value = phrases[current].id;
  $('prompt').textContent = `“${phrases[current].text}”`;
  $('timer').textContent = '0.0';
  status('Bấm “Bắt đầu thu”, đọc nguyên câu, rồi bấm “Dừng thu”.');
  controls();
}
function wav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2), view = new DataView(buffer);
  const text = (offset, value) => [...value].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
  text(0, 'RIFF'); view.setUint32(4, buffer.byteLength - 8, true); text(8, 'WAVE');
  text(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
  view.setUint16(22, 1, true); view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  text(36, 'data'); view.setUint32(40, samples.length * 2, true);
  samples.forEach((value, i) => view.setInt16(44 + i * 2, Math.max(-1, Math.min(1, value)) * 32767, true));
  return new Blob([buffer], { type: 'audio/wav' });
}
async function release() {
  clearInterval(timer); clearTimeout(deadline);
  if (processor) { processor.onaudioprocess = null; processor.disconnect(); }
  source?.disconnect(); silence?.disconnect();
  stream?.getTracks().forEach(track => track.stop());
  const closing = context;
  stream = context = source = processor = silence = undefined;
  if (closing && closing.state !== 'closed') await closing.close();
  $('level').value = 0;
}
async function stop() {
  if (!active) return;
  active = false; busy = true; controls();
  await release();
  if (sampleCount < rate / 10) {
    frames = []; busy = false; controls();
    status('Bản thu quá ngắn. Hãy bấm thu lại và đọc trọn câu.', true); return;
  }
  pcm = new Float32Array(sampleCount);
  let offset = 0;
  for (const frame of frames) { pcm.set(frame, offset); offset += frame.length; }
  frames = [];
  previewUrl = URL.createObjectURL(wav(pcm, rate));
  $('preview').src = previewUrl; $('preview').hidden = false;
  $('timer').textContent = (sampleCount / rate).toFixed(1);
  busy = false; controls();
  status('Đã dừng. Nghe lại, rồi bấm “Lưu bản thu” hoặc “Bắt đầu thu” để thu lại.');
}
async function record() {
  if (busy || active) return;
  discardPreview(); busy = true; controls();
  status('Đang mở microphone…');
  try {
    context = new AudioContext();
    await context.resume();
    stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }, video: false });
    rate = context.sampleRate;
    frames = []; sampleCount = 0; capturedPhrase = phrases[current].id;
    source = context.createMediaStreamSource(stream);
    processor = context.createScriptProcessor(4096, 1, 1);
    silence = context.createGain(); silence.gain.value = 0;
    processor.onaudioprocess = event => {
      if (!active) return;
      const input = event.inputBuffer.getChannelData(0);
      const part = input.slice(0, Math.min(input.length, rate * 12 - sampleCount));
      frames.push(part); sampleCount += part.length;
      let peak = 0;
      for (const value of part) peak = Math.max(peak, Math.abs(value));
      $('level').value = peak;
      if (sampleCount >= rate * 12) void stop();
    };
    source.connect(processor); processor.connect(silence); silence.connect(context.destination);
    active = true; busy = false; controls();
    timer = setInterval(() => { $('timer').textContent = (sampleCount / rate).toFixed(1); }, 100);
    deadline = setTimeout(() => void stop(), 12000);
    stream.getAudioTracks()[0].onended = () => { if (active) void stop(); };
    status('Đang thu… Đọc nguyên câu rồi bấm “Dừng thu”.');
  } catch (error) {
    active = false; await release(); busy = false; controls();
    status(error.name === 'NotAllowedError' ? 'Chưa được cấp quyền microphone. Hãy cho phép rồi thử lại.' : `Không mở được microphone: ${error.message}`, true);
  }
}
async function refresh() {
  const response = await fetch(`${api}/recordings`, { headers });
  if (!response.ok) throw new Error(`Không tải được danh sách (${response.status})`);
  const data = await response.json();
  phrases = data.phrases; records = data.recordings.filter(r => r.source === 'browser-microphone');
  if (!$('phrase').options.length) {
    for (const [i, phrase] of phrases.entries()) {
      const option = document.createElement('option'); option.value = phrase.id; option.textContent = `${i + 1}. ${phrase.text}`;
      $('phrase').append(option);
    }
  }
  $('saved').replaceChildren();
  let done = 0;
  for (const phrase of phrases) {
    const saved = records.filter(r => r.phrase_id === phrase.id).at(-1);
    const li = document.createElement('li'); li.textContent = `${saved ? '✓' : '○'} ${phrase.text}`;
    if (saved) {
      done++;
      const play = document.createElement('button'); play.textContent = 'Nghe bản đã lưu';
      play.onclick = async () => {
        if (active || busy) return;
        try {
          const response = await fetch(`${api}/recordings/${saved.id}/audio`, { headers });
          if (!response.ok) throw new Error('Không tải được bản thu');
          discardPreview();
          previewUrl = URL.createObjectURL(await response.blob());
          $('preview').src = previewUrl; $('preview').hidden = false;
          controls(); await $('preview').play();
        } catch (error) { status(error.message, true); }
      };
      li.append(play);
    }
    $('saved').append(li);
  }
  $('progress').textContent = `Đã lưu ${done} / ${phrases.length} câu`;
  $('complete').hidden = done !== phrases.length;
}
async function save() {
  if (busy || active || !pcm) return;
  busy = true; controls(); status('Đang lưu trên máy local…');
  try {
    const response = await fetch(`${api}/recordings`, { method: 'POST', headers: {
      ...headers, 'Content-Type': 'application/octet-stream', 'X-Sample-Rate': String(rate), 'X-Voice-Phrase': capturedPhrase,
    }, body: pcm });
    if (!response.ok) throw new Error(`Không lưu được (${response.status}). Bản thu vẫn còn để thử lại.`);
    await refresh();
    pcm = undefined;
    status('Đã lưu. Bấm “Câu tiếp theo” để thu câu kế tiếp.');
  } catch (error) { status(error.message, true); }
  finally { busy = false; controls(); }
}
$('record').onclick = record; $('stop').onclick = stop; $('save').onclick = save;
$('next').onclick = () => select(current + 1);
$('phrase').onchange = () => select(phrases.findIndex(p => p.id === $('phrase').value));
window.addEventListener('pagehide', () => { active = false; void release(); });
refresh().then(() => {
  const missing = phrases.findIndex(p => !records.some(r => r.phrase_id === p.id));
  select(Math.max(0, missing));
}).catch(error => status(error.message, true));
