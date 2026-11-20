package lila.aiCoach
package ui

import play.api.libs.json.Json

import lila.ui.*
import lila.ui.ScalatagsTemplate.*

/** The "AI Coach" tab of a finished game's analysis board; analyse.aiCoach.ts runs the chat. */
object AiCoachUi:

  def tab(t: CoachText): Frag =
    button(role := "tab", attr("data-panel") := "ai-coach", title := t.tabTitle)(t.tab)

  def panel(gameId: GameId, t: CoachText): Frag =
    div(
      cls := "ai-coach",
      attr("data-url") := routes.AiCoach.show(gameId).url,
      attr("data-i18n") := Json.stringify(t.browser)
    )(
      div(cls := "ai-coach__log")(p(cls := "ai-coach__intro")(t.intro)),
      div(cls := "ai-coach__suggestions")(
        t.suggestions.map(s => button(tpe := "button", cls := "ai-coach__chip")(s))
      ),
      form(cls := "ai-coach__form")(
        textarea(name := "q", maxlength := 500, rows := 1, required, placeholder := t.placeholder),
        button(tpe := "submit", cls := "button ai-coach__send")(t.ask)
      )
    )
