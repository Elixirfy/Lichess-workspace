package lila.aiCoach

import chess.eval.{ Score, WhiteScore }
import chess.format.pgn.SanStr
import chess.{ Centis, Color, Division, Ply }

import lila.tree.{ Analysis, Engine, Eval, Info }

class GameFactsTest extends munit.FunSuite:

  private val sans = "e4 e5 Nf3 Nc6 Bc4 Nd4 Nxe5 Qg5 Nxf7 Qxg2".split(' ').toVector.map(SanStr(_))

  // Stockfish eval after each ply, White's view. Variations exist only on judged moves, as in lila.
  private def info(ply: Int, cp: Int, line: String = "") =
    Info(
      Ply(ply),
      Eval(WhiteScore.fromWhite(Score.cp(cp)).some, None),
      line.split(' ').toList.filter(_.nonEmpty).map(SanStr(_))
    )

  private val infos = List(
    info(1, 30),
    info(2, 30),
    info(3, 25),
    info(4, 25),
    info(5, 20),
    info(6, 20),
    info(7, -100, "O-O Nf6"), // 4. Nxe5: White's mistake
    info(8, 600, "Qe7 Nf3 Qxe4+"), // 4... Qg5: Black's blunder
    info(9, 650),
    info(10, 700)
  )

  private val initial = chess.Position(chess.variant.Standard, Option.empty[chess.format.Fen.Full])

  private def input(winner: Option[Color] = Color.white.some, analysed: List[Info] = infos) =
    GameFacts.Input(
      start = initial,
      sans = sans,
      startedAtPly = Ply.initial,
      student = Color.black,
      winner = winner,
      analysis = Analysis(
        Analysis.Id.Game(GameId("abcdefgh")),
        None,
        analysed,
        Ply.initial,
        nowInstant,
        Engine.default
      ),
      division = Division(Ply(5).some, None, Ply(10)),
      clocks = Vector.tabulate(10)(i => Centis(18000 - i * 100)),
      header = List("Result: White won (resignation).")
    )

  private lazy val brief = GameFacts.brief(input())

  test("move labels"):
    assertEquals(GameFacts.moveLabel(Ply.initial, sans, Ply(1)), "1. e4".some)
    assertEquals(GameFacts.moveLabel(Ply.initial, sans, Ply(8)), "4... Qg5".some)
    assertEquals(GameFacts.moveLabel(Ply.initial, sans, Ply(11)), None)

  test("every move with its eval and clock"):
    assert(brief.contains("\n1. e4 +0.30 (3:00)\n"), brief)
    assert(brief.contains("\n1... e5 +0.30 (2:59)\n"), brief)
    assert(brief.contains("\n5... Qxg2 [queen takes pawn; material White +1] +7.00 (2:51)"), brief)

  test("captures: what was taken and the material after it"):
    assert(brief.contains("\n4. Nxe5 [knight takes pawn; material White +1] -1.00"), brief)
    assert(brief.contains("\n5. Nxf7 [knight takes pawn; material White +2] +6.50"), brief)
    assert(brief.contains("\n4... Qg5 +6.00"), brief) // no capture, no note
    assert(brief.contains("Material at the end: White +1."), brief)

  test("a promotion, from a set-up position"):
    val fen = chess.format.Fen.Full("k7/7P/8/8/8/8/8/K7 w - - 0 1")
    val promo = GameFacts.brief(
      input(analysed = List(info(1, 900))).copy(
        start = chess.Position(chess.variant.FromPosition, fen.some),
        sans = Vector(SanStr("h8=Q+")),
        clocks = Vector.empty
      )
    )
    assert(promo.contains("\n1. h8=Q+ [pawn promotes to queen; material White +9] +9.00"), promo)

  test("moves that do not replay: no capture notes, the rest of the brief stays"):
    val broken = GameFacts.brief(input().copy(sans = sans.updated(6, SanStr("Nxe7"))))
    assert(!broken.contains("[knight takes") && !broken.contains("[queen takes"), broken)
    assert(broken.contains("\n4. Nxe7 -1.00 (2:54) | Mistake."), broken)

  test("judged moves carry winning chances and the numbered Stockfish line with its captures"):
    assert(
      brief.contains(
        "4... Qg5 +6.00 (2:53) | Blunder. Black's winning chances 59% → 10%. Best: Qe7. Stockfish line: 4... Qe7 5. Nf3 Qxe4+ [queen takes pawn; material equal]."
      ),
      brief
    )
    assert(brief.contains("(2:54) | Mistake. White's winning chances 52% → 41%."), brief)
    assert(brief.contains("Stockfish line: 4. O-O Nf6."), brief)

  test("costliest moves per side"):
    assert(
      brief.contains(
        "Student's costliest moves (largest drop in their winning chances):\n- 4... Qg5 (Blunder, 59% → 10%)"
      ),
      brief
    )
    assert(brief.contains("Opponent's costliest moves:\n- 4. Nxe5 (Mistake, 52% → 41%)"), brief)

  test("judgment counts, phases and header"):
    assert(
      brief.contains(
        "Judged moves: White 0 inaccuracies, 1 mistake, 0 blunders; Black 0 inaccuracies, 0 mistakes, 1 blunder."
      ),
      brief
    )
    assert(brief.contains("Phases: middlegame from move 3."), brief)
    assert(
      brief.contains(
        "The student played Black; the opponent played White. The student lost the game.\nResult: White won (resignation)."
      ),
      brief
    )
    assert(GameFacts.brief(input(winner = Color.black.some)).contains("White. The student won the game."))
    assert(GameFacts.brief(input(winner = None)).contains("White. The game was drawn."))

  test("decisive moment: the move after which the winner never dropped below 80%"):
    assert(brief.contains("Decisive moment: 4... Qg5 (Black's decisive mistake)."), brief)

  test("draws and games that were never decided"):
    assert(GameFacts.brief(input(winner = None)).contains("Decisive moment: none, the game was drawn."))
    val blackWins = GameFacts.brief(input(winner = Color.black.some))
    assert(
      blackWins.contains("Decisive moment: none, Stockfish never gave Black a lasting 80% winning chance.")
    )

  test("a side without judged moves"):
    val clean =
      GameFacts.brief(input(analysed = infos.map(i => if i.ply == Ply(7) then i.dropVariation else i)))
    assert(clean.contains("Opponent's costliest moves:\n- none: Stockfish found no inaccuracy"), clean)

  // lila stores a checkmate position as a game-over score, as fishnet reports it ("mate 0")
  private def mated(ply: Int) = Info(Ply(ply), Eval(WhiteScore(Score.mated, Ply(ply).turn).some, None), Nil)

  test("checkmate by Black: no eval on the mating move, Black decided the game with it"):
    val mate = GameFacts.brief(input(winner = Color.black.some, analysed = infos.take(9) :+ mated(10)))
    assert(mate.contains("\n5... Qxg2 [queen takes pawn; material White +1] (2:51)"), mate)
    assert(mate.contains("Decisive moment: 5... Qxg2 (Black's winning move)."), mate)

  test("checkmate by White: no eval on the mating move"):
    val mate = GameFacts.brief(
      input(analysed = infos.take(8) :+ mated(9)).copy(sans = sans.take(9))
    )
    assert(mate.contains("\n5. Nxf7 [knight takes pawn; material White +2] (2:52)"), mate)
    assert(!mate.contains("?"), mate)
    assert(mate.contains("Decisive moment: 4... Qg5 (Black's decisive mistake)."), mate)

  test("moves without an eval are flagged"):
    assert(GameFacts.brief(input(analysed = infos.take(8))).contains("(2 moves have no Stockfish evaluation"))
