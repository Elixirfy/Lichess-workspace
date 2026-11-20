package lila.aiCoach

class CoachLlmTest extends munit.FunSuite:

  test("replies lose reasoning blocks and markup tags, keeping the text"):
    val raw = """<think>scratch work</think>Your opponent was more accurate.

<box border radius="lg" padding={3}>
  <title size="xl">Accuracy</title>
  <badge color="danger">50%</badge>
</box>

**5. Nxf7** lost the game. White's chances fell below 20%."""
    assertEquals(
      CoachLlm.clean(raw),
      """Your opponent was more accurate.

Accuracy
  50%

**5. Nxf7** lost the game. White's chances fell below 20%."""
    )
