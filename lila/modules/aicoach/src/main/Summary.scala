package lila.aicoach

import play.api.libs.json.*

case class CoachCoverage(analysed: Int, failed: Int, total: Int)
object CoachCoverage:
  given OFormat[CoachCoverage] = Json.format

case class LessonSummary(
    state: String,
    positionRevision: String,
    status: String,
    reason: String,
    coverage: CoachCoverage,
    moments: List[JsObject],
    advice: Option[String],
    message: String,
    startedAt: Long,
    deadlineAt: Long,
    updatedAt: Long,
    version: String = "coach-summary-v1"
)
object LessonSummary:
  given OFormat[LessonSummary] = Json.format

/** Reuses verified historical cards. No new engine/PV/LLM claims enter the summary. */
object Summary:
  def build(s: Lesson, game: Game, tasks: List[Task], now: Long, waitMillis: Long): LessonSummary =
    val revision = Snapshots.position(game, game.ply.value).revision
    val reason = if game.finishedOrAborted then "finished" else "abandoned"
    val previous = s.summary.filter(x =>
      x.positionRevision == revision && x.status == game.status.name && x.reason == reason
    )
    val started = previous.fold(now)(_.startedAt)
    val expected = Snapshots
      .learnerPlies(s, game)
      .map: ply =>
        Snapshots.taskId(s.id, "analyseMove", Snapshots.position(game, ply).revision)
    val history = tasks.filter(t => expected.contains(t.id) && t.kind == "analyseMove")
    val good = history.filter(t => t.state == "succeeded" && t.result.isDefined)
    val failed = history.count(t => Set("failed", "cancelled")(t.state))
    val coverage = CoachCoverage(good.size, failed, expected.size)
    val settled = good.size + failed == expected.size
    val deadline = previous.fold(started + waitMillis)(_.deadlineAt)
    val state = if good.size == expected.size then "ready"
    else if !settled && now < deadline then "pending"
    else if good.isEmpty then "failed"
    else "partial"
    val ranked = good.map: task =>
      val result = task.result.get
      val facts = result \ "facts"
      val move = facts \ "lastMove"
      def present(field: String) = (move \ field).toOption.exists(_ != JsNull)
      val rank = if (facts \ "checkmate").asOpt[Boolean].contains(true) then 5
      else if present("promotion") then 4
      else if present("castling") then 3
      else if present("capture") then 2
      else if (facts \ "check").asOpt[Boolean].contains(true) then 1
      else 0
      (rank, task.ply, PublicCard.verify(task, result))
    val selected = ranked.sortBy((rank, ply, _) => (-rank, -ply)).take(3).sortBy(_._2)
    val advice = Option.when(good.nonEmpty)(
      "Trước mỗi nước, hãy kiểm tra các nước chiếu, bắt quân và sự an toàn của vua."
    )
    val message = if expected.isEmpty then "Bạn chưa có nước đi nào để tổng kết."
    else if state == "pending" then "Coach đang hoàn tất phân tích các nước của bạn."
    else if good.isEmpty then "Chưa đủ dữ liệu đã kiểm để tổng kết các nước của bạn."
    else if state == "partial" then "Tổng kết còn thiếu dữ liệu; đây là các nhận xét đã xác nhận."
    else "Đây là các nhận xét đã xác nhận từ những nước của bạn."
    val next = LessonSummary(
      state,
      revision,
      game.status.name,
      reason,
      coverage,
      selected.map(_._3),
      advice,
      message,
      started,
      deadline,
      now
    )
    previous.filter(_.copy(updatedAt = now) == next).getOrElse(next)
