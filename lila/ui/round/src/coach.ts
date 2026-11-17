import { randomId } from 'lib/algo';
import * as xhr from 'lib/xhr';

export type QuestionKind = 'hint' | 'explain' | 'threat';
export interface CoachCard {
  id: string;
  kind: QuestionKind | 'analyseMove';
  scope: 'live' | 'history';
  positionRevision: string;
  validForStatus: string;
  ply: number;
  moveLabel: string;
  hintLevel: number;
  text: string;
  highlights: string[];
  moves: { san: string; uci: string }[];
}
export interface CoachSummary {
  state: 'pending' | 'ready' | 'partial' | 'failed';
  positionRevision: string;
  status: string;
  reason: 'finished' | 'abandoned';
  coverage: { analysed: number; failed: number; total: number };
  moments: CoachCard[];
  advice?: string | null;
  message: string;
}
export interface CoachSnapshot {
  sessionId: string;
  gameId: string;
  learnerColor: Color;
  support: 'proactive' | 'onDemand';
  phase: string;
  positionRevision: string;
  ply: number;
  status: string;
  hintLevel: number;
  cursor: number;
  capabilities: Record<QuestionKind, boolean>;
  cards: CoachCard[];
  summary?: CoachSummary | null;
  coverage: { analysed: number; failed: number; total: number };
  questions: {
    taskId: string;
    kind: QuestionKind;
    positionRevision: string;
    hintLevel: number;
    state: string;
  }[];
}
interface Request {
  kind: QuestionKind;
  expectedRevision: string;
  requestKey: string;
  live: boolean;
}
export interface CoachPosition {
  ply: number;
  viewedPly: number;
  status: string;
  live: boolean;
}
export interface CoachTransport {
  get<T>(url: string): Promise<T>;
  post(url: string, body: Request | Record<string, never>): Promise<{ status: number; taskId?: string }>;
  events(url: string): EventSource;
}
const transport: CoachTransport = {
  get: xhr.json,
  async post(url, body) {
    const response = await xhr.jsonAnyResponse(url, {
      method: 'POST',
      headers: { ...xhr.jsonHeader, ...xhr.xhrHeader, 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await response.json();
    return { status: response.status, taskId: data.taskId };
  },
  events: url => new EventSource(url),
};

// SSE invalidates a snapshot; it never appends a possibly stale card to the DOM.
export default class CoachCtrl {
  snapshot?: CoachSnapshot;
  connection: 'loading' | 'ready' | 'reconnecting' | 'unavailable' = 'loading';
  error?: 'questionError' | 'positionChanged' | 'resumeError';
  retry?: Request;
  posting = false;
  private sessionId?: string;
  private stream?: EventSource;
  private reconnect?: ReturnType<typeof setTimeout>;
  private poll?: ReturnType<typeof setInterval>;
  private loading?: Promise<void>;
  private dirty = false;
  private stopped = false;
  private lastEvent = 0;
  private backoff = 1000;
  private generation = 0;

  constructor(
    readonly gameId: string,
    readonly position: () => CoachPosition,
    readonly redraw: () => void,
    readonly goLive: () => void,
    private readonly io: CoachTransport = transport,
  ) {}

  async start(): Promise<void> {
    await this.refresh();
    if (!this.stopped) this.poll = setInterval(() => void this.refresh(), 5000);
  }

  stop = (): void => {
    this.stopped = true;
    this.generation++;
    this.stream?.close();
    clearTimeout(this.reconnect);
    clearInterval(this.poll);
  };

  matchesPosition(): boolean {
    const s = this.snapshot;
    const p = this.position();
    return !!s && s.ply === p.ply && s.status === p.status;
  }

  get pending(): boolean {
    const s = this.snapshot;
    return (
      this.posting ||
      !!s?.questions.some(
        q =>
          ['pending', 'running'].includes(q.state) &&
          (q.kind === 'explain' || (q.positionRevision === s.positionRevision && s.status === 'started')),
      )
    );
  }

  canAsk(kind: QuestionKind): boolean {
    const s = this.snapshot;
    return (
      !!s &&
      this.connection === 'ready' &&
      this.matchesPosition() &&
      !this.pending &&
      !this.retry &&
      s.capabilities[kind] &&
      !(
        kind === 'hint' &&
        s.hintLevel === 3 &&
        s.cards.some(
          card =>
            card.kind === 'hint' && card.hintLevel === 3 && card.positionRevision === s.positionRevision,
        )
      ) &&
      (kind === 'explain'
        ? ['active', 'finished'].includes(s.phase)
        : s.phase === 'active' && this.position().live)
    );
  }

  visibleCards(): CoachCard[] {
    const s = this.snapshot;
    if (!s) return [];
    const p = this.position();
    return s.cards.filter(card =>
      card.scope === 'history'
        ? card.ply <= p.viewedPly
        : s.phase === 'active' &&
          this.connection === 'ready' &&
          p.live &&
          this.matchesPosition() &&
          s.status === 'started' &&
          card.positionRevision === s.positionRevision &&
          card.validForStatus === s.status,
    );
  }

  currentCard(): CoachCard | undefined {
    const s = this.snapshot;
    if (!s) return undefined;
    const p = this.position();
    const cards = this.visibleCards();
    // A manual answer at the current position takes precedence over automatic
    // analysis that may finish later. Old hints never survive a position change.
    const ownParity = s.learnerColor === 'white' ? 1 : 0;
    const ply = p.viewedPly % 2 === ownParity ? p.viewedPly : p.viewedPly - 1;
    const requested = cards.filter(c => c.scope === 'live' || (c.kind === 'explain' && c.ply === ply));
    if (requested.length) return requested[requested.length - 1];
    if (ply < 1) return undefined;
    const history = cards.filter(c => c.scope === 'history' && c.ply === ply);
    return history[history.length - 1];
  }

  refresh = (): Promise<void> => {
    if (this.stopped) return Promise.resolve();
    if (this.loading) {
      this.dirty = true;
      return this.loading;
    }
    this.loading = (async () => {
      do {
        this.dirty = false;
        await this.load();
      } while (this.dirty && !this.stopped);
    })().finally(() => {
      this.loading = undefined;
    });
    return this.loading;
  };

  private async load(): Promise<void> {
    const generation = this.generation;
    try {
      if (!this.sessionId) {
        const found = await this.io.get<{ sessionId: string }>(`/ai-coach/games/${this.gameId}`);
        if (this.stopped || generation !== this.generation) return;
        this.sessionId = found.sessionId;
      }
      const snapshot = await this.io.get<CoachSnapshot>(`/ai-coach/sessions/${this.sessionId}`);
      if (this.stopped || generation !== this.generation) return;
      if (snapshot.sessionId !== this.sessionId || snapshot.gameId !== this.gameId)
        throw new Error('wrong target');
      // A snapshot started before a newer SSE event needs a second read.
      if (snapshot.cursor < this.lastEvent) {
        return;
      }
      this.snapshot = snapshot;
      if (
        this.retry &&
        (snapshot.phase === 'abandoned' ||
          (this.retry.kind !== 'explain' &&
            (this.retry.expectedRevision !== snapshot.positionRevision || snapshot.status !== 'started')))
      ) {
        this.retry = undefined;
        this.error = 'positionChanged';
      }
      this.connection = 'ready';
      if (!this.stream && !this.reconnect) this.connect(snapshot.cursor);
    } catch {
      if (!this.stopped && generation === this.generation) {
        this.connection = 'unavailable';
        this.stream?.close();
        this.stream = undefined;
        this.scheduleReconnect();
      }
    } finally {
      if (!this.stopped) this.redraw();
    }
  }

  private connect(cursor: number): void {
    if (this.stopped || !this.sessionId) return;
    this.lastEvent = cursor;
    const stream = (this.stream = this.io.events(
      `/ai-coach/sessions/${this.sessionId}/events?cursor=${cursor}`,
    ));
    stream.onopen = () => {
      if (this.stream !== stream || this.stopped) return;
      this.backoff = 1000;
      this.connection = 'ready';
      this.redraw();
    };
    stream.addEventListener('coach', event => {
      if (this.stream !== stream || this.stopped) return;
      const message = event;
      try {
        const data = JSON.parse(message.data);
        const id = Number(message.lastEventId);
        if (data.type === 'reset') {
          this.generation++;
          stream.close();
          this.stream = undefined;
          // Cursor may be ahead of the server after restore. Reset both.
          this.lastEvent = 0;
          this.connection = 'loading';
          void this.refresh();
        } else if (Number.isSafeInteger(id) && id > this.lastEvent) {
          this.lastEvent = id;
          void this.refresh();
        }
      } catch {
        stream.onerror?.(new Event('error'));
      }
    });
    stream.onerror = () => {
      if (this.stream !== stream || this.stopped) return;
      stream.close();
      this.stream = undefined;
      this.connection = 'reconnecting';
      this.scheduleReconnect();
      this.redraw();
    };
  }

  private scheduleReconnect(): void {
    if (this.reconnect || this.stopped) return;
    this.reconnect = setTimeout(() => {
      this.reconnect = undefined;
      void this.refresh();
    }, this.backoff);
    this.backoff = Math.min(this.backoff * 2, 15000);
  }

  resumeLesson = async (): Promise<void> => {
    if (this.posting || !this.sessionId || this.snapshot?.phase !== 'abandoned') return;
    this.posting = true;
    this.error = undefined;
    this.redraw();
    try {
      const result = await this.io.post(`/ai-coach/sessions/${this.sessionId}/resume`, {});
      if (result.status !== 200) this.error = 'resumeError';
    } catch {
      this.error = 'resumeError';
    } finally {
      await this.refresh();
      this.posting = false;
      if (!this.stopped) this.redraw();
    }
  };

  ask = async (kind: QuestionKind): Promise<void> => {
    if (!this.canAsk(kind)) return;
    this.retry = {
      kind,
      expectedRevision: this.snapshot!.positionRevision,
      requestKey: randomId(32),
      live: this.position().live,
    };
    await this.retryQuestion();
  };

  retryQuestion = async (): Promise<void> => {
    if (!this.retry || this.posting || !this.sessionId || this.stopped) return;
    if (this.retry.kind !== 'explain' && (!this.position().live || !this.matchesPosition())) return;
    // Retrying the same key cannot increment the hint level twice.
    const request = this.retry;
    this.posting = true;
    this.error = undefined;
    this.redraw();
    try {
      const result = await this.io.post(`/ai-coach/sessions/${this.sessionId}/questions`, request);
      if (result.status === 202) this.retry = undefined;
      else if (result.status >= 400 && result.status < 500) {
        this.retry = undefined;
        this.error = 'positionChanged';
      } else this.error = 'questionError';
    } catch {
      this.error = 'questionError';
    } finally {
      // Keep buttons locked until the accepted task has been read back.
      await this.refresh();
      this.posting = false;
      if (!this.stopped) this.redraw();
    }
  };
}
