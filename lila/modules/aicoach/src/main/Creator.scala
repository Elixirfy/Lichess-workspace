package lila.aicoach

import lila.core.game.{ GameRepo, OnStart }

final class Creator(
    store: Store,
    gameRepo: GameRepo,
    onStart: OnStart,
    guestRetentionDays: Int = 7,
    accountRetentionDays: Int = 30
)(using Executor):
  private val updates = SessionUpdates(store)

  def create(
      owner: String,
      user: Option[UserId],
      config: LessonConfig,
      key: String
  )(prepare: => Fu[Pov]): Fu[Lesson] =
    if !Identity.validKey(key) then fufail(CoachError("invalidRequestKey"))
    else
      store
        .byRequest(owner, key)
        .flatMap:
          case Some(s) if s.data.valid(nowMillis) =>
            if s.data.config != config then fufail(CoachError("idempotencyConflict"))
            else recover(s.data.id)
          case Some(_) => fufail(CoachError("expiredRequest"))
          case None =>
            store
              .active(owner)
              .flatMap:
                case Some(s) if s.data.valid(nowMillis) => fufail(CoachError("activeLessonExists"))
                case Some(s) =>
                  store
                    .save(s, s.copy(data = s.data.copy(phase = "expired", version = s.data.version + 1)))
                    .flatMap(_ => create(owner, user, config, key)(prepare))
                case None =>
                  prepare.flatMap: pov =>
                    val now = nowMillis
                    val lesson = Lesson(
                      Identity.random,
                      pov.gameId.value,
                      owner,
                      user.map(_.value),
                      key,
                      config,
                      pov.color.name,
                      "preparing",
                      now,
                      now,
                      now + retention(user.isDefined)
                    )
                    store
                      .insert(StoredLesson(lesson, Some(pov.game)))
                      .flatMap:
                        if _ then recover(lesson.id)
                        else
                          store
                            .byRequest(owner, key)
                            .flatMap:
                              case Some(s) if s.data.config == config => recover(s.data.id)
                              case _ => fufail(CoachError("activeLessonExists"))

  /** At least once onStart for the same game ID after crash; never a second game. Round/fishnet keep their
    * existing deduplication and turn checks.
    */
  def recover(id: String): Fu[Lesson] =
    val token = Identity.random
    updates(id): s =>
      if Set("preparing", "starting")(s.phase) && s.startLeaseUntil <= nowMillis then
        s.copy(startToken = token, startLeaseUntil = nowMillis + 45000)
      else s
    .flatMap:
      case Some(s) if Set("active", "finished")(s.phase) => fuccess(s)
      case Some(s) if !Set("preparing", "starting")(s.phase) => fufail(CoachError("creationFailed"))
      case Some(s) if s.startToken != token => fufail(CoachError("creationInProgress"))
      case Some(s) =>
        val gameId = GameId(s.gameId)
        (for
          stored <- store.get(id)
          existing <- gameRepo.game(gameId)
          _ <- existing match
            case Some(game) =>
              val same = stored
                .flatMap(_.preparedGame)
                .exists: prepared =>
                  prepared.players.map(p => (p.id, p.userId, p.aiLevel)) == game.players
                    .map(p => (p.id, p.userId, p.aiLevel)) &&
                    game.variant.standard && !game.fromPosition && game.clock.isEmpty && game.daysPerTurn.isEmpty &&
                    game.rated.no && game.source.contains(lila.core.game.Source.Ai) &&
                    game.hasRule(_.noTakeback) && game.hasRule(_.noRematch)
              if same then funit else fufail(CoachError("gameCollision"))
            case None =>
              stored
                .flatMap(_.preparedGame)
                .fold[Funit](fufail(CoachError("missingPreparedGame")))(gameRepo.insertDenormalized(_))
          ready <- updates(id): current =>
            if current.startToken == token then current.copy(phase = "starting") else current
          _ <- ready
            .filter(_.startToken == token)
            .fold[Funit](fufail(CoachError("lostCreationLease"))): _ =>
              onStart.exec(gameId)
          active <- updates.change(id): current =>
            if current.data.startToken == token then
              current.copy(
                preparedGame = None,
                data = current.data
                  .copy(
                    phase = "active",
                    startLeaseUntil = 0
                  )
                  .withEvent(JsonStatus.ready)
              )
            else current
        yield active.getOrElse(throw CoachError("sessionExpired")))
          .recoverWith:
            case error =>
              updates(id)(current =>
                if current.startToken == token then
                  current.copy(
                    startLeaseUntil = 0,
                    phase = if error == CoachError("gameCollision") then "failed" else current.phase
                  )
                else current
              ).flatMap(_ => Future.failed(error))
      case None => fufail(CoachError("sessionExpired"))

  def retention(account: Boolean): Long =
    (if account then accountRetentionDays.toLong else guestRetentionDays.toLong) * 86400000L

private object JsonStatus:
  val ready = play.api.libs.json.Json.obj("type" -> "ready")
