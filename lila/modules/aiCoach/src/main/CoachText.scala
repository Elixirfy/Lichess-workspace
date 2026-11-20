package lila.aiCoach

import play.api.i18n.Lang
import play.api.libs.json.*

/** The coach's interface texts, in English and in Vietnamese for a "vi" site language. lichess translations
  * go through crowdin, which this local module does not use. The answers follow the language of the question.
  */
final class CoachText(val vi: Boolean):

  private def t(en: String, viText: String) = if vi then viText else en

  def tab = t("AI Coach", "HLV AI")
  def tabTitle = t("Ask a coach about this game", "Hỏi huấn luyện viên về ván này")
  def intro = t(
    "Ask about this game. Answers are based only on Stockfish's analysis of it.",
    "Hỏi về ván cờ này. Câu trả lời chỉ dựa trên phân tích của Stockfish cho ván này."
  )
  def placeholder = t("Ask the coach…", "Hỏi huấn luyện viên…")
  def ask = t("Ask", "Hỏi")
  def suggestions: List[String] =
    if vi then
      List(
        "Sai lầm lớn nhất của tôi là gì?",
        "Nước nào quyết định ván cờ?",
        "Vì sao nước này là sai lầm?",
        "Sau ván này tôi nên luyện gì?"
      )
    else
      List(
        "What was my biggest mistake?",
        "Which move decided the game?",
        "Why was this move a mistake?",
        "What should I work on after this game?"
      )

  // server errors
  def limited = t(
    s"This review is limited to ${AiCoachApi.maxTurns} questions.",
    s"Mỗi ván chỉ được hỏi tối đa ${AiCoachApi.maxTurns} câu."
  )
  def analysisBusy = t(
    "Stockfish is still analysing another game of yours. Ask again in a minute.",
    "Stockfish đang phân tích một ván khác của bạn. Hãy hỏi lại sau ít phút."
  )
  def analysisLimited = t(
    "You have used up your computer analyses for now. Try again later.",
    "Bạn đã hết lượt phân tích máy tính cho lúc này. Hãy thử lại sau."
  )
  def analysisImpossible = t(
    "Stockfish cannot analyse this game: too few moves, or a variant it does not support.",
    "Stockfish không phân tích được ván này: quá ít nước, hoặc là biến thể không được hỗ trợ."
  )
  def analysisFailed = t(
    "Stockfish has not finished analysing this game. Ask again in a few minutes.",
    "Stockfish chưa phân tích xong ván này. Hãy hỏi lại sau vài phút."
  )
  def couldNotAnswer = t(
    "The coach could not answer that. Try rephrasing your question.",
    "Huấn luyện viên không trả lời được câu này. Hãy thử hỏi theo cách khác."
  )
  def unavailableLater = t(
    "The coach is unavailable right now. Try again later.",
    "Huấn luyện viên hiện không khả dụng. Hãy thử lại sau."
  )

  /** For analyse.aiCoach.ts. */
  def browser: JsObject = Json.obj(
    "thinking" -> t("Thinking…", "Đang suy nghĩ…"),
    "willAnalyse" -> t(
      "Your first question starts Stockfish's analysis of every move of the game, so its answer takes a little longer.",
      "Câu hỏi đầu tiên sẽ cho Stockfish phân tích mọi nước của ván, nên câu trả lời đầu tiên sẽ lâu hơn một chút."
    ),
    "analysing" -> t(
      "Stockfish is analysing every move of the game…",
      "Stockfish đang phân tích từng nước của ván…"
    ),
    "unavailable" -> t("The coach is unavailable right now.", "Huấn luyện viên hiện không khả dụng."),
    "tooMany" -> t("Too many questions today.", "Hôm nay bạn đã hỏi quá nhiều câu."),
    "interrupted" -> t("The answer was interrupted.", "Câu trả lời bị gián đoạn."),
    "error" -> t("Error.", "Lỗi.")
  )

object CoachText:

  def apply(lang: Lang): CoachText = new CoachText(lang.language == "vi")

  val en = new CoachText(false)
