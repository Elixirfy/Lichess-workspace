package lila.tilt
package ui

import lila.ui.*
import lila.ui.ScalatagsTemplate.{ *, given }

import TiltGame.{ Level, Pred }

final class TiltUi(helpers: Helpers)(
    AccountPage: (String, String) => Context ?=> Page
):
  import helpers.*

  def index(games: List[TiltGame], optOut: Boolean)(using ctx: Context) =
    val t = TiltText(ctx.lang)
    val now = nowInstant
    AccountPage("Tilt", "tilt"):
      div(cls := "tilt box")(
        h1(cls := "box__top")(t.tilt),
        div(cls := "box__pad")(p(t.intro)),
        div(cls := "box__pad tilt-stats")(
          h2(t.statsTitle),
          div(cls := "tilt-stats__cols")(
            stats(t, t.last30Days, TiltStats.lastDays(games, 30, now)),
            stats(t, t.last50Games, TiltStats.lastGames(games, 50))
          )
        ),
        div(cls := "box__pad tilt-setting")(
          h2(t.bannerSetting),
          p(if optOut then t.bannerOff else t.bannerOn),
          postForm(action := routes.Tilt.bannerSetting)(
            input(tpe := "hidden", name := "optOut", value := (!optOut).toString),
            submitButton(cls := "button button-empty")(if optOut then t.turnOn else t.turnOff)
          )
        ),
        div(cls := "box__pad")(h2(t.recentTitle)),
        if games.isEmpty then div(cls := "box__pad")(p(t.noGames))
        else
          st.table(cls := "slist slist-pad tilt-games")(
            thead(tr(th(t.game), th(t.finished), th(t.score), th(t.signsShort), th(t.ruleShort))),
            tbody(games.take(50).map(row(t)))
          )
      )

  private def stats(t: TiltText, title: String, s: TiltStats) =
    div(cls := "tilt-stats__block")(
      h3(title),
      if s.games == 0 then p(t.noScores)
      else
        frag(
          p(t.scoredGames(s.games)),
          div(cls := "tilt-stats__levels")(
            Level.values.toList.map: l =>
              div(cls := s"tilt-stats__level tilt-level--${l.key}")(
                span(cls := "tilt-stats__name")(t.level(l)),
                span(cls := "tilt-stats__bar")(span(style := s"width:${math.round(s.share(l) * 100)}%")),
                strong(t.percent(s.share(l)))
              )
          ),
          p(t.ruleTiltShare(s.ruleTilt, s.ruleDecided)),
          s.signs.nonEmpty.option(
            frag(
              h4(t.topSigns),
              ul(s.signs.map((family, n) => li(t.family(family), s" ($n)")))
            )
          )
        )
    )

  private def row(t: TiltText)(game: TiltGame) =
    tr(
      td(a(href := routes.Round.watcher(game.gameId, game.color))(s"#${game.gameId}")),
      td(momentFromNow(game.queuedAt)),
      game.v3 match
        case Some(pred) =>
          frag(
            td(levelTag(t, pred), s" · ${pred.score}"),
            td(pred.signs.orZero.map(s => t.family(s.family)).mkString("; ")),
            td(pred.rules.map(r => t.ruleShortLabel(r.label)))
          )
        case None =>
          game.pred match
            case Some(pred) =>
              frag(
                td(strong(pred.score.toString), s" / 100 · ${t.olderModel}"),
                td(pred.factors.take(3).map(TiltUi.factorName).mkString(", ")),
                td()
              )
            case None =>
              td(colspan := "3")(
                game.skip
                  .map(reason => span(title := t.skipped(reason))(t.notScored))
                  .orElse(game.err.map(err => span(title := err)(t.notScored)))
                  .getOrElse(t.waiting)
              )
    )

  private def levelTag(t: TiltText, pred: Pred) =
    pred.lvl.map(l => strong(cls := s"tilt-level tilt-level--${l.key}")(t.level(l)))

  /** The "Tilt" tab of a finished game and its panel, shown to the player of that game only. */
  def game(w: TiltGame.WithRun)(using ctx: Context): (Frag, Frag) =
    val t = TiltText(ctx.lang)
    val tab = button(role := "tab", attr("data-panel") := "tilt-game", title := t.tabTitle)(t.tilt)
    val body = w.game.v3 match
      case Some(pred) => v3Panel(t, pred)
      case None =>
        w.game.pred match
          case Some(pred) => olderPanel(t, pred, w.run)
          case None =>
            p(cls := "tilt-game__pending")(
              w.game.skip.map(t.skipped).orElse(w.game.err.map(t.failed)).getOrElse(t.pending)
            )
    val panel = div(cls := "tilt-game")(
      body,
      a(cls := "tilt-game__all", href := routes.Tilt.index)(t.allScores)
    )
    tab -> panel

  private def v3Panel(t: TiltText, pred: Pred) =
    val signs = pred.signs.orZero
    frag(
      div(cls := "tilt-game__score")(levelTag(t, pred), s" · ${pred.score} / 100"),
      div(cls := List("tilt-game__meter" -> true) ++ pred.lvl.map(l => s"tilt-level--${l.key}" -> true))(
        span(style := s"width:${pred.score.atLeast(0).atMost(100)}%")
      ),
      pred.preOnly.option(p(cls := "tilt-game__note")(t.preOnly)),
      h3(t.signsTitle),
      if signs.isEmpty && pred.fast.isEmpty then p(t.signsNone)
      else
        ul(cls := "tilt-game__signs")(
          signs.map(s => li(t.family(s.family))),
          pred.fast.map(f => li(cls := "tilt-game__fast")(t.fast(f)))
        )
      ,
      pred.rules.map: r =>
        frag(
          h3(t.rulesTitle, ": ", strong(t.ruleLabel(r.label))),
          r.fired.nonEmpty.option(ul(cls := "tilt-game__rules")(r.fired.map(id => li(t.rule(id)))))
        )
    )

  private def olderPanel(t: TiltText, pred: Pred, run: Int) =
    frag(
      div(cls := "tilt-game__score")(
        strong(pred.score.toString),
        s" / 100 · ${t.olderModel}"
      ),
      div(cls := "tilt-game__meter")(span(style := s"width:${pred.score.atLeast(0).atMost(100)}%")),
      pred.factors.nonEmpty.option(p(pred.factors.take(3).map(TiltUi.factorName).mkString(", "), ".")),
      (run >= TiltGame.warnRun).option(div(cls := "tilt-warning")(strong(t.flaggedRun(run)), t.breakHint))
    )

  /** The break suggestion on the home page. */
  def banner(reason: TiltBanner.Reason)(using ctx: Context) =
    val t = TiltText(ctx.lang)
    div(cls := "tilt-banner", role := "status")(
      strong(cls := "tilt-banner__title")(t.bannerTitle),
      p(t.bannerReason(reason)),
      div(cls := "tilt-banner__actions")(
        a(cls := "button button-thin", href := routes.Tilt.index)(t.bannerLink),
        postForm(action := routes.Tilt.dismissBanner)(
          submitButton(cls := "button button-empty button-thin")(t.dismiss)
        )
      )
    )

