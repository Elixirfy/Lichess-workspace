package lila.tilt

import play.api.i18n.Lang

import TiltGame.Level

/** The Tilt interface texts, in English and in Vietnamese for a "vi" site language. lichess translations go
  * through crowdin, which this local module does not use. Plain words for players: no model, rule or ply
  * jargon (user request, 2026-11-17).
  */
final class TiltText(val vi: Boolean):

  private def t(en: String, viText: String) = if vi then viText else en

  def percent(x: Double): String = s"${math.round(x * 100)}%"

  def tilt = "Tilt"
  def tabTitle = t("Your tilt score for this game", "Điểm tilt của bạn trong ván này")
  def allScores = t("See all your tilt scores", "Xem tất cả điểm tilt của bạn")

  def level(l: Level) = l match
    case Level.Low => t("Low", "Thấp")
    case Level.Attention => t("Worth noting", "Đáng chú ý")
    case Level.High => t("High", "Cao")

  def preOnly = t(
    "This game was too short, so the score is based only on your earlier games.",
    "Ván quá ngắn nên điểm chỉ dựa vào các ván trước đó."
  )
  def blitzOnly = t("Only blitz games are scored.", "Chỉ ván blitz mới được chấm điểm.")
  def skipped(reason: String) = reason match
    case "speed" => blitzOnly
    case "incomplete" =>
      t(
        "This game was not scored: the opening moves of one side are missing.",
        "Ván này không được chấm: thiếu nước đi đầu ván của một bên."
      )
    case other => t(s"This game was not scored ($other).", s"Ván này không được chấm ($other).")
  def pending = t(
    "This game is not scored yet. Reload the page in a minute or two.",
    "Ván này chưa được chấm. Hãy tải lại trang sau một hai phút."
  )
  def failed(err: String) = t(s"This game could not be scored: $err", s"Không chấm được ván này: $err")
  def notScored = t("Not scored", "Không chấm")
  def waiting = t("Pending", "Đang chờ")
  def olderModel = t("older scoring", "cách chấm cũ")
  def flaggedRun(n: Int) = t(s"$n flagged games in a row.", s"$n ván liên tiếp bị gắn cờ.")
  def breakHint = t(
    " A short break before your next game may help.",
    " Nghỉ một chút trước ván tiếp theo có thể giúp ích."
  )

  // section 5: what raised the score
  def signsTitle = t("This score mostly comes from", "Điểm này chủ yếu đến từ")
  def signsNone = t("No single reason stands out.", "Không có lý do nào nổi bật.")
  def family(name: String) = name match
    case "session" => t("the results of your earlier games this session", "kết quả các ván trước trong phiên")
    case "previous" => t("your previous game", "ván ngay trước đó")
    case "session_behavior" =>
      t("how you played earlier this session", "cách bạn chơi ở các ván trước trong phiên")
    case "history" =>
      t(
        "rematches, losing streak and rest before this game",
        "tái đấu, chuỗi thua và thời gian nghỉ trước ván"
      )
    case "baseline" => t("how many past games there are to compare with", "số ván cũ có để so sánh")
    case "prefix_z" =>
      t("the opening compared with how you usually play", "đầu ván so với cách bạn thường chơi")
    case "quality" => t("move quality early in the game", "chất lượng nước đi ở đầu ván")
    case "style" => t("risky, attacking moves early in the game", "nước đi mạo hiểm, tấn công ở đầu ván")
    case "time" => t("time use early in the game", "cách dùng thời gian ở đầu ván")
    case "position" => t("the position after the opening", "thế cờ sau giai đoạn đầu ván")
    case other => other.replace('_', ' ')
  val families =
    List(
      "session",
      "previous",
      "session_behavior",
      "history",
      "baseline",
      "prefix_z",
      "quality",
      "style",
      "time",
      "position"
    )

  // section 6: faster than usual
  def fast(f: TiltGame.Fast) = t(
    s"faster than your usual pace early in the game (compared with your last ${f.games} blitz games)",
    s"đi nhanh hơn thường lệ ở đầu ván (so với ${f.games} ván blitz gần nhất)"
  )

  // section 7: after-game check
  def rulesTitle = t("After the game", "Xét lại sau ván")
  def ruleLabel(label: String) = label match
    case "TILT" => t("signs of tilt", "có dấu hiệu tilt")
    case "NOT" => t("no sign of tilt", "không có dấu hiệu tilt")
    case _ => t("not enough to tell", "chưa đủ dấu hiệu để kết luận")
  def rule(id: String) = id match
    case "C1" => t("lost 2 or more games in a row", "thua từ 2 ván liên tiếp")
    case "C2" => t("lost 3 of the last 5 or 5 of the last 10 games", "thua 3/5 hoặc 5/10 ván gần nhất")
    case "C3" => t("losses piling up in this session", "các ván thua dồn lại trong phiên")
    case "C4" => t("rating down 30 or more in this session", "rating giảm từ 30 điểm trong phiên")
    case "C5" => t("breaks between games getting shorter", "thời gian nghỉ giữa các ván ngắn dần")
    case "E1" => t("lower accuracy than usual", "độ chính xác thấp hơn thường lệ")
    case "E2" => t("more blunders than usual", "nhiều nước sai nặng hơn thường lệ")
    case "E3" => t("hurried moves", "đi vội")
    case "E4" => t("erratic move times", "thời gian đi thất thường")
    case "E5" => t("more aggressive than usual", "chơi hung hăng hơn thường lệ")
    case "E6" => t("early resignation or abandonment", "xin thua hoặc bỏ ván sớm")
    case "E7" => t("started a new game right after a loss", "vào ván mới ngay sau khi thua")
    case other => other
  val rules = List("C1", "C2", "C3", "C4", "C5", "E1", "E2", "E3", "E4", "E5", "E6", "E7")

  // section 8: banner
  def bannerTitle = t("Maybe take a short break", "Có lẽ bạn nên nghỉ một chút")
  def bannerReason(r: TiltBanner.Reason) = r match
    case TiltBanner.Reason.TwoHigh =>
      t(
        "Your last 2 blitz games both had a high tilt score.",
        "2 ván blitz gần nhất của bạn đều có điểm tilt cao."
      )
    case TiltBanner.Reason.AfterLosses =>
      t(
        "Your last blitz game had a high tilt score after a run of losses.",
        "Ván blitz gần nhất của bạn có điểm tilt cao sau một chuỗi thua."
      )
  def bannerLink = t("See your tilt page", "Xem trang tilt của bạn")
  def dismiss = t("Dismiss", "Ẩn")

  // section 9: account page
  def intro = t(
    "Each blitz game you finish gets a tilt score from 0 to 100, based on your results and how you play. Other speeds are not scored. The score is only an estimate; it does not measure emotions.",
    "Mỗi ván blitz bạn chơi xong được chấm điểm tilt từ 0 đến 100, dựa trên kết quả và cách bạn chơi. Các tốc độ khác không được chấm. Điểm chỉ là ước tính, không đo cảm xúc."
  )
  def statsTitle = t("Statistics", "Thống kê")
  def last30Days = t("Last 30 days", "30 ngày qua")
  def last50Games = t("Last 50 scored games", "50 ván được chấm gần nhất")
  def scoredGames(n: Int) = t(s"$n scored blitz games", s"$n ván blitz được chấm")
  def ruleTiltShare(tilt: Int, decided: Int) =
    if decided == 0 then
      t(
        "After the game: no game was clear enough to tell yet",
        "Xét lại sau ván: chưa có ván nào đủ rõ để kết luận"
      )
    else
      t(
        s"After the game: signs of tilt in $tilt of $decided games clear enough to tell",
        s"Xét lại sau ván: có dấu hiệu tilt ở $tilt trong $decided ván đủ rõ để kết luận"
      )
  def topSigns = t("Most common reasons", "Lý do thường gặp nhất")
  def noScores = t("No scored blitz games yet.", "Chưa có ván blitz nào được chấm.")
  def recentTitle = t("Recent games", "Các ván gần đây")
  def noGames = t("No finished games yet.", "Chưa có ván nào kết thúc.")
  def game = t("Game", "Ván")
  def finished = t("Finished", "Kết thúc")
  def score = t("Score", "Điểm")
  def signsShort = t("Main reasons", "Lý do chính")
  def ruleShort = t("After the game", "Sau ván")
  def ruleShortLabel(label: String) = label match
    case "TILT" => "tilt"
    case "NOT" => t("no", "không")
    case _ => t("unclear", "chưa rõ")
  def bannerSetting = t("Break suggestions", "Gợi ý nghỉ")
  def bannerOn = t(
    "A suggestion to take a short break appears on the home page after 2 high blitz scores in a row, or a high score after a run of losses. At most once per session.",
    "Gợi ý nghỉ ngắn hiện ở trang chủ sau 2 ván blitz liên tiếp có điểm cao, hoặc 1 ván điểm cao sau chuỗi thua. Tối đa 1 lần mỗi phiên."
  )
  def bannerOff = t("Break suggestions are turned off.", "Gợi ý nghỉ đang tắt.")
  def turnOff = t("Turn off", "Tắt")
  def turnOn = t("Turn on", "Bật")

object TiltText:
  def apply(lang: Lang): TiltText = new TiltText(lang.language == "vi")
  val en = new TiltText(false)
  val vi = new TiltText(true)
