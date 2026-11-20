package controllers

import play.api.libs.json.Json

import lila.aiCoach.{ AiCoachApi, CoachText }
import lila.app.*

final class AiCoach(env: Env) extends LilaController(env):

  private def api = env.aiCoach.api

  def show(gameId: GameId) = Auth { ctx ?=> me ?=>
    Found(env.game.gameRepo.game(gameId).dmap(_.filter(api.canAsk(_, me.userId)))): game =>
      api
        .show(game, me.userId)
        .map: (ready, turns) =>
          JsonOk(Json.obj("ready" -> ready, "turns" -> turns.map(api.json)))
  }

  /** The server analysis for a game's first question: the same fishnet request, sender and limits as the
    * "Request a computer analysis" button.
    */
  private def stockfish(game: lila.core.game.Game)(using ctx: Context, me: Me) = new AiCoachApi.Stockfish:
    import lila.fishnet.Analyser.Result
    def queued = env.fishnet.analyser.queued(game.id)
    def request = env.fishnet
      .analyser(
        game,
        lila.fishnet.Work.Sender(
          userId = me,
          ip = ctx.ip.some,
          mod = isGranted(_.UserEvaluate) || isGranted(_.Relay),
          system = false
        )
      )
      .map:
        case Result.Ok | Result.AlreadyAnalysed => AiCoachApi.Request.Queued
        case Result.ConcurrentAnalysis => AiCoachApi.Request.Busy
        case Result.WeeklyLimit | Result.DailyLimit | Result.DailyIpLimit => AiCoachApi.Request.Limited
        case Result.NoGame | Result.NoChapter | Result.NotAnalysable => AiCoachApi.Request.Impossible

  /** The answer streams as ndjson, with keep-alive lines while Stockfish analyses and the model thinks. */
  def ask(gameId: GameId) = AuthBody { ctx ?=> me ?=>
    Found(env.game.gameRepo.gameWithInitialFen(gameId).dmap(_.filter(g => api.canAsk(g.game, me.userId)))):
      g =>
        bindForm(AiCoachApi.form)(
          err => jsonFormError(err).toFuccess,
          (question, ply) =>
            limit.aiCoach(me.userId, rateLimitedJson.toFuccess):
              api
                .ask(
                  g.game,
                  g.fen,
                  me.userId,
                  question,
                  ply.map(chess.Ply(_)),
                  CoachText(ctx.lang),
                  stockfish(g.game)
                )
                .map:
                  case Left(error) => JsonBadRequest(error)
                  case Right(answer) => jsOptToNdJson(ndJson.addKeepAlive(answer))
        )
  }
