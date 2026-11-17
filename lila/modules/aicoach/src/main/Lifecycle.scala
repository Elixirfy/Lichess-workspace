package lila.aicoach

object Lifecycle:
  def reconcile(s: Lesson, game: Game, now: Long, idleMillis: Long, retention: Long): Lesson =
    val newLearnerMove = Snapshots.learnerPlies(s, game).exists(_ > s.enqueuedThrough)
    // Game timestamp is used when replay catches a missed event; polling itself
    // never counts as owner activity, nor does a late AI move on its own.
    val activity = if newLearnerMove then s.lastOwnerActivityAt.max(game.movedAt.toEpochMilli.min(now))
    else s.lastOwnerActivityAt
    val finished = game.finishedOrAborted
    val phase = if finished then "finished"
    else if s.phase == "active" && now - activity >= idleMillis then "abandoned"
    else s.phase
    val endedAt = if finished then s.finishedAt.orElse(Some(now)) else s.finishedAt
    s.copy(
      phase = phase,
      lastOwnerActivityAt = activity,
      expiresAt = s.expiresAt.max(activity + retention).max(endedAt.fold(0L)(_ + retention)),
      finishedAt = endedAt
    )
