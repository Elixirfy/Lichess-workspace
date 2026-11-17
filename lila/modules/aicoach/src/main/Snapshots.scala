package lila.aicoach

import chess.format.Fen
import play.api.libs.json.*

object Snapshots:
  def position(game: Game, ply: Int): PositionRevision.Snapshot =
    if !game.variant.standard || ply < 0 || ply > game.ply.value then throw CoachError("invalidCoachGame")
    PositionRevision
      .replay(Fen.Full.initial, game.sans.take(ply).toList)
      .fold(error => throw CoachError(error), identity)

  def input(s: Lesson, game: Game, kind: String, ply: Int, level: Int, taskId: String): JsObject =
    val p = position(game, ply)
    Json.obj(
      "schemaVersion" -> 1,
      "requestId" -> Identity.digest(taskId),
      "kind" -> kind,
      "positionRevision" -> p.revision,
      "learnerColor" -> s.learnerColor,
      "snapshot" -> Json.obj(
        "schemaVersion" -> 1,
        "variant" -> "standard",
        "initialFen" -> p.initialFen.value,
        "sanHistory" -> game.sans.take(ply).map(_.value),
        "ply" -> ply,
        "fen" -> p.fen.value,
        "status" -> (if ply == game.ply.value then game.status.name else "started"),
        "winner" -> (if ply == game.ply.value then game.winnerColor.map(_.name) else None)
      )
    ) ++ (if kind == "analyseMove" then Json.obj() else Json.obj("hintLevel" -> level))

  def learnerPlies(s: Lesson, game: Game): List[Int] =
    (1 to game.ply.value).filter(p => (p % 2 == 1) == (s.learnerColor == "white")).toList

  def playable(s: Lesson, game: Game): Boolean =
    game.playable && game.turnColor.name == s.learnerColor && !game.position.end

  def taskId(session: String, kind: String, revision: String, level: Int = 0): String =
    Identity.digest(s"$session:$kind:$revision:$level")

object QuestionRules:
  /** Reservation and hint increment are committed in the same session CAS. */
  def reserve(
      s: Lesson,
      game: Game,
      q: Question,
      now: Long,
      maxQuestions: Int,
      retention: Boolean => Long = Retention.default
  ): Lesson =
    val current = Snapshots.position(game, game.ply.value)
    s.interactions.find(_.key == q.requestKey) match
      case Some(previous) =>
        if previous.kind != q.kind || q.expectedRevision != previous.expectedRevision then
          throw CoachError("idempotencyConflict")
        s
      case None =>
        if !Set("active", "finished")(s.phase) || q.expectedRevision != current.revision then
          throw CoachError("stalePosition")
        if s.interactions.size >= maxQuestions then throw CoachError("questionLimit")
        val ongoing = s.runningQuestion.flatMap(id => s.interactions.find(_.taskId == id))
        if ongoing.exists(i => i.kind == "explain" || i.revision == current.revision) then
          throw CoachError("questionInProgress")
        if q.kind != "explain" && (!q.live || !Snapshots.playable(s, game)) then
          throw CoachError("liveUnavailable")
        val target = if q.kind == "explain" then
          Snapshots.learnerPlies(s, game).lastOption.getOrElse(throw CoachError("noLearnerMove"))
        else game.ply.value
        if q.kind == "threat" && game.ply.value == 0 then throw CoachError("noOpponentMove")
        val p = Snapshots.position(game, target)
        val level = if q.kind == "hint" then
          if s.hintRevision == p.revision then (s.hintLevel + 1).min(3) else 1
        else 0
        val id = Snapshots.taskId(s.id, q.kind, p.revision, level)
        val interaction = Interaction(q.requestKey, q.kind, p.revision, target, level, current.revision, id)
        s.copy(
          lastOwnerActivityAt = now,
          expiresAt = now + retention(s.userId.isDefined),
          hintRevision = if q.kind == "hint" then p.revision else s.hintRevision,
          hintLevel = if q.kind == "hint" then level else s.hintLevel,
          interactions = s.interactions :+ interaction,
          runningQuestion = Option.unless(s.completed.contains(id))(id)
        )
