package lila.aiCoach

import chess.format.Fen
import chess.{ Ply, Status }
import play.api.data.Form
import play.api.data.Forms.*
import play.api.libs.json.*
import reactivemongo.api.bson.*

import org.apache.pekko.stream.scaladsl.Source

import lila.common.LilaFuture
import lila.core.config.NetDomain
import lila.core.game.{ Divider, Game }
import lila.db.dsl.{ *, given }
import lila.tree.Analysis

/** Who may ask, what the coach is told, and the stored conversation (one per game and player). */
final class AiCoachApi(
    coll: Coll,
    llm: CoachLlm,
    analyser: lila.analyse.Analyser,
    divider: Divider
)(using Executor, Scheduler, NetDomain):

  import AiCoachApi.*

  private given BSONDocumentHandler[CoachLlm.Usage] = Macros.handler
  private given BSONDocumentHandler[Turn] = Macros.handler
  private given BSONDocumentHandler[Chat] = Macros.handler

  private val markdown =
    lila.markdown.MarkdownRender(autoLink = false, list = true, header = true, table = true)

  /** Only the two players may ask, and only once the game is over. */
  def canAsk(game: Game, userId: UserId): Boolean =
    llm.enabled && game.finished && game.player(userId).isDefined

  /** Whether the server analysis is ready, and the turns so far. */
  def show(game: Game, userId: UserId): Fu[(Boolean, List[Turn])] =
    analysed(game)
      .zip(coll.byId[Chat](chatId(game, userId)))
      .map: (analysis, chat) =>
        (analysis.isDefined, chat.so(_.turns))

  /** Either an error before anything is asked, or the answer as it is written: `{"d": text}` lines, then
    * `{"turn": ...}` once it is stored, or `{"error": ...}`. Nothing about the game is read before the first
    * question; when it has no server analysis yet, that question requests it: `{"status": "analysing"}` comes
    * first, and the answer starts once Stockfish has analysed every move.
    */
  def ask(
      game: Game,
      initialFen: Option[Fen.Full],
      userId: UserId,
      question: String,
      ply: Option[Ply],
      t: CoachText,
      stockfish: Stockfish
  ): Fu[Either[String, Source[JsObject, ?]]] =
    val id = chatId(game, userId)
    coll
      .byId[Chat](id)
      .flatMap: chat =>
        val turns = chat.so(_.turns)
        if turns.sizeIs >= maxTurns then fuccess(Left(t.limited))
        else
          val viewing = ply.flatMap(GameFacts.moveLabel(game.startedAtPly, game.sans, _))
          val history = turns.map(t => CoachPrompt.question(t.q, t.viewing) -> t.a)
          def answer(facts: String) = this.answer(game, id, facts, history, question, ply, viewing, t)
          // the facts are stored with the first turn, so a conversation never sees two versions
          chat.map(_.facts) match
            case Some(stored) => fuccess(Right(answer(stored)))
            case None =>
              facts(game, initialFen, userId).map:
                case Some(facts) => Right(answer(facts))
                case None =>
                  Right:
                    Source.single(Json.obj("status" -> "analysing")) ++
                      Source
                        .futureSource:
                          analyse(game, initialFen, userId, stockfish, t).map:
                            case Right(facts) => answer(facts)
                            case Left(error) => Source.single(Json.obj("error" -> error))
                        .recover:
                          case e: Exception =>
                            logger.warn(s"${game.id} analysis: ${e.getMessage}")
                            Json.obj("error" -> t.unavailableLater)

  def json(turn: Turn): JsObject =
    Json
      .obj("q" -> turn.q, "html" -> markdown("aiCoach")(Markdown(turn.a)).value)
      .add("ply" -> turn.ply)
      .add("viewing" -> turn.viewing)

  private def answer(
      game: Game,
      id: String,
      facts: String,
      history: List[(String, String)],
      question: String,
      ply: Option[Ply],
      viewing: Option[String],
      t: CoachText
  ): Source[JsObject, ?] =
    llm
      .stream(facts, history, CoachPrompt.question(question, viewing))
      .mapAsync(1):
        case CoachLlm.Event.Delta(text) => fuccess(Json.obj("d" -> text))
        case CoachLlm.Event.Done(reply) if reply.text.isEmpty =>
          fuccess(Json.obj("error" -> t.couldNotAnswer))
        case CoachLlm.Event.Done(reply) =>
          val turn = Turn(
            q = question,
            ply = ply.map(_.value),
            viewing = viewing,
            a = reply.text,
            model = reply.model,
            prompt = CoachPrompt.version,
            millis = reply.millis,
            firstMillis = reply.firstMillis.some,
            usage = reply.usage,
            at = nowInstant
          )
          coll.update
            .one(
              bid(id),
              bdoc("$push" -> bdoc("turns" -> turn), "$setOnInsert" -> bdoc("facts" -> facts)),
              upsert = true
            )
            .inject(Json.obj("turn" -> json(turn)))
      .recover:
        case e: Exception =>
          logger.warn(s"${game.id} ${e.getMessage}")
          Json.obj("error" -> t.unavailableLater)

  /** The first question on a game without the server analysis: request it, unless it is already queued (the
    * other player asked first), then wait until it is stored. Left: why there is no analysis to answer from.
    */
  private def analyse(
      game: Game,
      initialFen: Option[Fen.Full],
      userId: UserId,
      stockfish: Stockfish,
      t: CoachText
  ): Fu[Either[String, String]] =
    val start = nowMillis
    stockfish.queued
      .flatMap: queued =>
        if queued then fuccess(Request.Queued) else stockfish.request
      .flatMap:
        case Request.Queued =>
          waitForFacts(game, initialFen, userId, stockfish, start + analysisWait.toMillis).map:
            case Some(facts) =>
              logger.info(s"${game.id} analysed for the coach in ${nowMillis - start} ms")
              Right(facts)
            case None =>
              logger.warn(s"${game.id} no analysis for the coach after ${nowMillis - start} ms")
              Left(t.analysisFailed)
        case Request.Busy => fuccess(Left(t.analysisBusy))
        case Request.Limited => fuccess(Left(t.analysisLimited))
        case Request.Impossible => fuccess(Left(t.analysisImpossible))

  /** Every few seconds until the analysis is stored, its request left the queue without it (fishnet gave up),
    * or the time is up. The analysis is stored before its request leaves the queue.
    */
  private def waitForFacts(
      game: Game,
      initialFen: Option[Fen.Full],
      userId: UserId,
      stockfish: Stockfish,
      until: Long
  ): Fu[Option[String]] =
    LilaFuture.sleep(pollEvery) >> facts(game, initialFen, userId).flatMap:
      case Some(facts) => fuccess(facts.some)
      case None if nowMillis > until => fuccess(none)
      case None =>
        stockfish.queued.flatMap:
          if _ then waitForFacts(game, initialFen, userId, stockfish, until)
          else facts(game, initialFen, userId) // stored between the two reads, or given up

  // by id: the game read before the analysis was requested still says it has none
  private def analysed(game: Game): Fu[Option[Analysis]] =
    analyser.byId(Analysis.Id(game.id)).dmap(_.filter(_.valid))

  private def facts(game: Game, initialFen: Option[Fen.Full], userId: UserId): Fu[Option[String]] =
    analysed(game).dmap: analysis =>
      for
        analysis <- analysis
        student <- game.player(userId).map(_.color)
      yield GameFacts.brief:
        GameFacts.Input(
          start = chess.Position(game.variant, initialFen),
          sans = game.sans,
          startedAtPly = game.startedAtPly,
          student = student,
          winner = game.winnerColor,
          analysis = analysis,
          division = divider(game.id, game.sans, game.variant, initialFen),
          clocks = ~game.bothClockStates,
          header = header(game)
        )

  private def header(game: Game): List[String] =
    val result = game.winnerColor.fold("Result: draw")(c => s"Result: ${c.fold("White", "Black")} won")
    val control = game.clock
      .map(_.config)
      .fold(game.daysPerTurn.fold("unlimited")(d => s"correspondence, ${d.value} days per move")): c =>
        s"${c.show} (${game.speed.name})"
    val players = game.players.mapList: p =>
      val who = p.aiLevel.fold(p.rating.fold("unrated")(_.toString))(level => s"Stockfish level $level")
      s"${p.color.fold("White", "Black")} $who"
    val opening = (game.variant.standard && !game.fromPosition)
      .so(chess.opening.OpeningDb.search(game.sans))
      .map(o => s"Opening: ${o.opening.eco} ${o.opening.name}.")
    List(
      s"$result (${statusText(game.status)}).".some,
      s"Variant: ${game.variant.name}. Time control: $control.".some,
      s"Players: ${players.mkString(", ")}.".some,
      opening
    ).flatten

  private def statusText(status: Status) = status match
    case Status.Mate => "checkmate"
    case Status.Resign => "resignation"
    case Status.Outoftime => "time ran out"
    case Status.Timeout => "the opponent left the game"
    case Status.Stalemate => "stalemate"
    case Status.Draw => "draw"
    case other => other.name

