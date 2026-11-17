package lila.aicoach

import chess.format.Fen
import chess.format.pgn.SanStr
import play.api.libs.json.*

object PublicCard:
  private val firstHints = Set(
    "Ưu tiên thoát chiếu trước khi thực hiện kế hoạch khác.",
    "Trước khi chọn nước, hãy kiểm tra sự an toàn của vua và các quân đang bị tấn công."
  )
  private val roles = Map(
    "p" -> "tốt",
    "n" -> "mã",
    "b" -> "tượng",
    "r" -> "xe",
    "q" -> "hậu",
    "k" -> "vua"
  )

  def verify(task: Task, response: JsObject): JsObject =
    if (response \ "schemaVersion").asOpt[Int] != Some(1) ||
      (response \ "requestId").asOpt[String] != (task.input \ "requestId").asOpt[String] ||
      (response \ "positionRevision").asOpt[String] != Some(task.revision) ||
      (response \ "kind").asOpt[String] != Some(task.kind)
    then throw CoachError("workerTargetMismatch")
    val card = (response \ "card").as[JsObject]
    if card.keys != Set("text", "highlights", "moves") then throw CoachError("unexpectedPublicFields")
    val text = (card \ "text").as[String]
    val highlights = (card \ "highlights").as[List[String]]
    val moves = (card \ "moves").as[List[JsObject]]
    if text.isEmpty || text.length > 800 || highlights.size > 2 ||
      !highlights.forall(_.matches("[a-h][1-8]")) || moves.size > 6
    then throw CoachError("invalidCard")
    if task.kind == "hint" && task.level == 1 then
      val board = Fen.read(chess.variant.Standard, Fen.Full((task.input \ "snapshot" \ "fen").as[String])).get
      val expected = if board.check.yes then "Ưu tiên thoát chiếu trước khi thực hiện kế hoạch khác."
      else "Trước khi chọn nước, hãy kiểm tra sự an toàn của vua và các quân đang bị tấn công."
      if !firstHints(text) || text != expected || highlights.nonEmpty || moves.nonEmpty then
        throw CoachError("hintLeak")
    else if task.kind == "hint" && task.level == 2 then
      val board = Fen.read(chess.variant.Standard, Fen.Full((task.input \ "snapshot" \ "fen").as[String])).get
      val expected = for
        square <- highlights match
          case List(value) => chess.Square.fromKey(value)
          case _ => None
        piece <- board.pieceAt(square)
        if piece.color.name == (task.input \ "learnerColor").as[String]
        role <- roles.get(piece.role.forsyth.toString)
      yield s"Hãy xem xét các nước hợp lệ của $role ở ${square.key}."
      if moves.nonEmpty || !expected.contains(text) then throw CoachError("hintLeak")
    else if task.kind == "hint" && task.level == 3 then
      if moves.isEmpty then throw CoachError("missingCandidate")
      if text != s"Một nước ứng viên từ engine là ${(moves.head \ "san").as[String]}, hãy tự kiểm tra ý tưởng trước khi đi."
      then throw CoachError("invalidCandidateText")
      var position = Fen
        .readWithMoveNumber(chess.variant.Standard, Fen.Full((task.input \ "snapshot" \ "fen").as[String]))
        .get
      moves.foreach: item =>
        if position.position.end then throw CoachError("variationAfterEnd")
        if item.keys != Set("san", "uci") then throw CoachError("invalidVariation")
        val san = (item \ "san").as[String]
        val (next, move) =
          position.play(SanStr(san)).fold(_ => throw CoachError("illegalVariation"), identity)
        val expected = move.fold(
          m => m.castle.fold(m.toUci.uci)(c => s"${m.orig.key}${c.kingTo.key}"),
          _ => throw CoachError("unexpectedDrop")
        )
        if expected != (item \ "uci").as[String] || move.toSanStr.value != san then
          throw CoachError("invalidVariation")
        position = next
    else if moves.nonEmpty then throw CoachError("unexpectedVariation")
    val live = Set("hint", "threat")(task.kind)
    val labelPly = if live then task.ply + 1 else task.ply
    Json.obj(
      "id" -> task.id,
      "kind" -> task.kind,
      "positionRevision" -> task.revision,
      "ply" -> task.ply,
      "moveLabel" -> s"${(labelPly + 1) / 2}${if labelPly % 2 == 1 then "." else "..."}",
      "scope" -> (if live then "live" else "history"),
      "hintLevel" -> task.level,
      "validForStatus" -> (task.input \ "snapshot" \ "status").as[String]
    ) ++ card

  def visible(card: JsObject, revision: String, status: String, phase: String = "active"): Boolean =
    (card \ "scope").asOpt[String].contains("history") ||
      (phase == "active" && (card \ "positionRevision").asOpt[String].contains(revision) &&
        (card \ "validForStatus").asOpt[String].contains(status) && status == "started")
