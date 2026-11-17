package lila.aicoach

import java.time.Instant

import play.api.libs.json.*
import reactivemongo.api.bson.*
import reactivemongo.api.indexes.{ Index, IndexType }

import lila.db.BSON
import lila.db.dsl.{ *, given }
import lila.game.BSONHandlers.gameHandler

final class MongoStore(sessions: Coll, jobs: Coll)(using Executor) extends Store:

  private var cleanupCursor = ""

  private given BSON[StoredLesson] with
    def reads(r: BSON.Reader) = StoredLesson(
      Json.parse(r.str("data")).as[Lesson],
      r.getO[Game]("preparedGame")
    )
    def writes(w: BSON.Writer, s: StoredLesson) = bdoc(
      "_id" -> s.data.id,
      "gameId" -> s.data.gameId,
      "owner" -> s.data.owner,
      "userId" -> s.data.userId,
      "requestKey" -> s.data.requestKey,
      "active" -> s.data.active,
      "needsReconcile" -> s.data.needsReconcile,
      "summaryState" -> s.data.summary.map(_.state),
      "version" -> s.data.version,
      "reconciledAt" -> s.data.reconciledAt,
      "expiresAt" -> Instant.ofEpochMilli(s.data.expiresAt),
      "data" -> Json.stringify(Json.toJson(s.data)),
      "preparedGame" -> s.preparedGame
    )

  private given BSON[Task] with
    def reads(r: BSON.Reader) =
      Json.parse(r.str("data")).as[Task].copy(expiresAt = r.date("expiresAt").toEpochMilli)
    def writes(w: BSON.Writer, t: Task) = bdoc(
      "_id" -> t.id,
      "sessionId" -> t.sessionId,
      "kind" -> t.kind,
      "createdAt" -> t.createdAt,
      "version" -> t.version,
      "state" -> t.state,
      "leaseUntil" -> t.leaseUntil,
      "availableAt" -> t.availableAt,
      "published" -> t.published,
      "expiresAt" -> Instant.ofEpochMilli(t.expiresAt),
      "data" -> Json.stringify(Json.toJson(t))
    )

  /** Index creation is awaited before creating lessons or starting workers. */
  def ensureIndexes(): Funit =
    val indexes = List(
      sessions -> Index(Seq("gameId" -> IndexType.Ascending), name = Some("coach_game"), unique = true),
      sessions -> Index(
        Seq("owner" -> IndexType.Ascending, "requestKey" -> IndexType.Ascending),
        name = Some("coach_request"),
        unique = true
      ),
      sessions -> Index(
        Seq("owner" -> IndexType.Ascending),
        name = Some("coach_active_owner"),
        unique = true,
        partialFilter = Some(bdoc("active" -> true))
      ),
      sessions -> Index(
        Seq("expiresAt" -> IndexType.Ascending),
        name = Some("coach_session_ttl"),
        expireAfterSeconds = Some(0)
      ),
      sessions -> Index(Seq("reconciledAt" -> IndexType.Ascending), name = Some("coach_reconcile")),
      sessions -> Index(Seq("summaryState" -> IndexType.Ascending), name = Some("coach_summary")),
      jobs -> Index(
        Seq("expiresAt" -> IndexType.Ascending),
        name = Some("coach_job_ttl"),
        expireAfterSeconds = Some(0)
      ),
      jobs -> Index(
        Seq("state" -> IndexType.Ascending, "availableAt" -> IndexType.Ascending),
        name = Some("coach_queue")
      ),
      jobs -> Index(Seq("sessionId" -> IndexType.Ascending), name = Some("coach_job_session"))
    )
    indexes.traverse_((coll, index) => coll.indexesManager.ensure(index).void)

  def get(id: String) = sessions.byId[StoredLesson](id)
  def byRequest(owner: String, key: String) =
    sessions.one[StoredLesson](bdoc("owner" -> owner, "requestKey" -> key))
  def active(owner: String) = sessions.one[StoredLesson](bdoc("owner" -> owner, "active" -> true))
  def byGame(id: String) = sessions.one[StoredLesson](bdoc("gameId" -> id))
  def insert(lesson: StoredLesson): Fu[Boolean] =
    sessions.insert.one(lesson).map(_ => true).recover(lila.db.recoverDuplicateKey(_ => false))

  def save(before: StoredLesson, after: StoredLesson): Fu[Boolean] =
    sessions.update
      .one(bdoc("_id" -> before.data.id, "version" -> before.data.version), after)
      .map(_.n == 1)
      .recover(lila.db.recoverDuplicateKey(_ => false))

  def scan(now: Long, limit: Int) = sessions
    .find(
      bdoc("expiresAt" -> bdoc("$gt" -> Instant.ofEpochMilli(now)), "needsReconcile" -> true),
      none[Bdoc]
    )
    .sort(bdoc("reconciledAt" -> 1))
    .cursor[StoredLesson]()
    .list(limit)

  def removeUser(user: String): Funit =
    sessions
      .list[StoredLesson](bdoc("userId" -> user))
      .flatMap: lessons =>
        lessons.traverse_ { s =>
          // Remove the parent first. All publication uses a non-upserting CAS.
          sessions.delete
            .one(bid(s.data.id))
            .void
            .flatMap: _ =>
              jobs.delete.one(bdoc("sessionId" -> s.data.id), limit = None).void
        }

  def task(id: String) = jobs.byId[Task](id)
  def enqueue(task: Task) = jobs.insert
    .one(task.copy(createdAt = task.createdAt.orElse(Some(nowMillis))))
    .void
    .recover(lila.db.ignoreDuplicateKey)
  def saveTask(before: Task, after: Task): Fu[Boolean] =
    val doc = summon[BSON[Task]].write(after.copy(version = before.version + 1)) -- "_id" -- "expiresAt"
    jobs.update
      .one(
        bdoc("_id" -> before.id, "version" -> before.version),
        bdoc("$set" -> doc, "$max" -> bdoc("expiresAt" -> Instant.ofEpochMilli(after.expiresAt)))
      )
      .map(_.n == 1)

  def ready(now: Long, historyFirst: Boolean, limit: Int): Fu[List[Task]] =
    val query = bdoc(
      "expiresAt" -> bdoc("$gt" -> Instant.ofEpochMilli(now)),
      "$or" -> List(
        bdoc("state" -> "pending", "availableAt" -> bdoc("$lte" -> now)),
        bdoc("state" -> "running", "leaseUntil" -> bdoc("$lte" -> now))
      )
    )
    val preferred =
      if historyFirst then bdoc("kind" -> "analyseMove") else bdoc("kind" -> bdoc("$ne" -> "analyseMove"))
    jobs
      .find(query ++ preferred, none[Bdoc])
      .cursor[Task]()
      .list(limit)
      .flatMap:
        case Nil => jobs.find(query, none[Bdoc]).cursor[Task]().list(limit)
        case tasks => fuccess(tasks)

  def unpublished(now: Long, limit: Int) = jobs
    .find(
      bdoc(
        "expiresAt" -> bdoc("$gt" -> Instant.ofEpochMilli(now)),
        "published" -> false,
        "state" -> bdoc("$in" -> List("succeeded", "failed", "cancelled"))
      ),
      none[Bdoc]
    )
    .cursor[Task]()
    .list(limit)
  def tasks(sessionId: String) = jobs.list[Task](bdoc("sessionId" -> sessionId))
  def removeTask(id: String) = jobs.delete.one(bid(id)).void
  def extendTasks(sessionId: String, expiresAt: Long): Funit =
    jobs.update
      .one(
        bdoc("sessionId" -> sessionId),
        bdoc("$max" -> bdoc("expiresAt" -> Instant.ofEpochMilli(expiresAt))),
        multi = true
      )
      .void

  /** Bounded sweep also catches children inserted by an in-flight reconcile after UserDelete. */
  def cleanup(now: Long, limit: Int): Fu[Int] =
    for
      expired <- sessions
        .find(bdoc("expiresAt" -> bdoc("$lte" -> Instant.ofEpochMilli(now))), none[Bdoc])
        .cursor[StoredLesson]()
        .list(limit)
      _ <- expired.traverse_ { old =>
        sessions.delete
          .one(
            bdoc(
              "_id" -> old.data.id,
              "version" -> old.data.version,
              "expiresAt" -> bdoc("$lte" -> Instant.ofEpochMilli(now))
            )
          )
          .flatMap: deleted =>
            if deleted.n == 1 then jobs.delete.one(bdoc("sessionId" -> old.data.id), limit = None).void
            else funit
      }
      batch <- jobs
        .find(
          if cleanupCursor.isEmpty then emptyBdoc else bdoc("_id" -> bdoc("$gt" -> cleanupCursor)),
          none[Bdoc]
        )
        .sort(bdoc("_id" -> 1))
        .cursor[Task]()
        .list(limit)
      removed <- batch.traverse { task =>
        get(task.sessionId).flatMap:
          case Some(parent) if parent.data.valid(now) => fuccess(0)
          case _ => removeTask(task.id).map(_ => 1)
      }
    yield
      cleanupCursor = batch.lastOption.fold("")(_.id)
      removed.sum

  def metrics(now: Long): Fu[Map[String, Long]] =
    val states = List("pending", "running", "succeeded", "failed", "cancelled")
    val summaries = List("pending", "ready", "partial", "failed")
    for
      queue <- states.traverse(state =>
        jobs.countSel(bdoc("state" -> state)).map(n => s"tasks.$state" -> n.toLong)
      )
      summary <- summaries.traverse(state =>
        sessions.countSel(bdoc("summaryState" -> state)).map(n => s"summary.$state" -> n.toLong)
      )
      active <- sessions.countSel(bdoc("active" -> true))
      expiredLeases <- jobs.countSel(bdoc("state" -> "running", "leaseUntil" -> bdoc("$lte" -> now)))
      oldest <- jobs
        .find(bdoc("state" -> "pending"), none[Bdoc])
        .sort(bdoc("createdAt" -> 1))
        .cursor[Task]()
        .list(1)
    yield (queue ++ summary ++ List(
      "sessions.active" -> active.toLong,
      "leases.expired" -> expiredLeases.toLong,
      "queue.oldestMs" -> oldest.headOption.flatMap(_.createdAt).fold(0L)(t => (now - t).max(0))
    )).toMap
