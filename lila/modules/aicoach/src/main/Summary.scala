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
      val legacyRank = if (facts \ "checkmate").asOpt[Boolean].contains(true) then 6
      else if present("promotion") then 5
      else if present("castling") then 4
      else if present("capture") then 3
      else if (facts \ "check").asOpt[Boolean].contains(true) then 2
      else 1
      val insight = result \ "coachInsight"
      val rank = (insight \ "importance").asOpt[Int].getOrElse(legacyRank)
      (rank, task.ply, PublicCard.verify(task, result), (insight \ "lesson").asOpt[String])
    val selected = ranked.filter(_._1 > 0).sortBy((rank, ply, _, _) => (-rank, -ply)).take(3)
    val advice = selected
      .flatMap(_._4)
      .headOption
      .flatMap:
        case "reply" =>
          Some("Trước khi bắt quân, hãy tính nước đáp mạnh nhất của đối thủ và xem ai lời sau khi đổi.")
        case "king" => Some("Trước mỗi nước, hãy thử tính nước chiếu nguy hiểm nhất mà đối thủ có thể đáp.")
        case "missed" =>
          Some("Khi có cơ hội tấn công vua, hãy tính các nước chiếu trước rồi mới chọn nước đi.")
        case "compare" =>
          Some("Chọn hai nước ứng viên và tính một nước đáp mạnh cho mỗi lựa chọn trước khi quyết định.")
        case "loosePiece" =>
          Some("Trước khi đi, hãy xem quân nào của đối thủ có thể bị bắt mà không có nước bắt lại ngay.")
        case "mate" =>
          Some(
            "Khi tìm nước chiếu hết, hãy kiểm tra ô vua có thể chạy, cách chặn chiếu và cách bắt quân chiếu."
          )
        case "stalemate" =>
          Some("Thử nhìn từ phía đối thủ trước nước kết thúc và kiểm tra xem họ còn nước đi hợp lệ nào.")
        case "promotion" =>
          Some("Trước khi phong cấp, hãy kiểm tra nước chiếu, nước bắt quân và nguy cơ hòa hết nước đi.")
        case _ => None
    val practice = advice.orElse(
      Option.when(
        selected.nonEmpty && good.forall(_.result.exists(r => (r \ "coachInsight").toOption.isEmpty))
      )(
        "Trước mỗi nước, hãy kiểm tra các nước chiếu, bắt quân và sự an toàn của vua."
      )
    )
    val message = if expected.isEmpty then "Bạn chưa có nước đi nào để tổng kết."
    else if state == "pending" then "Coach đang hoàn tất phân tích các nước của bạn."
    else if good.isEmpty then "Chưa đủ dữ liệu đã kiểm để tổng kết các nước của bạn."
    else if state == "partial" then "Tổng kết còn thiếu dữ liệu; đây là các nhận xét đã xác nhận."
    else if selected.isEmpty then "Chưa thấy bước ngoặt rõ ràng trong các nước đã phân tích."
    else "Đây là những bước ngoặt đáng xem lại trong ván."
    val next = LessonSummary(
      state,
      revision,
      game.status.name,
      reason,
      coverage,
      selected.sortBy(_._2).map(_._3),
      practice,
      message,
      started,
      deadline,
      now
    )
    previous.filter(_.copy(updatedAt = now) == next).getOrElse(next)
