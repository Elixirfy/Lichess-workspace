package views.coach

import lila.app.UiEnv.{ *, given }

// Created with Codex; human review and manual testing remain required.
object setup:
  def apply(resumeUrl: Option[String])(using Context): lila.ui.Page =
    Page(trans.aicoach.title.txt())
      .i18n(_.aicoach)
      .css("lobby.coach")
      .js(PageModule("lobby.coach", play.api.libs.json.Json.obj())):
        main(cls := "coach-setup box box-pad")(
          h1(trans.aicoach.title()),
          p(trans.aicoach.goal()),
          p(trans.aicoach.setupInfo()),
          resumeUrl.map(url => p(a(cls := "button", href := url)(trans.aicoach.resume()))),
          form(cls := "coach-setup__form form3", action := routes.AiCoach.create, method := "post")(
            label(st.`for` := "coach-color")(trans.aicoach.color()),
            select(id := "coach-color", name := "color")(
              option(value := "white")(trans.aicoach.white()),
              option(value := "black")(trans.aicoach.black()),
              option(value := "random", selected)(trans.aicoach.random())
            ),
            label(st.`for` := "coach-level")(trans.aicoach.level()),
            select(id := "coach-level", name := "level")(
              (1 to 8).map(n => option(value := n.toString, (n == 3).option(selected))(n))
            ),
            label(st.`for` := "coach-support")(trans.aicoach.support()),
            select(id := "coach-support", name := "support")(
              option(value := "proactive")(trans.aicoach.proactive()),
              option(value := "onDemand")(trans.aicoach.onDemand())
            ),
            button(cls := "button", tpe := "submit", resumeUrl.isDefined.option(disabled))(
              trans.aicoach.start()
            ),
            p(cls := "coach-setup__status", role := "status", attr("aria-live") := "polite")
          )
        )
