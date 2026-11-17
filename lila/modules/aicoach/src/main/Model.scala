package lila.aicoach

import java.security.MessageDigest
import java.nio.charset.StandardCharsets.UTF_8

import play.api.libs.json.*

case class CoachError(code: String) extends RuntimeException(code)

object Retention:
  def default(account: Boolean): Long = (if account then 30L else 7L) * 86400000L

case class LessonConfig(color: String, level: Int, support: String)
object LessonConfig:
  given OFormat[LessonConfig] = Json.format
  def read(json: JsValue): Either[CoachError, LessonConfig] =
    json
      .validate[LessonConfig]
      .asEither
      .left
      .map(_ => CoachError("invalidConfig"))
      .flatMap: config =>
        Either.cond(
          json.as[JsObject].keys == Set("color", "level", "support") &&
            Set("white", "black", "random")(config.color) && (1 to 8).contains(config.level) &&
            Set("proactive", "onDemand")(config.support),
          config,
          CoachError("invalidConfig")
        )

case class Question(kind: String, expectedRevision: String, requestKey: String, live: Boolean)
object Question:
  given OFormat[Question] = Json.format
  def read(json: JsValue): Either[CoachError, Question] =
    json
      .validate[Question]
      .asEither
      .left
      .map(_ => CoachError("invalidQuestion"))
      .flatMap: q =>
        Either.cond(
          json.as[JsObject].keys == Set("kind", "expectedRevision", "requestKey", "live") &&
            Set("hint", "explain", "threat")(q.kind) && q.expectedRevision.matches("[a-f0-9]{64}") &&
            Identity.validKey(q.requestKey),
          q,
          CoachError("invalidQuestion")
        )

object Identity:
  def random = scalalib.SecureRandom.nextString(24)
  def digest(value: String): String = java.util.HexFormat
    .of()
    .formatHex(
      MessageDigest.getInstance("SHA-256").digest(value.getBytes(UTF_8))
    )
  def owner(userId: Option[UserId], browserSession: String): String =
    userId.fold(s"g:${digest(browserSession)}")(u => s"u:${u.value}")
  def validKey(key: String) = key.matches("[a-zA-Z0-9_-]{8,80}")

case class Interaction(
    key: String,
    kind: String,
    revision: String,
    ply: Int,
    level: Int,
    expectedRevision: String,
    taskId: String
)
object Interaction:
  given OFormat[Interaction] = Json.format

case class CoachEvent(id: Long, data: JsObject)
object CoachEvent:
  given OFormat[CoachEvent] = Json.format

case class Lesson(
    id: String,
    gameId: String,
    owner: String,
    userId: Option[String],
    requestKey: String,
    config: LessonConfig,
    learnerColor: String,
    phase: String,
    createdAt: Long,
    lastOwnerActivityAt: Long,
    expiresAt: Long,
    version: Int = 0,
    startLeaseUntil: Long = 0,
    startToken: String = "",
    reconciledAt: Long = 0,
    enqueuedThrough: Int = 0,
    hintRevision: String = "",
    hintLevel: Int = 0,
    interactions: List[Interaction] = Nil,
    runningQuestion: Option[String] = None,
    completed: List[String] = Nil,
    cards: List[JsObject] = Nil,
    cursor: Long = 0,
    events: List[CoachEvent] = Nil,
    lastProactivePly: Int = -8,
    observedRevision: String = "",
    summary: Option[LessonSummary] = None,
    finishedAt: Option[Long] = None
):
  def active = Set("preparing", "starting", "active")(phase)
  def needsReconcile = active || phase == "abandoned" || (phase == "finished" && (summary.forall(
    _.state == "pending"
  ) || completed.size <
    ((enqueuedThrough + (if learnerColor == "white" then 1 else 0)) / 2 + interactions
      .map(_.taskId)
      .distinct
      .size)))
  def valid(now: Long) = expiresAt > now && phase != "deleted"
  def withEvent(data: JsObject): Lesson =
    copy(cursor = cursor + 1, events = (events :+ CoachEvent(cursor + 1, data)).takeRight(128))
object Lesson:
  given OFormat[Lesson] = Json.format

case class StoredLesson(data: Lesson, preparedGame: Option[Game])

/** Auth is checked against the actual game player, never a session ID alone. Guest requests require rk2 even
  * if a client supplies a mobile/API header.
  */
object Ownership:
  def allows(lesson: Lesson, pov: Pov, user: Option[UserId], cookie: Option[String]): Boolean =
    pov.gameId.value == lesson.gameId && pov.color.name == lesson.learnerColor &&
      !pov.player.isAi && pov.game.hasAi && pov.game.variant.standard && !pov.game.fromPosition &&
      pov.game.clock.isEmpty && pov.game.daysPerTurn.isEmpty && pov.game.rated.no &&
      pov.game.source.contains(lila.core.game.Source.Ai) &&
      pov.game.hasRule(_.noTakeback) && pov.game.hasRule(_.noRematch) &&
      lesson.userId.match
        case Some(owner) => user.exists(_.value == owner) && pov.player.userId.exists(_.value == owner)
        case None => pov.player.userId.isEmpty && cookie.contains(pov.playerId.value)

case class Task(
    id: String,
    sessionId: String,
    kind: String,
    revision: String,
    ply: Int,
    level: Int,
    input: JsObject,
    expiresAt: Long,
    state: String = "pending",
    version: Int = 0,
    attempts: Int = 0,
    leaseUntil: Long = 0,
    token: String = "",
    availableAt: Long = 0,
    deadline: Long = 0,
    result: Option[JsObject] = None,
    error: Option[String] = None,
    published: Boolean = false,
    createdAt: Option[Long] = None,
    publishedAt: Option[Long] = None
)
object Task:
  given OFormat[Task] = Json.format
