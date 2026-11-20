package lila.aiCoach

import chess.eval.WinPercent
import chess.format.pgn.SanStr
import chess.{ Centis, Color, Division, Ply }

import lila.analyse.AccuracyPercent
import lila.tree.{ Advice, Analysis, Info }

/** Stockfish facts about one finished game, rendered as a plain-text brief for the coach. Pure: every number
  * comes from lila's server analysis; nothing is estimated here.
  */
object GameFacts:

  /** The winner keeps at least these winning chances from the decisive move to the end. */
  private val decidedWinPercent = 80d

  case class Input(
      start: chess.Position, // before the first move: variant and initial position
      sans: Vector[SanStr],
      startedAtPly: Ply,
      student: Color,
      winner: Option[Color],
      analysis: Analysis,
      division: Division,
      clocks: Vector[Centis], // empty when the game had no clock
      header: List[String] // result, time control, opening, ratings
  ):
    def label(ply: Ply): String = moveLabel(startedAtPly, sans, ply) | s"ply ${ply.value}"

    /** The mainline moves, replayed: what each one captured and the material after it. Empty if a move does
      * not replay, so the brief then just has no capture notes.
      */
    lazy val played: Vector[chess.MoveOrDrop] =
      start.play(sans.toList, startedAtPly)(_.move).fold(_ => Vector.empty, _.toVector)

    /** The position before the move that leads to `ply`. */
    def before(ply: Ply): Option[chess.Position] =
      val i = ply.value - startedAtPly.value - 1
      if i == 0 then start.some else played.lift(i - 1).map(_.after)

  /** "12... Nxe4" for the mainline move that leads to `ply`. */
  def moveLabel(startedAtPly: Ply, sans: Vector[SanStr], ply: Ply): Option[String] =
    sans.lift(ply.value - startedAtPly.value - 1).map(san => s"${number(ply)} $san")

  def brief(in: Input): String =
    import in.*
    val infos = analysis.infos.mapBy(_.ply)
    val advices = analysis.advices.mapBy(_.ply)
    val clockOffset = startedAtPly.turn.fold(0, 1) // same indexing as the PGN export
    val moves = sans.indices.map: i =>
      val ply = Ply(startedAtPly.value + i + 1)
      val note = played.lift(i).flatMap(moveNote).so(n => s" $n")
      val eval = infos.get(ply).flatMap(showEval).so(e => s" $e")
      val clock = clocks.lift(i - clockOffset).so(c => s" (${showClock(c)})")
      val judged = advices.get(ply).so(a => s" | ${showAdvice(in, a)}")
      s"${label(ply)}$note$eval$clock$judged"
    val lines = List(
      "GAME FACTS (Stockfish, lichess server analysis)",
      s"The student played ${name(student)}; the opponent played ${name(!student)}. ${outcome(in)}"
    ) ::: header ::: List(
      accuracy(in),
      phases(division),
      counts(analysis),
      decisive(in),
      "Student's costliest moves (largest drop in their winning chances):",
      costliest(in, student),
      "Opponent's costliest moves:",
      costliest(in, !student),
      s"Material at the end: ${material(played.lastOption.fold(start)(_.after))}.",
      "",
      "MOVES",
      "Each line: move, Stockfish eval after it in pawns from White's side (+ favours White; #N: White mates in N; #-N: Black mates in N), clock left after the move.",
      "A capture or promotion adds what it took and the material after it, in pawns (queen 9, rook 5, bishop 3, knight 3, pawn 1): [bishop takes knight; material Black +3].",
      "Judged moves add: the judgment, the mover's winning chances before → after the move (before: what Stockfish's best move keeps), Stockfish's best move and line from the position before the move."
    ) ::: moves.toList ::: unanalysed(in).toList
    lines.mkString("\n")

  private def outcome(in: Input): String =
    in.winner.fold("The game was drawn."): winner =>
      if winner == in.student then "The student won the game." else "The student lost the game."

  /** "[bishop takes knight; material Black +3]" for a capture or a promotion. */
  private def moveNote(m: chess.MoveOrDrop): Option[String] = m match
    case m: chess.Move =>
      val taken = m.capture.flatMap(m.before.board.roleAt).map(role => s" takes ${role.name}")
      val promotion = m.promotion.map(role => s"${taken.so(_ => " and")} promotes to ${role.name}")
      (taken.isDefined || promotion.isDefined).option:
        s"[${m.piece.role.name}${~taken}${~promotion}; material ${material(m.after)}]"
    case _ => None

  /** "equal" or "Black +3", in pawns. */
  private def material(position: chess.Position): String =
    val balance = position.materialImbalance
    if balance == 0 then "equal" else s"${name(Color.fromWhite(balance > 0))} +${balance.abs}"

  /** Move number prefix for the move that leads to `ply`: "12." or "12...". */
  private def number(ply: Ply): String =
    val before = ply - 1
    s"${before.fullMoveNumber}${before.turn.fold(".", "...")}"

  private def name(color: Color) = color.fold("White", "Black")

  private def percent(d: Double) = s"${Math.round(d)}%"

  /** None for a checkmate position: the SAN of its move already ends with #. */
  private def showEval(info: Info): Option[String] =
    if info.eval.isGameOver then None
    else
      info.cp
        .map(cp => "%+.2f".formatLocal(java.util.Locale.ROOT, cp.centipawns / 100d))
        .orElse(info.mate.map(m => s"#${m.value}"))

  private def showClock(c: Centis): String =
    val s = c.roundSeconds.value
    "%d:%02d".format(s / 60, s % 60)

  /** Winning chances (0-100) of `color` in the position after `info`. */
  private def winPercent(info: Info, color: Color): Option[Double] =
    info.eval.forceAsCp.map: cp =>
      val white = WinPercent.fromCentiPawns(cp).value
      color.fold(white, 100 - white)

  private def chances(a: Advice): Option[(Double, Double)] =
    (winPercent(a.prev, a.color), winPercent(a.info, a.color)).tupled

  private def showAdvice(in: Input, a: Advice): String =
    // makeComment: "Blunder. Nf6 was best." or "Checkmate is now unavoidable. Nf6 was best."
    val kind = a.makeComment(withEval = false).value.takeWhile(_ != '.')
    val judgment = if kind == a.judgment.name then kind else s"${a.judgment.name} ($kind)"
    val swing = chances(a).so: (before, after) =>
      s" ${name(a.color)}'s winning chances ${percent(before)} → ${percent(after)}."
    val best = a.info.variation.headOption.so: san =>
      val notes = in
        .before(a.ply)
        .flatMap(_.play(a.info.variation, a.ply - 1)(_.move).toOption)
        .so(_.map(moveNote))
      s" Best: $san. Stockfish line: ${numberedLine(a.ply, a.info.variation, notes)}."
    s"$judgment.$swing$best"

  /** Numbers a Stockfish line whose first move replaces the move leading to `firstPly`, with the capture
    * notes of its moves when the line replays.
    */
  private def numberedLine(firstPly: Ply, line: List[SanStr], notes: List[Option[String]]): String =
    line.zipWithIndex
      .map: (san, i) =>
        val ply = Ply(firstPly.value + i)
        val move = if i == 0 || (ply - 1).turn.white then s"${number(ply)} $san" else san.value
        notes.lift(i).flatten.fold(move)(note => s"$move $note")
      .mkString(" ")

  private def accuracy(in: Input): String =
    AccuracyPercent
      .gameAccuracy(in.startedAtPly.turn, in.analysis)
      .fold("Accuracy: not available."): acc =>
        val phases = studentPhaseAccuracy(in).so(p => s" Student's accuracy by phase: $p.")
        s"Accuracy (0-100): White ${acc.white.toInt}%, Black ${acc.black.toInt}%.$phases"

  private def studentPhaseAccuracy(in: Input): Option[String] =
    val byPhase = AccuracyPercent.phaseAccuracies(in.division, in.analysis)(in.student)
    List[lila.analyse.GamePhase]("opening", "middlegame", "endgame")
      .flatMap(phase => byPhase.get(phase).map(acc => s"$phase ${acc.toInt}%"))
      .mkString(", ")
      .nonEmptyOption

  private def phases(division: Division): String =
    List(
      division.middle.map(p => s"middlegame from move ${p.fullMoveNumber}"),
      division.end.map(p => s"endgame from move ${p.fullMoveNumber}")
    ).flatten match
      case Nil => "Phases: the game never left the opening."
      case ps => s"Phases: ${ps.mkString(", ")}."

  private def counts(analysis: Analysis): String =
    analysis.summary
      .map: (color, judgments) =>
        val bits = judgments.map: (j, n) =>
          val word = j.name.toLowerCase
          s"$n ${if n == 1 then word else if word.endsWith("y") then s"${word.init}ies" else s"${word}s"}"
        s"${name(color)} ${bits.mkString(", ")}"
      .mkString("Judged moves: ", "; ", ".")

  /** First move after which the winner keeps `decidedWinPercent` until the end. */
  private def decisive(in: Input): String =
    in.winner.fold("Decisive moment: none, the game was drawn."): winner =>
      val decidedFrom = in.analysis.infosWithInitial.reverse
        .dropWhile(_.eval.forceAsCp.isEmpty) // a final mate position may have no eval
        .takeWhile(winPercent(_, winner).exists(_ >= decidedWinPercent))
        .lastOption
        .map(_.ply)
        .filter(_ > in.startedAtPly)
      decidedFrom.fold(
        s"Decisive moment: none, Stockfish never gave ${name(winner)} a lasting ${decidedWinPercent.toInt}% winning chance."
      ): ply =>
        val mover = (ply - 1).turn
        val kind = if mover == winner then "winning move" else "decisive mistake"
        s"Decisive moment: ${in.label(ply)} (${name(mover)}'s $kind). From then on Stockfish gave ${name(winner)} at least ${decidedWinPercent.toInt}% winning chances until the end."

  private def costliest(in: Input, color: Color): String =
    in.analysis.advices
      .filter(_.color == color)
      .sortBy(a => chances(a).fold(0d)((before, after) => after - before))
      .take(3)
      .map: a =>
        val swing = chances(a).so((before, after) => s", ${percent(before)} → ${percent(after)}")
        s"- ${in.label(a.ply)} (${a.judgment.name}$swing)"
      .mkString("\n")
      .nonEmptyOption | "- none: Stockfish found no inaccuracy, mistake or blunder."

  private def unanalysed(in: Input): Option[String] =
    val missing = in.sans.size - in.analysis.infos.count(!_.isEmpty)
    (missing > 0).option(s"($missing moves have no Stockfish evaluation; say so if asked about them.)")
