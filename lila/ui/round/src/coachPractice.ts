import { Chess, castlingSide, normalizeMove } from 'chessops/chess';
import { chessgroundDests } from 'chessops/compat';
import { makeFen, parseFen } from 'chessops/fen';
import { makeSanAndPlay, parseSan } from 'chessops/san';
import type { NormalMove } from 'chessops/types';
import { kingCastlesTo, makeSquare, makeUci, parseSquare, parseUci } from 'chessops/util';

import { practiceFeedback } from './coachPracticeFeedback';

export interface PracticeLine {
  moves: { san: string; uci: string }[];
  text: string;
}

export interface PracticePosition {
  version?: number;
  fen: string;
  prompt: string;
  played: PracticeLine;
  alternatives: PracticeLine[];
}

const promotionRoles = { q: 'hậu', r: 'xe', b: 'tượng', n: 'mã' } as const;
type Promotion = keyof typeof promotionRoles;

interface PracticeStep {
  position: Chess;
  san: string;
  lastMove: Key[];
  line?: PracticeLine;
  feedback: string;
  capture?: NormalMove;
  foundAlternative: boolean;
}

export default class CoachPractice {
  readonly initial: Chess;
  promotion?: string;
  ground?: CgApi;
  private steps: PracticeStep[] = [];
  private inputError?: string;

  constructor(
    readonly cardId: string,
    readonly data: PracticePosition,
    readonly redraw: Redraw,
  ) {
    this.initial = Chess.fromSetup(parseFen(data.fen).unwrap()).unwrap();
  }

  private get current(): PracticeStep | undefined {
    return this.steps[this.steps.length - 1];
  }

  get position(): Chess {
    return this.current?.position ?? this.initial;
  }

  get feedback(): string | undefined {
    return this.inputError ?? this.current?.feedback;
  }

  get foundAlternative(): boolean {
    return !this.inputError && !!this.current?.foundAlternative;
  }

  get capture(): NormalMove | undefined {
    return this.current?.capture;
  }

  get moveHistory(): string[] {
    return this.steps.map(step => step.san);
  }

  get ended(): boolean {
    return this.position.isEnd() || this.position.halfmoves >= 100;
  }

  get canUndo(): boolean {
    return this.steps.length > 0 || !!this.promotion;
  }

  get inSolution(): boolean {
    return (this.current?.line?.moves.length ?? 0) > 2;
  }

  get canFollowSolution(): boolean {
    return !!this.solutionMove;
  }

  private get solutionMove(): PracticeLine['moves'][number] | undefined {
    return this.inSolution && !this.ended ? this.current?.line?.moves[this.steps.length] : undefined;
  }

  get fen(): string {
    return makeFen(this.position.toSetup());
  }

  get promotionOptions(): [Promotion, string][] {
    return this.promotion ? (Object.entries(promotionRoles) as [Promotion, string][]) : [];
  }

  config(): CgConfig {
    const canMove = !this.ended && !this.promotion;
    return {
      fen: this.fen,
      orientation: this.initial.turn,
      turnColor: this.position.turn,
      check: this.position.isCheck(),
      lastMove: this.current?.lastMove ?? [],
      movable: {
        free: false,
        color: canMove ? this.position.turn : undefined,
        dests: canMove ? chessgroundDests(this.position) : new Map(),
        events: { after: (from, to) => this.playSquares(from, to) },
      },
      premovable: { enabled: false },
      drawable: { enabled: false },
    };
  }

  private playSquares(from: Key, to: Key) {
    const square = parseSquare(from);
    const piece = square === undefined ? undefined : this.position.board.get(square);
    if (piece?.role === 'pawn' && (to.endsWith('1') || to.endsWith('8'))) {
      this.promotion = from + to;
      this.redraw();
    } else this.play(from + to);
  }

  promote(role: Promotion): void {
    if (this.promotion) this.play(this.promotion + role);
  }

  play(input: string): void {
    this.promotion = undefined;
    const notation = input.replace(/\s/g, '');
    const parsed = parseUci(notation) ?? parseSan(this.position, notation);
    if (this.ended || !parsed || !('from' in parsed) || !this.position.isLegal(parsed)) {
      this.inputError = 'Nước này không hợp lệ ở thế đang luyện.';
      this.redraw();
      return;
    }
    this.advance(parsed);
  }

  private advance(move: NormalMove, shownCapture = false): void {
    const before = this.position;
    const index = this.steps.length;
    const candidates = index ? [this.current?.line] : [this.data.played, ...this.data.alternatives];
    const uci = makeUci(normalizeMove(before, move));
    const line = candidates.find(candidate => {
      const step = candidate?.moves[index];
      const expected = step && parseUci(step.uci);
      return expected && makeUci(normalizeMove(before, expected)) === uci;
    });
    const opening = index === 0 ? line : undefined;
    const text = opening ? this.lineText(opening) : shownCapture ? this.current?.feedback : undefined;
    this.steps.push(this.makeStep(before, move, line, text, !!opening && opening !== this.data.played));
    this.promotion = this.inputError = undefined;
    this.redraw();
  }

  showCapture(): void {
    if (this.capture && !this.ended) this.advance(this.capture, true);
  }

  followSolution(): void {
    const move = this.solutionMove;
    if (move) this.play(move.uci);
  }

  undo(): void {
    if (!this.promotion) this.steps.pop();
    this.promotion = this.inputError = undefined;
    this.redraw();
  }

  show(line: PracticeLine): void {
    const steps: PracticeStep[] = [];
    let position = this.initial;
    for (const step of line === this.data.played ? line.moves : line.moves.slice(0, 1)) {
      const move = parseUci(step.uci);
      if (!move || !('from' in move) || !position.isLegal(move)) return;
      const next = this.makeStep(position, move, line, this.lineText(line));
      steps.push(next);
      position = next.position;
    }
    this.steps = steps;
    this.promotion = this.inputError = undefined;
    this.redraw();
  }

  private makeStep(
    before: Chess,
    move: NormalMove,
    line?: PracticeLine,
    text?: string,
    foundAlternative = false,
  ): PracticeStep {
    const position = before.clone();
    const san = makeSanAndPlay(position, move);
    const castle = castlingSide(before, move);
    const to = castle ? kingCastlesTo(before.turn, castle) : move.to;
    const feedback: ReturnType<typeof practiceFeedback> =
      text === undefined || position.isEnd() || position.halfmoves >= 100
        ? practiceFeedback(before, move, position, this.initial.turn)
        : { text };
    return {
      position,
      san,
      lastMove: [makeSquare(move.from), makeSquare(to)],
      line,
      feedback: feedback.text,
      capture: feedback.capture,
      foundAlternative,
    };
  }

  private lineText(line: PracticeLine): string {
    // Existing exercise cards can still contain the previous reply narration.
    return line.text.split(' Trong biến Stockfish tìm được,')[0];
  }

  reset(): void {
    this.steps = [];
    this.promotion = this.inputError = undefined;
    this.redraw();
  }
}
