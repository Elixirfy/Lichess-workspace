package lila.aicoach

import chess.format.Fen
import chess.format.pgn.SanStr
import play.api.libs.json.*

object PublicCard:
  private[aicoach] val practiceVersion = 3
  private val checkHint = "Ưu tiên thoát chiếu trước khi thực hiện kế hoạch khác."
  private val quietHints = Set(
    "Trước khi chọn nước, hãy kiểm tra sự an toàn của vua và các quân đang bị tấn công.",
    "Trước khi triển khai kế hoạch, hãy tìm nước chiếu hoặc bắt quân nguy hiểm nhất của đối thủ."
  )
  private val candidatePurposes = Set(
    "nước này chiếu hết",
    "nước này nhập thành và đưa xe vào cuộc",
    "nước này giúp vua thoát chiếu",
    "hãy tính tiếp xem đối thủ có thể bắt lại hay không",
    "nước này buộc đối thủ đỡ chiếu",
    "nước này phát triển mã khỏi hàng xuất phát",
    "nước này phát triển tượng khỏi hàng xuất phát",
    "nước này đưa quân vào trung tâm",
    "hãy xem nước đáp của đối thủ trong biến gợi ý",
    "hãy tự kiểm tra ý tưởng trước khi đi"
  )
  private val roles = Map(
    "p" -> "tốt",
    "n" -> "mã",
    "b" -> "tượng",
    "r" -> "xe",
    "q" -> "hậu",
    "k" -> "vua"
  )

  private def describeCandidate(position: chess.Position, san: String, uci: String): String =
    if san.startsWith("O-O-O") then "nhập thành cánh hậu"
    else if san.startsWith("O-O") then "nhập thành cánh vua"
    else
      val origin = uci.take(2)
      val target = uci.slice(2, 4)
      val role = if san.head.isUpper then roles.getOrElse(san.head.toLower.toString, "tốt") else "tốt"
      val action = if san.contains('x') then
        val victim = chess.Square.fromKey(target).flatMap(position.pieceAt)
        val name = victim.fold("tốt")(p => roles(p.role.forsyth.toString))
        val suffix = if victim.isEmpty then " bằng nước bắt tốt qua đường" else ""
        s"dùng $role ở $origin bắt $name tại $target$suffix"
      else if role == "tốt" then
        val direction = if target(1) > origin(1) then "lên" else "xuống"
        s"đẩy tốt từ $origin $direction $target"
      else s"đưa $role từ $origin đến $target"
      action + roles.get(uci.drop(4)).fold("")(name => s" và phong thành $name")

  private def replayLine(fen: Fen.Full, moves: List[JsObject]): Unit =
    var position = Fen.readWithMoveNumber(chess.variant.Standard, fen).get
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

  private def practiceCard(task: Task, response: JsObject): Option[JsObject] =
    (response \ "practice")
      .asOpt[JsObject]
      .flatMap: practice =>
        (practice \ "version")
          .asOpt[Int]
          .filter(version => version == 2 || version == practiceVersion)
          .map(version => (practice, if version == 2 then 2 else 7))
      .map: (practice, maxPlies) =>
        if !Set("analyseMove", "explain")(task.kind) ||
          practice.keys != Set("version", "prompt", "played", "alternatives")
        then throw CoachError("invalidPractice")
        val snapshot = task.input \ "snapshot"
        val sans = (snapshot \ "sanHistory").as[List[String]]
        if sans.size != task.ply || sans.isEmpty then throw CoachError("invalidPracticePosition")
        val initial = Fen.Full((snapshot \ "initialFen").as[String])
        val before = PositionRevision
          .replay(initial, sans.dropRight(1).map(SanStr(_)))
          .fold(_ => throw CoachError("invalidPracticePosition"), identity)
        val played = (practice \ "played").as[JsObject]
        val alternatives = (practice \ "alternatives").as[List[JsObject]]
        val prompt = (practice \ "prompt").as[String]
        if alternatives.isEmpty || alternatives.size > 3 || prompt.isEmpty || prompt.length > 180 then
          throw CoachError("invalidPractice")
        val firstMoves = (played :: alternatives).map: line =>
          val moves = (line \ "moves").as[List[JsObject]]
          val text = (line \ "text").as[String]
          if line.keys != Set(
              "text",
              "moves"
            ) || moves.isEmpty || moves.size > maxPlies || text.isEmpty || text.length > 800
          then throw CoachError("invalidPracticeLine")
          replayLine(before.fen, moves)
          (moves.head \ "san").as[String]
        if firstMoves.head != sans.last || firstMoves.distinct != firstMoves then
          throw CoachError("invalidPracticeChoices")
        practice + ("fen" -> JsString(before.fen.value))

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
      val expected = if board.check.yes then Set(checkHint) else quietHints
      if !expected(text) || highlights.nonEmpty || moves.nonEmpty then throw CoachError("hintLeak")
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
      val first = (moves.head \ "san").as[String]
      val reply = moves.drop(1).headOption.map(m => (m \ "san").as[String])
      val purposes =
        candidatePurposes ++ reply.map(san => s"hãy xem thế cờ thay đổi ra sao nếu đối thủ đáp $san")
      val fen = Fen.Full((task.input \ "snapshot" \ "fen").as[String])
      replayLine(fen, moves)
      val initial = Fen.read(chess.variant.Standard, fen).get
      val description = describeCandidate(initial, first, (moves.head \ "uci").as[String])
      val currentPurposes = if reply.isDefined then candidatePurposes
      else candidatePurposes - "hãy xem nước đáp của đối thủ trong biến gợi ý"
      val friendly = currentPurposes.exists(purpose => text == s"Thử $description. ${purpose.capitalize}.")
      val legacy = purposes.exists(purpose => text == s"Một nước ứng viên từ engine là $first, $purpose.")
      if !friendly && !legacy then throw CoachError("invalidCandidateText")
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
    ) ++ card ++ JsObject(practiceCard(task, response).map("practice" -> _).toList)

  def visible(card: JsObject, revision: String, status: String, phase: String = "active"): Boolean =
    (card \ "scope").asOpt[String].contains("history") ||
      (phase == "active" && (card \ "positionRevision").asOpt[String].contains(revision) &&
        (card \ "validForStatus").asOpt[String].contains(status) && status == "started")
