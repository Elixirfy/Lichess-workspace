package lila.tilt

import reactivemongo.api.bson.*

import TiltGame.{ Fast, Level, Pred, Response, Rules, Sign }
import TiltBanner.{ Reason, State }

class TiltGameTest extends munit.FunSuite:

  private val now = nowInstant

  private def game(n: Int, pred: Option[Pred], err: Option[String] = None, minutesAgo: Int = 0) =
    TiltGame
      .make(GameId(f"game$n%04d"), UserId("player"), Color.white, "blitz")
      .copy(
        queuedAt = now.minusSeconds(minutesAgo * 60L),
        response = (pred.isDefined || err.isDefined).option(Response(now, pred, err))
      )

  private def scored(n: Int, flag: Boolean) = game(n, Pred(if flag then 80 else 20, flag, Nil).some)

  private def rules(context: String, label: String) =
    Rules(label, context, Nil, Nil, Nil)

  private def v3(
      level: Level,
      context: String = "none",
      label: String = "ABSTAIN",
      signs: List[String] = Nil
  ) =
    val prob = level match
      case Level.Low => .05
      case Level.Attention => .2
      case Level.High => .4
    Pred(
      (prob * 100).toInt,
      level == Level.High,
      signs,
      v = 3.some,
      prob = prob.some,
      level = level.key.some,
      head = "p20".some,
      signs = signs.map(Sign(_, .5)).some,
      rules = rules(context, label).some
    )

  private def at(n: Int, minutesAgo: Int, pred: Pred) = game(n, pred.some, minutesAgo = minutesAgo)

  test("flagged run counts flagged games from the newest one"):
    val games = List(scored(5, true), scored(4, true), scored(3, true), scored(2, false), scored(1, true))
    assertEquals(TiltGame.flaggedRun(games), 3)

  test("games not scored yet do not break the run, a calm game does"):
    val games =
      List(game(6, None), scored(5, true), game(4, None, "no clock".some), scored(3, true), scored(2, false))
    assertEquals(TiltGame.flaggedRun(games), 2)
    assertEquals(TiltGame.flaggedRun(List(scored(2, false), scored(1, true))), 0)

  test("a warning from three flagged games in a row"):
    val g = scored(1, true)
    assert(!TiltGame.WithRun(g, 2).warn)
    assert(TiltGame.WithRun(g, 3).warn)

  test("queued games carry their speed"):
    assertEquals(game(1, None).speed, "blitz".some)

  test("only M-v3 scores have a level"):
    assertEquals(at(1, 0, v3(Level.High)).level, Level.High.some)
    assertEquals(scored(1, true).level, none)
    assertEquals(scored(1, true).v3, none)

  test("worker documents read back, old and new, null fields as absent"):
    import TiltApi.given
    val newDoc = BSONDocument(
      "_id" -> "abcdefghw",
      "gameId" -> "abcdefgh",
      "userId" -> "player",
      "color" -> true,
      "queuedAt" -> BSONDateTime(now.toEpochMilli),
      "speed" -> "blitz",
      "response" -> BSONDocument(
        "at" -> BSONDateTime(now.toEpochMilli),
        "pred" -> BSONDocument(
          "score" -> 41,
          "flag" -> true,
          "factors" -> BSONArray("session"),
          "v" -> 3,
          "prob" -> 0.4123,
          "level" -> "high",
          "head" -> "p20",
          "signs" -> BSONArray(BSONDocument("family" -> "session", "share" -> 0.5)),
          "fast" -> BSONDocument("z" -> -2.1, "zTrim" -> -1.4, "games" -> 36),
          "rules" -> BSONDocument(
            "label" -> "TILT",
            "context" -> "strong",
            "fired" -> BSONArray("C1", "E1", "E2"),
            "missing" -> BSONArray(),
            "pending" -> BSONArray("E7"),
            "reason" -> BSONNull
          )
        ),
        "shadow" -> BSONDocument("model" -> "P3-B", "score" -> 20, "flag" -> false)
      )
    )
    val g = newDoc.asTry[TiltGame].get
    val pred = g.pred.get
    assertEquals(g.level, Level.High.some)
    assertEquals(pred.signs, List(Sign("session", 0.5)).some)
    assertEquals(pred.fast, Fast(-2.1, -1.4, 36).some)
    assertEquals(pred.rules.map(_.pending), List("E7").some)
    assertEquals(pred.rules.flatMap(_.reason), none)
    val skipped =
      (newDoc -- "response") ++ BSONDocument(
        "response" -> BSONDocument("at" -> BSONDateTime(0), "skip" -> "speed")
      )
    assertEquals(skipped.asTry[TiltGame].get.skip, "speed".some)
    val old = BSONDocument(
      "_id" -> "abcdefghb",
      "gameId" -> "abcdefgh",
      "userId" -> "player",
      "color" -> false,
      "queuedAt" -> BSONDateTime(now.toEpochMilli),
      "response" -> BSONDocument(
        "at" -> BSONDateTime(now.toEpochMilli),
        "pred" -> BSONDocument("score" -> 74, "flag" -> true, "factors" -> BSONArray("attack_rate"))
      )
    )
    val o = old.asTry[TiltGame].get
    assertEquals(o.speed, none)
    assertEquals(o.pred.map(_.score), 74.some)
    assertEquals(o.v3, none)

  test("banner after two high games in a row of the same session"):
    val games = List(at(2, 5, v3(Level.High)), at(1, 20, v3(Level.High)))
    assertEquals(TiltBanner.decide(TiltBanner.noState, games, now, playing = false), Reason.TwoHigh.some)
    // the previous game belongs to an earlier session
    val apart = List(at(2, 5, v3(Level.High)), at(1, 40, v3(Level.High)))
    assertEquals(TiltBanner.decide(TiltBanner.noState, apart, now, playing = false), none)
    // a game of another speed or one not scored yet is no break
    val skipped = game(3, None, minutesAgo = 2).copy(response = Response(now, None, None, "speed".some).some)
    assertEquals(
      TiltBanner.decide(TiltBanner.noState, skipped :: games, now, playing = false),
      Reason.TwoHigh.some
    )

  test("banner after one high game with a strong context"):
    val strong = List(at(2, 5, v3(Level.High, "strong")), at(1, 20, v3(Level.Low)))
    assertEquals(TiltBanner.decide(TiltBanner.noState, strong, now, playing = false), Reason.AfterLosses.some)
    val weak = List(at(2, 5, v3(Level.High, "weak")), at(1, 20, v3(Level.Attention)))
    assertEquals(TiltBanner.decide(TiltBanner.noState, weak, now, playing = false), none)
    val attention = List(at(2, 5, v3(Level.Attention, "strong")), at(1, 20, v3(Level.High)))
    assertEquals(TiltBanner.decide(TiltBanner.noState, attention, now, playing = false), none)

  test("no banner long after the session, during a game, or after opting out"):
    val old = List(at(2, 45, v3(Level.High)), at(1, 50, v3(Level.High)))
    assertEquals(TiltBanner.decide(TiltBanner.noState, old, now, playing = false), none)
    val games = List(at(2, 5, v3(Level.High)), at(1, 20, v3(Level.High)))
    assertEquals(TiltBanner.decide(TiltBanner.noState, games, now, playing = true), none)
    assertEquals(TiltBanner.decide(State(None, true), games, now, playing = false), none)

  test("banner at most once per session and 30 minutes apart"):
    // a session of 41 minutes; shown 35 minutes ago, during this session
    val games =
      List(
        at(4, 2, v3(Level.High)),
        at(3, 15, v3(Level.High)),
        at(2, 28, v3(Level.High)),
        at(1, 41, v3(Level.Low))
      )
    val shownThisSession = State(now.minusSeconds(35 * 60).some, false)
    assertEquals(TiltBanner.decide(shownThisSession, games, now, playing = false), none)
    assertEquals(
      TiltBanner.decide(State(now.minusSeconds(45 * 60).some, false), games, now, false),
      Reason.TwoHigh.some
    )
    // shown before this session started, but only 20 minutes ago
    val recent = List(at(2, 2, v3(Level.High)), at(1, 10, v3(Level.High)))
    assertEquals(TiltBanner.decide(State(now.minusSeconds(20 * 60).some, false), recent, now, false), none)
    // shown before this session and long enough ago
    assertEquals(
      TiltBanner.decide(State(now.minusSeconds(40 * 60).some, false), recent, now, false),
      Reason.TwoHigh.some
    )

  test("statistics count M-v3 games only"):
    val games = List(
      at(5, 1, v3(Level.High, label = "TILT", signs = List("session", "previous"))),
      at(4, 2, v3(Level.Attention, label = "NOT", signs = List("session"))),
      at(3, 3, v3(Level.Low, label = "ABSTAIN")),
      at(2, 4, v3(Level.Low, label = "NOT")),
      scored(1, true),
      game(0, None, "game not available".some)
    )
    val s = TiltStats.of(games)
    assertEquals(s.games, 4)
    assertEquals(s.levels, Map(Level.High -> 1, Level.Attention -> 1, Level.Low -> 2))
    assertEquals(s.share(Level.Low), 0.5)
    assertEquals((s.ruleTilt, s.ruleDecided), (1, 3))
    assertEquals(s.signs, List("session" -> 2, "previous" -> 1))
    assertEquals(TiltStats.lastGames(games, 2).games, 2)
    val month = TiltStats.lastDays(games :+ at(9, 60 * 24 * 40, v3(Level.High)), 30, now)
    assertEquals(month.games, 4)
    assertEquals(TiltStats.of(Nil).share(Level.High), 0.0)

  test("texts exist in both languages"):
    for t <- List(TiltText.en, TiltText.vi) do
      for f <- t.families do assertNotEquals(t.family(f), f.replace('_', ' '), f)
      for r <- t.rules do assertNotEquals(t.rule(r), r, r)
      for l <- Level.values do assert(t.level(l).nonEmpty)
    assertNotEquals(TiltText.en.intro, TiltText.vi.intro)
    assertEquals(TiltText.vi.family("session"), "kết quả các ván trước trong phiên")
    assertEquals(TiltText.en.rule("E7"), "started a new game right after a loss")

  test("player texts use plain words"):
    val fast = Fast(-2.1, -1.4, 36)
    assert(TiltText.vi.fast(fast).contains("so với 36 ván blitz gần nhất"))
    assertEquals(TiltText.en.percent(0.256), "26%")
    assertEquals(TiltText.vi.ruleTiltShare(0, 0), "Xét lại sau ván: chưa có ván nào đủ rõ để kết luận")
    assertEquals(
      TiltText.vi.ruleTiltShare(1, 3),
      "Xét lại sau ván: có dấu hiệu tilt ở 1 trong 3 ván đủ rõ để kết luận"
    )
    val jargon = List("mô hình", "nửa nước", "model", "plies", " ply", "v3", "z =", "luật", "rule")
    for t <- List(TiltText.en, TiltText.vi) do
      val shown =
        List(t.signsTitle, t.signsNone, t.fast(fast), t.rulesTitle, t.preOnly, t.intro, t.topSigns) ++
          t.families.map(t.family) ++ List("TILT", "NOT", "ABSTAIN").map(t.ruleLabel) ++
          List(t.ruleTiltShare(1, 2), t.ruleTiltShare(0, 0), t.ruleShort, t.signsShort, t.olderModel)
      for text <- shown; word <- jargon do assert(!text.toLowerCase.contains(word), s"$word in: $text")

  test("model features of the previous model in words"):
    assertEquals(ui.TiltUi.factorName("attack_rate"), "attacking moves")
    assertEquals(ui.TiltUi.factorName("baseline_speed_games"), "games at this speed in your history")
    assertEquals(ui.TiltUi.factorName("deviation_risk_rate_z"), "risky moves compared with your usual games")
    assertEquals(
      ui.TiltUi.factorName("baseline_attack_rate_games"),
      "how many of your past games show your usual attacking moves"
    )
    assertEquals(ui.TiltUi.factorName("baseline_risk_rate_median"), "your usual risky moves")
    assertEquals(ui.TiltUi.factorName("new_feature_x"), "new feature x")
