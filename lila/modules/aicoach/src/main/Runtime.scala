package lila.aicoach

import java.util.concurrent.atomic.AtomicInteger

import play.api.libs.json.*

trait AnalysisClient:
  def apply(input: JsObject): Fu[JsObject]

final class Runtime(
    store: Store,
    creator: Creator,
    getGame: GameId => Fu[Option[Game]],
    client: AnalysisClient,
    parallelism: Int = 1,
    leaseMillis: Long = 30000,
    maxAttempts: Int = 3,
    maxQuestions: Int = 128,
    idleMillis: Long = 86400000L,
    summaryWaitMillis: Long = 30000L
)(using Executor):
  private val updates = SessionUpdates(store)
  private val workers = AtomicInteger(0)
  private val polls = AtomicInteger(0)

  def reconcileAll(): Funit = store.scan(nowMillis, 32).flatMap(_.traverse_(s => reconcile(s.data)))

  def reconcile(s: Lesson): Funit =
    if Set("preparing", "starting")(s.phase) then
      creator.recover(s.id).void.recover { case _: CoachError => () }
    else
      getGame(GameId(s.gameId)).flatMap:
        case None => funit
        case Some(game) =>
          val plies = Snapshots.learnerPlies(s, game).filter(_ > s.enqueuedThrough)
          val history = plies.traverse_ { ply =>
            val revision = Snapshots.position(game, ply).revision
            val id = Snapshots.taskId(s.id, "analyseMove", revision)
            store.enqueue(
              Task(
                id,
                s.id,
                "analyseMove",
                revision,
                ply,
                0,
                Snapshots.input(s, game, "analyseMove", ply, 0, id),
                s.expiresAt,
                deadline = nowMillis + 86400000L
              )
            )
          }
          history
            .flatMap: _ =>
              s.interactions.traverse_(ensureInteraction(s, game, _))
            .flatMap: _ =>
              val revision = Snapshots.position(game, game.ply.value).revision
              updates(s.id) { current =>
                if game.ply.value < current.enqueuedThrough then current
                else
                  val lifecycle = Lifecycle.reconcile(
                    current,
                    game,
                    nowMillis,
                    idleMillis,
                    creator.retention(current.userId.isDefined)
                  )
                  val next = lifecycle.copy(
                    enqueuedThrough = current.enqueuedThrough.max(game.ply.value),
                    reconciledAt = nowMillis,
                    observedRevision = revision,
                    runningQuestion = lifecycle.runningQuestion.filter: id =>
                      current.interactions
                        .find(_.taskId == id)
                        .exists(i =>
                          i.kind == "explain" ||
                            (i.revision == revision && Snapshots.playable(current, game))
                        )
                  )
                  if current.observedRevision != revision || current.phase != next.phase then
                    next.withEvent(
                      Json.obj(
                        "type" -> "position",
                        "positionRevision" -> revision,
                        "ply" -> game.ply.value,
                        "status" -> game.status.name,
                        "phase" -> next.phase
                      )
                    )
                  else next
              }.flatMap(
                _.fold(funit)(saved =>
                  store
                    .extendTasks(saved.id, saved.expiresAt)
                    .flatMap(_ => refreshSummary(saved, game))
                )
              )

  def moveObserved(s: Lesson, game: Game): Funit =
    val learnerMoved = game.ply.value > 0 && ((game.ply.value % 2 == 1) == (s.learnerColor == "white"))
    val touch = if learnerMoved then
      updates(s.id): current =>
        val at = current.lastOwnerActivityAt.max(game.movedAt.toEpochMilli.min(nowMillis))
        current.copy(
          lastOwnerActivityAt = at,
          expiresAt = current.expiresAt.max(at + creator.retention(current.userId.isDefined))
        )
    else fuccess(Some(s))
    touch.flatMap(_.fold(funit)(reconcile))

  private def refreshSummary(s: Lesson, game: Game): Funit =
    if !Set("finished", "abandoned")(s.phase) then funit
    else
      store
        .tasks(s.id)
        .flatMap: tasks =>
          updates(s.id): current =>
            if !Set("finished", "abandoned")(current.phase) || current.enqueuedThrough > game.ply.value then
              current
            else
              val summary = Summary.build(current, game, tasks, nowMillis, summaryWaitMillis)
              if current.summary.contains(summary) then current
              else
                current
                  .copy(summary = Some(summary))
                  .withEvent(Json.obj("type" -> "summary", "state" -> summary.state))
          .void

  /** Explicit owner action. Reads, heartbeats and reconnects never resume a lesson. */
  def resume(id: String): Fu[Lesson] =
    store
      .get(id)
      .flatMap:
        case Some(stored) if stored.data.valid(nowMillis) =>
          store
            .active(stored.data.owner)
            .flatMap:
              case Some(other) if other.data.id != id && other.data.valid(nowMillis) =>
                fufail(CoachError("activeLessonExists"))
              case _ =>
                getGame(GameId(stored.data.gameId)).flatMap:
                  case Some(game) if game.playable && !game.position.end =>
                    updates(id): current =>
                      if !Set("active", "abandoned")(current.phase) then throw CoachError("resumeUnavailable")
                      current
                        .copy(
                          phase = "active",
                          summary = None,
                          lastOwnerActivityAt = nowMillis,
                          expiresAt = nowMillis + creator.retention(current.userId.isDefined)
                        )
                        .withEvent(Json.obj("type" -> "resumed"))
                    .flatMap:
                      case Some(saved) => store.extendTasks(id, saved.expiresAt).map(_ => saved)
                      case _ => fufail(CoachError("sessionExpired"))
                  case _ => fufail(CoachError("resumeUnavailable"))
        case _ => fufail(CoachError("sessionExpired"))

  private def ensureInteraction(s: Lesson, game: Game, i: Interaction): Funit =
    store
      .task(i.taskId)
      .flatMap:
        case Some(_) => funit
        case None if !s.completed.contains(i.taskId) =>
          val input = Snapshots.input(s, game, i.kind, i.ply, i.level, i.taskId)
          store.enqueue(
            Task(
              i.taskId,
              s.id,
              i.kind,
              i.revision,
              i.ply,
              i.level,
              input,
              s.expiresAt,
              deadline = nowMillis + 30000
            )
          )
        case _ => funit

  def question(id: String, q: Question): Fu[Interaction] =
    store
      .get(id)
      .flatMap:
        case Some(s) =>
          getGame(GameId(s.data.gameId)).flatMap:
            case Some(game) =>
              updates(id)(QuestionRules.reserve(_, game, q, nowMillis, maxQuestions, creator.retention))
                .flatMap:
                  case Some(updated) =>
                    val interaction = updated.interactions.find(_.key == q.requestKey).get
                    store
                      .extendTasks(updated.id, updated.expiresAt)
                      .flatMap(_ => ensureInteraction(updated, game, interaction))
                      .map(_ => interaction)
                  case _ => fufail(CoachError("sessionExpired"))
            case _ => fufail(CoachError("gameUnavailable"))
        case _ => fufail(CoachError("sessionExpired"))

  def tick(): Funit =
    store
      .unpublished(nowMillis, 32)
      .flatMap(_.traverse_(publish))
      .flatMap: _ =>
        val free = parallelism - workers.get()
        if free <= 0 then funit
        else
          store
            .ready(nowMillis, polls.incrementAndGet() % 4 == 0, free)
            .flatMap:
              _.traverse_ { task =>
                if workers.incrementAndGet() > parallelism then
                  workers.decrementAndGet()
                  funit
                else run(task).andThen { case _ => workers.decrementAndGet() }
              }

  def run(task: Task): Funit =
    val now = nowMillis
    if task.expiresAt <= now || (task.state == "running" && task.leaseUntil > now) then funit
    else if task.attempts >= maxAttempts || task.deadline <= now then
      store.saveTask(task, task.copy(state = "failed", error = Some("retryExhausted"))).void
    else
      val started = nowMillis
      task.createdAt.foreach(created => lila.mon.aiCoach.queue(task.kind, started - created))
      val claimed = task.copy(
        state = "running",
        version = task.version + 1,
        token = Identity.random,
        attempts = task.attempts + 1,
        leaseUntil = now + leaseMillis
      )
      store
        .saveTask(task, claimed)
        .flatMap:
          case false => funit
          case true =>
            validTarget(claimed).flatMap:
              case false => store.saveTask(claimed, claimed.copy(state = "cancelled")).void
              case true =>
                client(claimed.input)
                  .flatMap: result =>
                    PublicCard.verify(claimed, result)
                    lila.mon.aiCoach.attempt(task.kind, "received", nowMillis - started)
                    val narration = result \ "narration"
                    (narration \ "fallback")
                      .asOpt[Boolean]
                      .foreach: fallback =>
                        val tokens = (narration \ "promptTokens").asOpt[Long].getOrElse(0L) +
                          (narration \ "completionTokens").asOpt[Long].getOrElse(0L)
                        lila.mon.aiCoach.narration(
                          task.kind,
                          fallback,
                          tokens,
                          (narration \ "usageKnown").asOpt[Boolean].contains(true)
                        )
                    validTarget(claimed).flatMap:
                      case true if claimed.leaseUntil > nowMillis =>
                        store
                          .saveTask(
                            claimed,
                            claimed.copy(
                              state = "succeeded",
                              result = Some(
                                result + ("lilaTimings" -> Json.obj(
                                  "queueMs" -> task.createdAt.map(created => (started - created).max(0)),
                                  "serviceMs" -> (nowMillis - started).max(0)
                                ))
                              )
                            )
                          )
                          .flatMap(saved =>
                            if saved then store.task(task.id).flatMap(_.fold(funit)(publish)) else funit
                          )
                      case _ => store.saveTask(claimed, claimed.copy(state = "cancelled")).void
                  .recoverWith:
                    case _ =>
                      lila.mon.aiCoach.attempt(task.kind, "failed", nowMillis - started)
                      store
                        .saveTask(
                          claimed,
                          claimed.copy(
                            state = if claimed.attempts >= maxAttempts then "failed" else "pending",
                            availableAt = nowMillis + (1000L << claimed.attempts),
                            error = Some("analysisUnavailable")
                          )
                        )
                        .void

  private def validTarget(task: Task): Fu[Boolean] = store
    .get(task.sessionId)
    .flatMap:
      case Some(s) if s.data.valid(nowMillis) =>
        if Set("analyseMove", "explain")(task.kind) then fuTrue
        else
          getGame(GameId(s.data.gameId)).map:
            _.exists: game =>
              s.data.phase == "active" && Snapshots.playable(s.data, game) &&
                Snapshots.position(game, game.ply.value).revision == task.revision &&
                game.status.name == (task.input \ "snapshot" \ "status").as[String]
      case _ => fuFalse

  def publish(task: Task): Funit =
    updates(task.sessionId): s =>
      if s.completed.contains(task.id) then s
      else
        val candidate = task.result.map(PublicCard.verify(task, _))
        val selected = task.kind != "analyseMove" || s.config.support == "proactive"
        val card = candidate.filter(_ => selected)
        s.copy(
          completed = s.completed :+ task.id,
          cards = s.cards ++ card.toList,
          runningQuestion = s.runningQuestion.filterNot(_ == task.id),
          lastProactivePly =
            if card.isDefined && task.kind == "analyseMove" then task.ply else s.lastProactivePly
        ).withEvent(
          Json.obj(
            "type" -> "result",
            "taskId" -> task.id,
            "kind" -> task.kind,
            "positionRevision" -> task.revision,
            "state" -> task.state,
            "card" -> card
          )
        )
    .flatMap:
      case Some(_) => store.saveTask(task, task.copy(published = true, publishedAt = Some(nowMillis))).void
      case None => store.removeTask(task.id)
