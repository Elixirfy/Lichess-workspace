package lila.tilt

import com.softwaremill.macwire.*
import play.api.Configuration

import lila.common.autoconfig.given
import lila.core.config.CollName

@Module
final class Env(
    appConfig: Configuration,
    db: lila.db.Db
)(using Executor):

  private val coll = db(appConfig.get[CollName]("tilt.collection.queue"))
  private val bannerColl = db(appConfig.get[CollName]("tilt.collection.banner"))

  val api = TiltApi(coll, bannerColl)

  if appConfig.get[Boolean]("tilt.enabled") then
    lila.common.Bus.sub[lila.core.game.FinishGame]: finish =>
      api.request(finish).logFailure(logger)
