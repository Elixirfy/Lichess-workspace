package lila.tilt

import reactivemongo.api.bson.*

import lila.core.game.FinishGame
import lila.db.dsl.{ *, given }

object TiltApi:
  import TiltGame.{ Fast, Pred, Response, Rules, Sign }
  private given BSONDocumentHandler[Sign] = Macros.handler
  private given BSONDocumentHandler[Fast] = Macros.handler
  private given BSONDocumentHandler[Rules] = Macros.handler
  private given BSONDocumentHandler[Pred] = Macros.handler
  private given BSONDocumentHandler[Response] = Macros.handler
  private[tilt] given BSONDocumentHandler[TiltGame] = Macros.handler

final class TiltApi(coll: Coll, bannerColl: Coll)(using Executor):

  import TiltApi.given

  lila.common.Bus.sub[lila.core.user.UserDelete]: del =>
    coll.delete.one(bdoc("userId" -> del.id)).void
    bannerColl.delete.one(bid(del.id)).void

  def recent(userId: UserId, nb: Int): Fu[List[TiltGame]] =
    coll
      .find(bdoc("userId" -> userId))
      .sort(bdoc("queuedAt" -> -1))
      .cursor[TiltGame]()
      .list(nb)

  /** The player's score for this game; for the previous model, also its flagged run up to this game. */
  def forGame(gameId: GameId, userId: UserId): Fu[Option[TiltGame.WithRun]] =
    coll
      .one[TiltGame](bdoc("gameId" -> gameId, "userId" -> userId))
      .flatMap:
        _.so: game =>
          game.pred
            .exists(p => p.flag && !p.isV3)
            .so(flaggedRun(userId, game.queuedAt))
            .map(run => TiltGame.WithRun(game, run).some)

  private def flaggedRun(userId: UserId, upTo: Instant): Fu[Int] =
    coll
      .find(
        bdoc(
          "userId" -> userId,
          "response.pred" -> bdoc("$exists" -> true),
          "queuedAt" -> bdoc("$lte" -> upTo)
        )
      )
      .sort(bdoc("queuedAt" -> -1))
      .cursor[TiltGame]()
      .list(TiltGame.runMax)
      .map(TiltGame.flaggedRun)

  def bannerState(userId: UserId): Fu[TiltBanner.State] =
    bannerColl
      .one[Bdoc](bid(userId))
      .map:
        _.fold(TiltBanner.noState): doc =>
          TiltBanner.State(doc.getAsOpt[Instant]("shownAt"), doc.getAsOpt[Boolean]("optOut") | false)

  /** The home page banner, if due now; showing it is recorded, so it appears once per session. */
  def banner(userId: UserId, playing: Boolean): Fu[Option[TiltBanner.Reason]] =
    if playing then fuccess(none)
    else
      for
        state <- bannerState(userId)
        games <- if state.optOut then fuccess(Nil) else recent(userId, 20)
        now = nowInstant
        reason = TiltBanner.decide(state, games, now, playing)
        _ <- reason.fold(funit)(_ =>
          bannerColl.update.one(bid(userId), bset("shownAt" -> now), upsert = true).void
        )
      yield reason

  def dismissBanner(userId: UserId): Funit =
    bannerColl.update.one(bid(userId), bset("dismissedAt" -> nowInstant), upsert = true).void

  def setBannerOptOut(userId: UserId, optOut: Boolean): Funit =
    bannerColl.update.one(bid(userId), bset("optOut" -> optOut), upsert = true).void

  // standard games with a clock between humans; the worker scores the blitz ones
  private[tilt] def request(finish: FinishGame): Funit =
    val game = finish.game
    val eligible =
      game.finished && game.variant.standard && game.hasClock && !game.hasAi && game.playedPlies > 1
    eligible.so:
      Color.all
        .flatMap: color =>
          finish
            .usersBeforeGame(color)
            .filter(_.noBot)
            .map(user => TiltGame.make(game.id, user.id, color, game.speed.key.value))
        .sequentiallyVoid: req =>
          coll.update.one(bid(req.id), req, upsert = true).void