object TiltUi:

  // inputs of the previous model (P3-B), for documents scored before M-v3
  private val factorNames = Map(
    "risk_rate" -> "risky moves",
    "attack_rate" -> "attacking moves",
    "defensive_rate" -> "defensive moves",
    "sacrifice_rate" -> "sacrifices",
    "style_switch_rate" -> "switches of playing style",
    "style_drift_in_session" -> "style drift during the session",
    "clock_missing_fraction" -> "missing clock data",
    "rematch" -> "rematch",
    "rematch_streak_before" -> "rematches in a row",
    "games_in_session_before" -> "games earlier in the session",
    "history_games" -> "games in your history",
    "baseline_speed_games" -> "games at this speed in your history",
    "initial_seconds" -> "time control",
    "increment_seconds" -> "increment",
    "phase_opening_fraction" -> "share of moves in the opening",
    "phase_middlegame_fraction" -> "share of moves in the middlegame",
    "phase_endgame_fraction" -> "share of moves in the endgame",
    // Within-game dynamics of the Phase 5 model (tilt/src/tilt/features/behavior.py).
    "attack_trend_3w" -> "change in attacking moves from the start to the end of the game",
    "risk_volatility_3w" -> "how much your risk-taking changed across the game",
    "behavior_change_point" -> "a sudden shift in risk-taking during the game"
  )

  /** A model input feature, as the worker reports it, in words. Per-player baselines (features.py
    * score_baseline) come as baseline_X_games, baseline_X_median, baseline_X_mad and deviation_X_z.
    */
  private[tilt] def factorName(feature: String): String =
    def words(f: String) = factorNames.getOrElse(f, f.replace('_', ' '))
    factorNames
      .get(feature)
      .getOrElse:
        feature match
          case s"deviation_${base}_z" => s"${words(base)} compared with your usual games"
          case s"baseline_${base}_games" => s"how many of your past games show your usual ${words(base)}"
          case s"baseline_${base}_median" => s"your usual ${words(base)}"
          case s"baseline_${base}_mad" => s"how much your ${words(base)} usually varies"
          case s"deviation_$base" => s"${words(base)} compared with your usual games"
          case s"historical_$base" => s"${words(base)} in your past games"
          case _ => words(feature)
