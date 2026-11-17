package lila.mon

import kamon.Kamon.{ counter, gauge, histogram }

/** Bounded labels only: no session, game, owner, model output or credentials. */
object aiCoach:
  def attempt(kind: String, state: String, serviceMillis: Long): Unit =
    counter("aiCoach.attempt").withTags(Map("kind" -> kind, "state" -> state)).increment()
    histogram("aiCoach.service.ms").withTag("kind", kind).record(serviceMillis.max(0))

  def queue(kind: String, millis: Long): Unit =
    histogram("aiCoach.queue.ms").withTag("kind", kind).record(millis.max(0))

  def narration(kind: String, fallback: Boolean, tokens: Long, known: Boolean): Unit =
    counter("aiCoach.narration")
      .withTags(Map("kind" -> kind, "fallback" -> fallback.toString, "usageKnown" -> known.toString))
      .increment()
    if known then counter("aiCoach.tokens").withTag("kind", kind).increment(tokens.max(0))

  def inventory(values: Map[String, Long]): Unit = values.foreach: (name, value) =>
    gauge("aiCoach.inventory").withTag("item", name).update(value.toDouble)

  def cleaned(count: Int): Unit = counter("aiCoach.cleanup").withoutTags().increment(count.toLong)
