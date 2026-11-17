package lila.aicoach

import play.api.libs.json.*

object Feed:
  def after(s: Lesson, cursor: Long, revision: String, status: String): List[CoachEvent] =
    if cursor > s.cursor || cursor < s.events.headOption.map(_.id - 1).getOrElse(s.cursor) then
      List(CoachEvent(s.cursor, Json.obj("type" -> "reset", "reload" -> true)))
    else
      s.events
        .filter(_.id > cursor)
        .map: event =>
          val data = (event.data \ "card").asOpt[JsObject] match
            case Some(card) if !PublicCard.visible(card, revision, status, s.phase) =>
              event.data + ("card" -> JsNull)
            case _ => event.data
          event.copy(data = data)

  def encode(event: CoachEvent): String =
    s"id: ${event.id}\nevent: coach\ndata: ${Json.stringify(event.data)}\n\n"
