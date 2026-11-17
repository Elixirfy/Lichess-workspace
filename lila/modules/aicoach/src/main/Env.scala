package lila.aicoach

import play.api.Configuration
import play.api.libs.json.*
import play.api.libs.ws.JsonBodyWritables.*
import play.api.libs.ws.StandaloneWSClient

import lila.common.{ Bus, LilaScheduler }
import lila.core.config.CollName

final class Env(
    config: Configuration,
    db: lila.db.Db,
    gameRepo: lila.core.game.GameRepo,
    onStart: lila.core.game.OnStart,
    proxy: lila.core.game.GameProxy,
    ws: StandaloneWSClient
)(using Executor, Scheduler):
  val enabled = config.getOptional[Boolean]("aiCoach.enabled").getOrElse(false)
  private val token = config.getOptional[String]("aiCoach.internalToken").getOrElse("")
  private val url = config.getOptional[String]("aiCoach.workerUrl").getOrElse("http://127.0.0.1:8137")
  private val concurrency = config.getOptional[Int]("aiCoach.parallelism").getOrElse(1)
  private val guestDays = config.getOptional[Int]("aiCoach.guestRetentionDays").getOrElse(7)
  private val accountDays = config.getOptional[Int]("aiCoach.accountRetentionDays").getOrElse(30)
  private val questionBudget = config.getOptional[Int]("aiCoach.maxQuestions").getOrElse(128)
  private val idleHours = config.getOptional[Int]("aiCoach.abandonAfterHours").getOrElse(24)
  private val summaryWait = config.getOptional[Int]("aiCoach.summaryWaitSeconds").getOrElse(30)
  require(
    (1 to 720).contains(idleHours) && (1 to 600).contains(summaryWait),
    "invalid coach lifecycle limits"
  )
  require(
    !enabled || (token.length >= 32 && concurrency >= 1 && concurrency <= 8),
    "invalid coach worker config"
  )
  require(
    !enabled || ((1 to 365).contains(guestDays) && (1 to 365).contains(accountDays) &&
      questionBudget >= 1 && questionBudget <= 1024),
    "invalid coach retention/question limit"
  )

  lazy val store = MongoStore(db(CollName("ai_coach_session")), db(CollName("ai_coach_task")))
  lazy val creator = Creator(store, gameRepo, onStart, guestDays, accountDays)
  private var initialization: Option[Funit] = None
  def ready: Funit = synchronized:
    if !enabled then fufail(CoachError("disabled"))
    else
      initialization.getOrElse:
        val result = store.ensureIndexes()
        initialization = Some(result)
        result.failed.foreach(_ => synchronized { initialization = None })
        result

  private val client = new AnalysisClient:
    def apply(input: JsObject): Fu[JsObject] =
      ws.url(s"${url.stripSuffix("/")}/analyse")
        .addHttpHeaders("Authorization" -> s"Bearer $token")
        .withRequestTimeout(12.seconds)
        .post(input)
        .flatMap: response =>
          if response.status != 200 || response.body.length > 262144 then
            fufail(CoachError("workerUnavailable"))
          else fuccess(Json.parse(response.body).as[JsObject])

  lazy val runtime = Runtime(
    store,
    creator,
    id => proxy.game(id).orElse(gameRepo.game(id)),
    client,
    parallelism = concurrency,
    maxQuestions = questionBudget,
    idleMillis = idleHours.toLong * 3600000L,
    summaryWaitMillis = summaryWait.toLong * 1000L
  )

  def observe(s: Lesson): Unit =
    if enabled then runtime.reconcile(s)

  if enabled then
    LilaScheduler("aicoach.reconcile", _.Every(2.seconds), _.AtMost(20.seconds), _.Delay(1.second)):
      ready.flatMap: _ =>
        store
          .scan(nowMillis, 32)
          .flatMap:
            _.traverse_ { stored =>
              runtime.reconcile(stored.data)
            }
    LilaScheduler("aicoach.work", _.Every(1.second), _.AtMost(20.seconds), _.Delay(1.second)):
      ready.flatMap(_ => runtime.tick())
    LilaScheduler("aicoach.maintenance", _.Every(10.seconds), _.AtMost(20.seconds), _.Delay(5.seconds)):
      ready
        .flatMap(_ => store.cleanup(nowMillis, 32))
        .flatMap: count =>
          lila.mon.aiCoach.cleaned(count)
          store.metrics(nowMillis).map(lila.mon.aiCoach.inventory)
    Bus.sub[lila.core.game.FinishGame]: finish =>
      store.byGame(finish.game.id.value).foreach(_.foreach(s => runtime.reconcile(s.data)))
    Bus.subscribeFunDyn(lila.game.actorApi.MoveGameEvent.coachChan):
      case event: lila.game.actorApi.MoveGameEvent =>
        store.byGame(event.game.id.value).foreach(_.foreach(s => runtime.moveObserved(s.data, event.game)))
  Bus.sub[lila.core.user.UserDelete](event => store.removeUser(event.id.value))
