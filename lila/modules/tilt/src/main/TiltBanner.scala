package lila.tilt

import TiltGame.Level

/** The break suggestion on the home page (tilt/reports/label_v3_deployment.md section 8).
  *
  * Shown when the last two scored blitz games of the current session were both high, or the last one was high
  * with a strong rule context. At most once per session, at least 30 minutes apart, never during a game, and
  * never after the player opted out.
  */
object TiltBanner:

  enum Reason(val key: String):
    case TwoHigh extends Reason("twoHigh")
    case AfterLosses extends Reason("afterLosses")

  /** Stored in `tilt_banner`, one document per user. */
  case class State(shownAt: Option[Instant], optOut: Boolean)
  val noState = State(None, false)

  // the worker's session gap (features/manifest.json session_gap_minutes)
  val sessionGap = java.time.Duration.ofMinutes(30)
  val minInterval = java.time.Duration.ofMinutes(30)

  /** The scored M-v3 games of the session that holds the newest one, newest first. */
  def session(games: List[TiltGame], now: Instant): List[TiltGame] =
    val scored = games.filter(_.v3.isDefined).sortBy(_.queuedAt)(using Ordering[Instant].reverse)
    scored.headOption
      .filter(_.queuedAt.isAfter(now.minus(sessionGap)))
      .so: newest =>
        newest :: scored
          .zip(scored.drop(1))
          .takeWhile((later, earlier) => earlier.queuedAt.isAfter(later.queuedAt.minus(sessionGap)))
          .map(_._2)

  def reason(session: List[TiltGame]): Option[Reason] =
    session match
      case last :: previous :: _ if last.level.contains(Level.High) && previous.level.contains(Level.High) =>
        Reason.TwoHigh.some
      case last :: _ if last.level.contains(Level.High) && last.v3.flatMap(_.rules).exists(_.strong) =>
        Reason.AfterLosses.some
      case _ => none

  /** `games` are the player's latest queued games, in any order; `playing`: a game is in progress. */
  def decide(state: State, games: List[TiltGame], now: Instant, playing: Boolean): Option[Reason] =
    if state.optOut || playing then none
    else
      val current = session(games, now)
      reason(current).filter: _ =>
        state.shownAt.forall: shown =>
          shown.isBefore(now.minus(minInterval)) && current.lastOption.forall(g => shown.isBefore(g.queuedAt))

/** Counts for /account/tilt over M-v3 scores. */
case class TiltStats(
    games: Int,
    levels: Map[Level, Int],
    ruleTilt: Int,
    ruleDecided: Int,
    signs: List[(String, Int)]
):
  def share(level: Level): Double = if games == 0 then 0 else levels.getOrElse(level, 0).toDouble / games

object TiltStats:

  def of(games: List[TiltGame]): TiltStats =
    val preds = games.flatMap(_.v3)
    val rules = preds.flatMap(_.rules)
    TiltStats(
      games = preds.size,
      levels = preds.flatMap(_.lvl).groupMapReduce(identity)(_ => 1)(_ + _),
      ruleTilt = rules.count(_.tilt),
      ruleDecided = rules.count(_.decided),
      signs = preds
        .flatMap(_.signs.orZero.map(_.family))
        .groupMapReduce(identity)(_ => 1)(_ + _)
        .toList
        .sortBy((family, n) => (-n, family))
        .take(3)
    )

  def lastDays(games: List[TiltGame], days: Int, now: Instant) =
    of(games.filter(_.queuedAt.isAfter(now.minus(java.time.Duration.ofDays(days)))))

  def lastGames(games: List[TiltGame], nb: Int) =
    of(games.filter(_.v3.isDefined).sortBy(_.queuedAt)(using Ordering[Instant].reverse).take(nb))
