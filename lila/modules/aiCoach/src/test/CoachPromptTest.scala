package lila.aiCoach

class CoachPromptTest extends munit.FunSuite:

  test("the question after the viewed move and, for Vietnamese, the answer language"):
    assertEquals(
      CoachPrompt.question("Why was this a mistake?", "4. Nxe5".some),
      "[Viewing the position after 4. Nxe5]\nWhy was this a mistake?"
    )
    assertEquals(CoachPrompt.question("Why was this a mistake?", None), "Why was this a mistake?")
    assertEquals(
      CoachPrompt.question("Vì sao nước này là sai lầm?", "4. Nxe5".some),
      "[Viewing the position after 4. Nxe5]\n[Answer in Vietnamese]\nVì sao nước này là sai lầm?"
    )
    assertEquals(CoachPrompt.question("ĐÂY LÀ GÌ", None), "[Answer in Vietnamese]\nĐÂY LÀ GÌ")
    // without diacritics the model is left to tell the language
    assertEquals(CoachPrompt.question("sai lam lon nhat la gi", None), "sai lam lon nhat la gi")
