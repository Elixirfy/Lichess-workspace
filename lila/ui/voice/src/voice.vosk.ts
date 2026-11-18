import {
  type KaldiRecognizer,
  VoskClient,
  type ServerMessageResult,
  type ServerMessagePartialResult,
} from '@lichess-org/vosk-browser';

import { UtteranceAudio } from './fallback';
import type { RecognizerOpts, VoskModule } from './interfaces';
import { type Selectable, Switch } from './switch';

const LOG_LEVEL = -1; // -1 errors only. 0 includes warnings, 3 is just insane

export function initModule(): VoskModule {
  const recs = new Switch<string, KaldiRec>();
  let voskClient: VoskClient | undefined;
  let lang: string;
  let modelVersion = 0;
  const retries = new Set<() => void>();

  return {
    initModel,
    initRecognizer,
    isLoaded,
    select,
    transcribe,
  };

  async function initModel(url: string, language: string): Promise<void> {
    const version = ++modelVersion;
    for (const cancel of retries) cancel();
    voskClient?.terminate();
    voskClient = undefined;
    recs.remove();
    const client = new VoskClient({
      modelUrl: url,
      workerUrl: site.asset.url('npm/vosk/vosk.worker.js'),
      wasmUrl: site.asset.url('npm/vosk/vosk.wasm'),
      logLevel: LOG_LEVEL,
    });
    // The upstream convenience factory listens only for 'load', leaving worker
    // 'error' messages (for example a corrupt archive) pending indefinitely.
    let timeout: ReturnType<typeof setTimeout> | undefined;
    try {
      await new Promise<void>((resolve, reject) => {
        timeout = setTimeout(() => reject(new Error('Vosk model load timed out')), 30000);
        client.on('load', message => {
          if ('result' in message && message.result) resolve();
          else reject(new Error('Vosk model could not be loaded'));
        });
        client.on('error', message => {
          reject(new Error(('error' in message && message.error) || 'Invalid Vosk model'));
        });
      });
    } catch (error) {
      client.terminate();
      throw error;
    } finally {
      clearTimeout(timeout);
    }
    if (version !== modelVersion) {
      client.terminate();
      return;
    }
    voskClient = client;
    lang = language;
  }

  function initRecognizer(opts: RecognizerOpts): AudioNode | undefined {
    if (!opts.words?.length || !voskClient) {
      recs.remove(opts.recId);
      return undefined;
    }
    const kaldi = new voskClient.KaldiRecognizer(opts.audioCtx.sampleRate, JSON.stringify(opts.words));

    // buffer size under 100ms for timely partial results, 200ms for full results
    const bufSize = 2 ** Math.ceil(Math.log2(opts.audioCtx.sampleRate / (opts.partial ? 16 : 8)));

    // fun fact - createScriptProcessor was deprecated in 2014
    const node = opts.audioCtx.createScriptProcessor(bufSize, 1, 1);
    const audio = opts.audioResult ? new UtteranceAudio(opts.audioCtx.sampleRate) : undefined;
    if (opts.partial)
      kaldi.on('partialresult', (msg: ServerMessagePartialResult) => {
        if (recs.items.get(opts.recId)?.kaldi !== kaldi) return;
        if (msg.result.partial.length > 0) opts.broadcast(msg.result.partial, 'partial', 0);
      });
    else
      kaldi.on('partialresult', () => {
        if (recs.items.get(opts.recId)?.kaldi !== kaldi) return;
        audio?.acknowledge(false);
      });
    kaldi.on('result', (msg: ServerMessageResult) => {
      if (recs.items.get(opts.recId)?.kaldi !== kaldi || opts.partial) return;
      const samples = audio?.acknowledge(true);
      if (samples) opts.audioResult?.(msg.result.text, samples, opts.audioCtx.sampleRate);
      else if (msg.result.text.length > 0) opts.broadcast(msg.result.text, 'full', 3000);
    });

    if (LOG_LEVEL >= -1)
      console.info(
        `Created ${opts.audioCtx.sampleRate.toFixed(0)}Hz recognizer '${
          opts.recId
        }' with buffer size ${bufSize}`,
        opts.words,
      );

    // Switch.add closes the selected entry; inactive recognizers also need disposal.
    if (recs.key !== opts.recId) recs.remove(opts.recId);
    recs.add(opts.recId, new KaldiRec(kaldi, node, opts.partial, audio));
    return node;
  }

  function isLoaded(language?: string): boolean {
    return voskClient !== undefined && (!language || language === lang);
  }

  function transcribe(
    samples: Float32Array,
    sampleRate: number,
    phrases: string[],
    signal: AbortSignal,
  ): Promise<string | undefined> {
    if (!voskClient || signal.aborted || !phrases.length || samples.length > sampleRate * 12)
      return Promise.resolve(undefined);
    // A separate recognizer never switches the live audio graph or its listeners.
    // Vosk's grammar is a word loop, so accept only an entire generated phrase.
    return new Promise(resolve => {
      const kaldi = new voskClient!.KaldiRecognizer(sampleRate, JSON.stringify(phrases));
      const parts: string[] = [];
      let replies = 0;
      let finished = false;
      const cancel = () => finish();
      const finish = (text?: string) => {
        if (finished) return;
        finished = true;
        clearTimeout(timeout);
        signal.removeEventListener('abort', cancel);
        retries.delete(cancel);
        kaldi.remove();
        resolve(text);
      };
      const timeout = setTimeout(cancel, 2000);
      signal.addEventListener('abort', cancel, { once: true });
      retries.add(cancel);
      const acknowledge = (text = '') => {
        if (finished) return;
        if (text) parts.push(text);
        if (++replies !== 2) return;
        const full = parts.join(' ').trim();
        finish(phrases.includes(full) && full.split(' ').length >= 4 ? full : undefined);
      };
      kaldi.on('partialresult', () => acknowledge());
      kaldi.on('result', (msg: ServerMessageResult) => acknowledge(msg.result.text));
      try {
        kaldi.acceptWaveformFloat(samples, sampleRate);
        kaldi.retrieveFinalResult();
      } catch {
        finish();
      }
    });
  }

  function select(recId: string | false): void {
    recs.set(recId);
  }
}

class KaldiRec implements Selectable {
  kaldi: KaldiRecognizer;
  node: ScriptProcessorNode;
  partial: boolean;

  constructor(
    kaldi: KaldiRecognizer,
    node: ScriptProcessorNode,
    partial: boolean,
    private readonly audio?: UtteranceAudio,
  ) {
    this.kaldi = kaldi;
    this.node = node;
    this.partial = partial;
  }
  select() {
    if (this.node.onaudioprocess) return;
    this.node.onaudioprocess = e => {
      this.audio?.push(e.inputBuffer.getChannelData(0));
      this.kaldi.acceptWaveform(e.inputBuffer);
    };
  }
  deselect() {
    if (!this.node.onaudioprocess) return;
    this.audio?.flush();
    this.kaldi.retrieveFinalResult(); // flush lattice
    this.node.onaudioprocess = null;
  }
  close() {
    this.deselect();
    this.kaldi.remove();
  }
}
