package lila.tilt

import reactivemongo.api.bson.Macros.Annotations.Key

// one finished game of one player, queued for the external tilt worker (`python -m tilt lila-worker`)
case class TiltGame(
    @Key("_id") id: String,
    gameId: GameId,
    userId: UserId,
    color: Color,
    queuedAt: Instant,
    speed: Option[String] = None, // the worker scores blitz only (tilt/reports/label_v3_deployment.md)
    response: Option[TiltGame.Response] = None
):
  def pred = response.flatMap(_.pred)
  def err = response.flatMap(_.err)
  def skip = response.flatMap(_.skip)

  /** A score of the deployed M-v3 model, with its level. */
  def v3 = pred.filter(_.isV3)
  def level = v3.flatMap(_.lvl)

object TiltGame:

  /** A game and the flagged run ending with it (scores of the previous model only). */
  case class WithRun(game: TiltGame, run: Int):
    def warn = run >= warnRun

  // that many flagged games in a row deserve a break
  val warnRun = 3
  private[tilt] val runMax = 20

  /** Flagged games in a row at the start of `games`, newest first; games not scored yet are skipped. */
  def flaggedRun(games: List[TiltGame]): Int =
    games.flatMap(_.pred).takeWhile(_.flag).size

  def makeId(gameId: GameId, color: Color) = s"$gameId${color.letter}"

  def make(gameId: GameId, userId: UserId, color: Color, speed: String) = TiltGame(
    id = makeId(gameId, color),
    gameId = gameId,
    userId = userId,
    color = color,
    queuedAt = nowInstant,
    speed = speed.some
  )

  // written by the worker. skip: "speed" (not blitz) or "incomplete" (one side's moves missing).
  case class Response(at: Instant, pred: Option[Pred], err: Option[String], skip: Option[String] = None)

  enum Level(val key: String):
    case Low extends Level("low")
    case Attention extends Level("attention")
    case High extends Level("high")
  object Level:
    def apply(key: String): Option[Level] = values.find(_.key == key)

  // score: calibrated probability × 100, from 0 to 100. flag: the score reached the decision threshold.
  // factors: what moved the score the most, strongest first.
  // The M-v3 score (v = 3) predicts the v3 behavioural tilt rule; it does not measure an emotion.
  // Older documents of the previous model have no v and none of the fields after it.
  case class Pred(
      score: Int,
      flag: Boolean,
      factors: List[String],
      v: Option[Int] = None,
      prob: Option[Double] = None,
      level: Option[String] = None,
      head: Option[String] = None, // "pre": fewer than 20 plies, context before the game only
      signs: Option[List[Sign]] = None,
      fast: Option[Fast] = None,
      rules: Option[Rules] = None
  ):
    def isV3 = v.contains(3)
    def lvl: Option[Level] = isV3.so(level.flatMap(Level.apply))
    def preOnly = head.contains("pre")
    def band =
      if score <= 25 then "low"
      else if score <= 50 then "moderate"
      else if score <= 75 then "high"
      else "very high"

  /** A registry feature family that pushed the score up, and its share of the upward push. */
  case class Sign(family: String, share: Double)

  /** Faster than the player's usual blitz pace over the first 20 plies, as a robust z. */
  case class Fast(z: Double, zTrim: Double, games: Int)

  /** The post-game v3 rule check. label: TILT | NOT | ABSTAIN; context: none | stale | weak | strong. */
  case class Rules(
      label: String,
      context: String,
      fired: List[String],
      missing: List[String],
      pending: List[String],
      reason: Option[String] = None
  ):
    def tilt = label == "TILT"
    def decided = label == "TILT" || label == "NOT"
    def strong = context == "strong"
