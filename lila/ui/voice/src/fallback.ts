export class UtteranceAudio {
  private readonly pending: ({ samples?: Float32Array; length: number } | null)[] = [];
  private chunks: Float32Array[] = [];
  private queuedSamples = 0;
  private samples = 0;
  private overflow = false;
  constructor(readonly sampleRate: number) {}
  push(samples: Float32Array): void {
    // Bound both the worker backlog and the current utterance; never decode a truncated tail.
    this.queuedSamples += samples.length;
    this.pending.push({
      length: samples.length,
      samples: this.queuedSamples <= this.sampleRate * 12 ? samples.slice() : undefined,
    });
  }
  flush(): void {
    this.pending.push(null);
  }
  acknowledge(final: boolean): Float32Array | undefined {
    const frame = this.pending.shift();
    if (frame) {
      this.queuedSamples -= frame.length;
      this.samples += frame.length;
      if (frame.samples && this.samples <= this.sampleRate * 12) this.chunks.push(frame.samples);
      else this.overflow = true;
    }
    if (!final) return undefined;
    let result: Float32Array | undefined;
    if (!this.overflow && this.samples) {
      result = new Float32Array(this.samples);
      let offset = 0;
      for (const chunk of this.chunks) {
        result.set(chunk, offset);
        offset += chunk.length;
      }
    }
    this.chunks = [];
    this.samples = 0;
    this.overflow = false;
    this.queuedSamples = this.pending.reduce((sum, p) => sum + (p?.length ?? 0), 0);
    return result;
  }
}

export class SpeechFallback {
  private version = 0;
  private request?: AbortController;
  get pending(): boolean {
    return !!this.request;
  }
  cancel(): void {
    this.version++;
    this.request?.abort();
    this.request = undefined;
  }
  async run(
    samples: Float32Array,
    sampleRate: number,
    deliver: (text: string) => void,
    status: (text: string) => void,
    context: 'general' | 'promotion' | 'coordinates' = 'general',
    local?: {
      recognize: (signal: AbortSignal) => Promise<string | undefined>;
      accept: (text: string) => boolean;
    },
  ): Promise<void> {
    this.cancel();
    const version = this.version;
    const request = (this.request = new AbortController());
    const timeout = setTimeout(() => request.abort(), 8000);
    status('Đang nhận dạng lại…');
    try {
      if (local) {
        const text = await local.recognize(request.signal).catch(() => undefined);
        if (version !== this.version || request.signal.aborted) return;
        if (text && local.accept(text)) return;
      }
      if (request.signal.aborted) return;
      const response = await fetch('/voice-asr/transcribe', {
        method: 'POST',
        signal: request.signal,
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/octet-stream',
          'X-Voice-ASR': '1',
          'X-Sample-Rate': String(sampleRate),
          'X-Voice-Context': context,
        },
        body: samples.slice().buffer,
      });
      if (!response.ok) throw new Error(String(response.status));
      const result = await response.json();
      if (version !== this.version || request.signal.aborted) return;
      if (
        result.speech === true &&
        typeof result.text === 'string' &&
        result.text.length &&
        result.text.length < 512
      )
        deliver(result.text);
      else status('Chưa nghe rõ lời nói. Hãy nói lại.');
    } catch {
      if (version === this.version) status('Chưa nhận dạng được. Hãy nói lại hoặc nhập nước bằng chuột.');
    } finally {
      clearTimeout(timeout);
      if (this.request === request) this.request = undefined;
    }
  }
}
