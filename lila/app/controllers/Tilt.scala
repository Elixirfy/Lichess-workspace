package controllers

import play.api.data.Form
import play.api.data.Forms.{ boolean, single }

import lila.app.*

final class Tilt(env: Env) extends LilaController(env):

  private val optOutForm = Form(single("optOut" -> boolean))

  def index = Auth { _ ?=> me ?=>
    for
      games <- env.tilt.api.recent(me.userId, 300)
      banner <- env.tilt.api.bannerState(me.userId)
      page <- Ok.async(views.tilt.index(games, banner.optOut))
    yield page
  }

  def bannerSetting = AuthBody { _ ?=> me ?=>
    bindForm(optOutForm)(
      _ => Redirect(routes.Tilt.index).toFuccess,
      optOut =>
        env.tilt.api.setBannerOptOut(me.userId, optOut).inject(Redirect(routes.Tilt.index).flashSuccess)
    )
  }

  def dismissBanner = Auth { _ ?=> me ?=>
    env.tilt.api.dismissBanner(me.userId).inject(Redirect(routes.Lobby.home))
  }
