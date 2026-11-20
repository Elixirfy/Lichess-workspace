package lila.aiCoach

import play.api.i18n.Lang

class CoachTextTest extends munit.FunSuite:

  test("Vietnamese for a vi site language, English otherwise"):
    assert(CoachText(Lang("vi", "VN")).vi)
    assert(!CoachText(Lang("en", "GB")).vi)
    assert(!CoachText(Lang("fr", "FR")).vi)
    assertEquals(CoachText(Lang("vi", "VN")).ask, "Hỏi")
    assertEquals(CoachText(Lang("en", "US")).ask, "Ask")

  test("both languages have the same suggestions and browser texts"):
    val (vi, en) = (CoachText(Lang("vi", "VN")), CoachText(Lang("en", "US")))
    assertEquals(vi.suggestions.size, en.suggestions.size)
    assertEquals(vi.browser.keys, en.browser.keys)
    assert(vi.browser.keys.contains("analysing") && vi.browser.keys.contains("willAnalyse"))
    for (a, b) <- List(
        vi.analysisBusy -> en.analysisBusy,
        vi.analysisLimited -> en.analysisLimited,
        vi.analysisImpossible -> en.analysisImpossible,
        vi.analysisFailed -> en.analysisFailed
      )
    do assert(a.nonEmpty && b.nonEmpty && a != b)
    assert(vi.limited.contains(AiCoachApi.maxTurns.toString))