object AiCoachApi:

  val maxTurns = 30

  // how long the first question waits for Stockfish; the analysis goes on after that, for the next question
  private val analysisWait = 4.minutes
  private val pollEvery = 2.seconds

  val form = Form:
    tuple(
      "q" -> lila.common.Form.cleanNonEmptyText(maxLength = 500),
      "ply" -> optional(number(min = 1, max = 2000))
    )

  /** The server analysis of one game, for its first question. It comes from the fishnet module, which this
    * module does not depend on: the app gives it, with the student as the sender of the request.
    */
  trait Stockfish:
    /** Whether a request for the game waits in the queue or is being analysed. */
    def queued: Fu[Boolean]
    def request: Fu[Request]

  enum Request:
    case Queued // or already analysed
    case Busy // the student's other request is still running
    case Limited // daily or weekly limit
    case Impossible // too short, or a variant fishnet does not analyse

  /** One question and answer, with what it cost: the data for the phase 1 evaluation. */
  case class Turn(
      q: String,
      ply: Option[Int],
      viewing: Option[String], // "12... Nxe4", the move the student was looking at
      a: String,
      model: String,
      prompt: Int, // CoachPrompt.version
      millis: Int,
      firstMillis: Option[Int], // until the first text: what the student waits for
      usage: CoachLlm.Usage,
      at: Instant
  )

  private case class Chat(_id: String, facts: String, turns: List[Turn])

  private def chatId(game: Game, userId: UserId) = s"${game.id}/$userId"
