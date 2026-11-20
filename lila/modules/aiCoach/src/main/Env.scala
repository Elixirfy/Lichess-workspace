package lila.aiCoach

import com.softwaremill.macwire.*
import play.api.Configuration
import play.api.libs.ws.StandaloneWSClient

import lila.core.config.{ CollName, NetDomain }

@Module
final class Env(
    appConfig: Configuration,
    db: lila.db.Db,
    ws: StandaloneWSClient,
    analyser: lila.analyse.Analyser,
    divider: lila.core.game.Divider
)(using Executor, Scheduler, NetDomain, org.apache.pekko.stream.Materializer):

  private val llm = CoachLlm(ws, appConfig.get[CoachLlm.Config]("aiCoach"))

  val api = AiCoachApi(db(CollName("ai_coach_chat")), llm, analyser, divider)
