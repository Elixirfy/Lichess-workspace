package controllers

import org.apache.pekko.NotUsed
import org.apache.pekko.stream.scaladsl.Source
import play.api.libs.json.*
import play.api.mvc.Result

import lila.app.*
import lila.aicoach.{
  CoachError,
  Feed,
  Identity,
  Lesson,
  LessonConfig,
  Ownership,
  PublicCard,
  Question,
  Snapshots
}
import lila.game.AnonCookie
import lila.core.game.Game as ChessGame

final class AiCoach(env: Env) extends LilaController(env):
  private def coach = env.aiCoach

  /** Establish the existing signed Lila browser session before guest POSTs. */
  def bootstrap = Open: ctx ?=>
    if !coach.enabled then notFoundJson()
    else
      val owner = Identity.owner(ctx.userId, ctx.req.sid.map(_.value).getOrElse(""))
      for
        _ <- coach.ready
        active <- coach.store.active(owner)
        found <- active
          .filter(_.data.valid(System.currentTimeMillis()))
          .fold(
            fuccess(Option.empty[(Lesson, ChessGame)])
          )(s => findOwned(s.data.id))
        resume = found.map: (s, game) =>
          routes.Round.watcher(game.id, if s.learnerColor == "white" then Color.White else Color.Black).url
        response <- negotiate(
          Ok.page(views.coach.setup(resume)),
          fuccess(
            Ok(
              Json.obj(
                "levels" -> (1 to 8),
                "support" -> List("proactive", "onDemand"),
                "colors" -> List("white", "black", "random"),
                "resumeUrl" -> resume
              )
            )
          )
        )
      yield env.security.lilaCookie.ensure(response.withHeaders("Cache-Control" -> "no-store"))

  def create = OpenBodyOf(parse.json): ctx ?=>
    limit.setupPost(ctx.ip, rateLimited()):
      handled:
        if !coach.enabled then fufail(CoachError("disabled"))
        else if ctx.userId.isEmpty && ctx.req.sid.isEmpty then fufail(CoachError("browserSessionRequired"))
        else
          for
            config <- LessonConfig.read(ctx.body.body).toFuture
            key <- ctx.req.headers
              .get("Idempotency-Key")
              .filter(Identity.validKey)
              .fold[Fu[String]](fufail(CoachError("invalidRequestKey")))(fuccess)
            _ <- coach.ready
            owner = Identity.owner(ctx.userId, ctx.req.sid.map(_.value).getOrElse(""))
            color = config.color match
              case "white" => Color.White
              case "black" => Color.Black
              case _ => if scalalib.ThreadLocalRandom.nextBoolean() then Color.White else Color.Black
            s <- coach.creator.create(owner, ctx.userId, config, key):
              env.setup.processor.prepareCoach(color, config.level)(using ctx.me)
            game <- env.round.gameProxy
              .game(GameId(s.gameId))
              .flatMap(_.fold[Fu[ChessGame]](fufail(CoachError("gameUnavailable")))(fuccess))
          yield
            coach.observe(s)
            val pov = Pov(game, if s.learnerColor == "white" then Color.White else Color.Black)
            val response = Created(
              Json.obj(
                "sessionId" -> s.id,
                "gameId" -> s.gameId,
                "learnerColor" -> s.learnerColor,
                "playUrl" -> routes.Round.watcher(pov.gameId, pov.color).url
              )
            )
            if ctx.userId.isDefined then response
            else
              response.withCookies(
                env.security.lilaCookie.cookie(
                  AnonCookie.name,
                  pov.playerId.value,
                  maxAge = Some(AnonCookie.maxAge),
                  httpOnly = Some(false)
                )
              )

  def snapshot(id: String) = Open:
    owned(id): (s, game) =>
      coach.store
        .tasks(s.id)
        .map: tasks =>
          val p = Snapshots.position(game, game.ply.value)
          val historical = tasks.filter(_.kind == "analyseMove")
          val learnerPlies = Snapshots.learnerPlies(s, game)
          val proactive = s.config.support == "proactive"
          val playable = s.phase == "active" && Snapshots.playable(s, game)
          val visible = s.cards.filter(PublicCard.visible(_, p.revision, game.status.name, s.phase))
          // Older workers analysed quiet moves but did not publish them in proactive lessons.
          val previousObservation = learnerPlies.lastOption
            .filter(_ => proactive)
            .flatMap: ply =>
              historical
                .find(task =>
                  task.ply == ply && task.state == "succeeded" && task.published &&
                    !visible.exists(card => (card \ "id").asOpt[String].contains(task.id))
                )
                .filter(task =>
                  task.revision == (if ply == p.ply then p.revision
                                    else Snapshots.position(game, ply).revision)
                )
                .flatMap(task => task.result.map(PublicCard.verify(task, _)))
          Ok(
            Json.obj(
              "sessionId" -> s.id,
              "gameId" -> s.gameId,
              "phase" -> s.phase,
              "learnerColor" -> s.learnerColor,
              "level" -> s.config.level,
              "support" -> s.config.support,
              "positionRevision" -> p.revision,
              "ply" -> p.ply,
              "status" -> game.status.name,
              "hintLevel" -> (if s.hintRevision == p.revision then s.hintLevel else 0),
              "openingAdvice" -> Option.when(proactive && playable && learnerPlies.isEmpty)(
                "Hãy thử tranh chấp trung tâm bằng một nước mở đường cho tượng hoặc đưa mã ra."
              ),
              "capabilities" -> Json.obj(
                "hint" -> playable,
                "explain" -> (Set("active", "finished")(s.phase) && learnerPlies.nonEmpty),
                "threat" -> (playable && game.ply.value > 0)
              ),
              "cursor" -> s.cursor,
              "cards" -> (visible ++ previousObservation),
              "summary" -> s.summary.filter(x =>
                Set("finished", "abandoned")(s.phase) &&
                  x.positionRevision == p.revision && x.status == game.status.name
              ),
              "coverage" -> Json.obj(
                "analysed" -> historical.count(_.state == "succeeded"),
                "failed" -> historical.count(_.state == "failed"),
                "total" -> Snapshots.learnerPlies(s, game).size
              ),
              "questions" -> s.interactions.map: i =>
                Json.obj(
                  "taskId" -> i.taskId,
                  "kind" -> i.kind,
                  "positionRevision" -> i.revision,
                  "ply" -> i.ply,
                  "hintLevel" -> i.level,
                  "state" -> tasks.find(_.id == i.taskId).map(_.state).getOrElse("pending")
                )
            )
          ).withHeaders("Cache-Control" -> "no-store")

  /** Round can rediscover its session after refresh without browser storage. */
  def forGame(gameId: GameId) = Open:
    if !coach.enabled then notFoundJson()
    else
      coach.store
        .byGame(gameId.value)
        .flatMap:
          case Some(stored) =>
            owned(stored.data.id): (s, _) =>
              fuccess(Ok(Json.obj("sessionId" -> s.id)).withHeaders("Cache-Control" -> "no-store"))
          case None => notFoundJson()

  def resume(id: String) = OpenBodyOf(parse.json): ctx ?=>
    limit.setupPost(ctx.ip, rateLimited()):
      owned(id): (_, _) =>
        if ctx.body.body != Json.obj() then fufail(CoachError("invalidResume"))
        else coach.runtime.resume(id).map(s => Ok(Json.obj("sessionId" -> s.id, "phase" -> s.phase)))

  def question(id: String) = OpenBodyOf(parse.json): ctx ?=>
    limit.setupPost(ctx.ip, rateLimited()):
      owned(id): (_, _) =>
        for
          question <- Question.read(ctx.body.body).toFuture
          interaction <- coach.runtime.question(id, question)
        yield Accepted(
          Json.obj(
            "taskId" -> interaction.taskId,
            "positionRevision" -> interaction.revision,
            "ply" -> interaction.ply,
            "hintLevel" -> interaction.level
          )
        )

  def events(id: String) = Open:
    owned(id): (_, _) =>
      val supplied = get("cursor").orElse(ctx.req.headers.get("Last-Event-ID")).getOrElse("0")
      supplied.toLongOption.filter(_ >= 0) match
        case None => fuccess(BadRequest(Json.obj("error" -> "invalidCursor")))
        case Some(initial) =>
          var cursor = initial
          val source = Source
            .tick(Duration.Zero, 1.second, NotUsed)
            .mapAsync(1): _ =>
              findOwned(id)
            .takeWhile(_.isDefined)
            .mapConcat: found =>
              val (s, game) = found.get
              val revision = Snapshots.position(game, game.ply.value).revision
              val pending = Feed.after(s, cursor, revision, game.status.name)
              pending.lastOption.foreach(e => cursor = e.id)
              if pending.isEmpty then List(": heartbeat\n\n") else pending.map(Feed.encode)
          fuccess(
            Ok.chunked(source)
              .as("text/event-stream")
              .withHeaders("Cache-Control" -> "no-store", "X-Accel-Buffering" -> "no")
          )

  private def findOwned(id: String)(using ctx: Context): Fu[Option[(Lesson, ChessGame)]] =
    if !coach.enabled || !id.matches("[a-zA-Z0-9]{24}") then fuccess(None)
    else
      coach.store
        .get(id)
        .flatMap:
          case Some(stored) if stored.data.valid(System.currentTimeMillis()) =>
            env.round.gameProxy
              .game(GameId(stored.data.gameId))
              .map:
                _.filter: game =>
                  val pov =
                    Pov(game, if stored.data.learnerColor == "white" then Color.White else Color.Black)
                  Ownership.allows(
                    stored.data,
                    pov,
                    ctx.userId,
                    ctx.req.cookies.get(AnonCookie.name).map(_.value)
                  )
                .map(stored.data -> _)
          case _ => fuccess(None)

  private def owned(id: String)(f: (Lesson, ChessGame) => Fu[Result])(using Context): Fu[Result] = handled:
    findOwned(id).flatMap:
      case Some((s, game)) => f(s, game)
      case None => notFoundJson()

  private def handled(f: => Fu[Result]): Fu[Result] =
    scala.util
      .Try(f)
      .fold(Future.failed, identity)
      .recover:
        case CoachError(code) =>
          val status = if code == "disabled" then 404
          else if code.startsWith("invalid") || code == "browserSessionRequired" then 400
          else 409
          Status(status)(Json.obj("error" -> code))
