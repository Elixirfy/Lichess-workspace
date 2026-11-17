package lila.aicoach

trait Store:
  def get(id: String): Fu[Option[StoredLesson]]
  def byRequest(owner: String, key: String): Fu[Option[StoredLesson]]
  def active(owner: String): Fu[Option[StoredLesson]]
  def byGame(id: String): Fu[Option[StoredLesson]]
  def insert(lesson: StoredLesson): Fu[Boolean]
  def save(before: StoredLesson, after: StoredLesson): Fu[Boolean]
  def scan(now: Long, limit: Int): Fu[List[StoredLesson]]
  def cleanup(now: Long, limit: Int): Fu[Int]
  def metrics(now: Long): Fu[Map[String, Long]]
  def removeUser(user: String): Funit
  def task(id: String): Fu[Option[Task]]
  def enqueue(task: Task): Funit
  def saveTask(before: Task, after: Task): Fu[Boolean]
  def ready(now: Long, historyFirst: Boolean, limit: Int): Fu[List[Task]]
  def unpublished(now: Long, limit: Int): Fu[List[Task]]
  def tasks(sessionId: String): Fu[List[Task]]
  def removeTask(id: String): Funit
  def extendTasks(sessionId: String, expiresAt: Long): Funit

final class SessionUpdates(store: Store)(using Executor):
  /** Pure transformation may be retried. No external effects inside f. */
  def apply(id: String)(f: Lesson => Lesson): Fu[Option[Lesson]] = change(id, 0): old =>
    old.copy(data = f(old.data))

  def change(id: String, retries: Int = 0)(f: StoredLesson => StoredLesson): Fu[Option[Lesson]] =
    store
      .get(id)
      .flatMap:
        case Some(old) if old.data.valid(nowMillis) =>
          val updated = f(old)
          if updated == old then fuccess(old.data.some)
          else
            val next = updated.copy(data = updated.data.copy(version = old.data.version + 1))
            store
              .save(old, next)
              .flatMap:
                if _ then fuccess(next.data.some)
                else if retries < 24 then change(id, retries + 1)(f)
                else fufail(CoachError("contention"))
        case _ => fuccess(None)
