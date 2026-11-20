package lila.aiCoach

import com.anthropic.client.AnthropicClientAsync
import com.anthropic.client.okhttp.AnthropicOkHttpClientAsync
import com.anthropic.core.http.AsyncStreamResponse
import com.anthropic.helpers.MessageAccumulator
import com.anthropic.models.messages.{
  CacheControlEphemeral,
  Message,
  MessageCreateParams,
  OutputConfig,
  RawMessageStreamEvent,
  StopReason,
  TextBlockParam
}
import org.apache.pekko.stream.Materializer
import org.apache.pekko.stream.scaladsl.{ Framing, Source }
import org.apache.pekko.util.ByteString
import play.api.ConfigLoader
import play.api.libs.json.*
import play.api.libs.ws.JsonBodyWritables.*
import play.api.libs.ws.{ StandaloneWSClient, StandaloneWSResponse }

import scala.jdk.CollectionConverters.*
import scala.jdk.OptionConverters.*
import scala.util.Try

import lila.common.autoconfig.AutoConfig
import lila.common.config.given
import lila.core.config.Secret

/** Sends one coaching turn to the configured model and streams the answer back as it is written. Two wire
  * formats, picked by `aiCoach.provider`:
  *   - "anthropic": Claude through the official Anthropic Java SDK
  *   - "openai": any OpenAI-compatible chat completions endpoint (OpenAI, Together, vLLM serving a fine-tuned
  *     model, ...), streamed as server-sent events, or read whole if the server ignores `stream`
  * Swapping the model, including for a fine-tuned one, is a config change.
  */
final class CoachLlm(ws: StandaloneWSClient, config: CoachLlm.Config)(using Executor, Materializer):

  import CoachLlm.*

  def enabled = config.apiKey.value.nonEmpty

  /** Text deltas as the model writes them, then the whole cleaned reply. `history` holds earlier (question,
    * answer) pairs, oldest first.
    */
  def stream(facts: String, history: List[(String, String)], question: String): Source[Event, ?] =
    // a monotonic clock: the wall clock can step while an answer is written
    val start = System.nanoTime()
    def elapsed = ((System.nanoTime() - start) / 1_000_000).toInt
    val events = config.provider match
      case "anthropic" => anthropic(facts, history, question)
      case "openai" => openAi(facts, history, question)
      case other => Source.failed(Exception(s"Unknown aiCoach.provider: $other"))
    events
      .filter:
        case Event.Delta(text) => text.nonEmpty
        case _ => true
      .statefulMap(() => none[Int])(
        (first, event) =>
          event match
            case Event.Delta(_) => (first.orElse(elapsed.some), event)
            case Event.Done(r) =>
              val total = elapsed
              (first, Event.Done(r.copy(text = clean(r.text), millis = total, firstMillis = first | total))),
        _ => none
      )

  private lazy val claude: AnthropicClientAsync =
    val builder = AnthropicOkHttpClientAsync
      .builder()
      .apiKey(config.apiKey.value)
      .timeout(java.time.Duration.ofSeconds(timeoutSeconds))
    config.url.nonEmptyOption.fold(builder)(url => builder.baseUrl(url)).build()

  private def anthropic(facts: String, history: List[(String, String)], question: String): Source[Event, ?] =
    val base = MessageCreateParams
      .builder()
      .model(config.model)
      .maxTokens(config.maxTokens.toLong)
      .systemOfTextBlockParams(
        List(CoachPrompt.system, facts).map(TextBlockParam.builder().text(_).build()).asJava
      )
      // caches system + facts + earlier turns, so follow-up questions are cheap
      .cacheControl(CacheControlEphemeral.builder().build())
    val withEffort = config.effort.nonEmptyOption.fold(base): effort =>
      base.outputConfig(OutputConfig.builder().effort(OutputConfig.Effort.of(effort)).build())
    val params = history
      .foldLeft(withEffort):
        case (b, (q, a)) => b.addUserMessage(q).addAssistantMessage(a)
      .addUserMessage(question)
      .build()
    Source
      .queue[Event](bufferSize)
      .mapMaterializedValue: queue =>
        val accumulator = MessageAccumulator.create()
        claude
          .messages()
          .createStreaming(params)
          .subscribe(new AsyncStreamResponse.Handler[RawMessageStreamEvent]:
            def onNext(event: RawMessageStreamEvent): Unit =
              accumulator.accumulate(event)
              event
                .contentBlockDelta()
                .toScala
                .flatMap(_.delta().text().toScala)
                .foreach(d => queue.offer(Event.Delta(d.text())))
            override def onComplete(error: java.util.Optional[Throwable]): Unit =
              error.toScala.orElse(Try(accumulator.message()).failed.toOption) match
                case Some(e) => queue.fail(e)
                case None =>
                  queue.offer(Event.Done(anthropicReply(accumulator.message())))
                  queue.complete())
      // stops the HTTP stream when the browser goes away
      .watchTermination()((stream, done) => done.onComplete(_ => stream.close()))

  private def anthropicReply(msg: Message) =
    val usage = msg.usage()
    val refused = msg.stopReason().toScala.contains(StopReason.REFUSAL)
    Reply(
      text = refused.not.so(msg.content().asScala.flatMap(_.text().toScala).map(_.text()).mkString.trim),
      model = msg.model().asString(),
      usage = Usage(
        input = usage.inputTokens().toInt,
        output = usage.outputTokens().toInt,
        cacheRead = usage.cacheReadInputTokens().toScala.fold(0)(_.toInt),
        cacheWrite = usage.cacheCreationInputTokens().toScala.fold(0)(_.toInt)
      )
    )

  private def openAi(facts: String, history: List[(String, String)], question: String): Source[Event, ?] =
    def msg(role: String, content: String) = Json.obj("role" -> role, "content" -> content)
    val messages = msg("system", s"${CoachPrompt.system}\n\n$facts") ::
      history.flatMap((q, a) => List(msg("user", q), msg("assistant", a))) :::
      List(msg("user", question))
    val body = Json.obj(
      "model" -> config.model,
      "max_tokens" -> config.maxTokens,
      "messages" -> messages,
      "stream" -> true,
      "stream_options" -> Json.obj("include_usage" -> true)
    )
    def post(timeout: FiniteDuration) =
      ws.url(config.url.nonEmptyOption | "https://api.openai.com/v1/chat/completions")
        .withHttpHeaders(
          "Authorization" -> s"Bearer ${config.apiKey.value}",
          "Content-Type" -> "application/json",
          "Accept" -> "text/event-stream, application/json"
        )
        .withRequestTimeout(timeout)
        .withMethod("POST")
        .withBody(body)
        .stream()
    val start = nowMillis
    Source.futureSource:
      post(timeoutSeconds.seconds)
        .flatMap: rsp =>
          // like the Anthropic SDK, retry a failed call once, within the same time budget; a proxy
          // over a pool of accounts often succeeds on the next account
          val left = timeoutSeconds * 1000L - (nowMillis - start)
          val retryable = rsp.status == 401 || rsp.status == 429 || rsp.status >= 500
          if retryable && left > 5000 then
            bodyText(rsp).flatMap: text =>
              logger.info(s"retrying once after ${rsp.status} ${firstLine(text)}")
              post(left.millis)
          else fuccess(rsp)
        .flatMap: rsp =>
          if rsp.status != 200 then
            bodyText(rsp).flatMap(text => fufail(s"API error ${rsp.status} ${firstLine(text)}"))
          else if rsp.contentType.contains("event-stream") then fuccess(serverSentEvents(rsp))
          else
            bodyText(rsp).map: text =>
              readOpenAi(Json.parse(text))
                .fold(e => Source.failed(Exception(e)), r => Source.single(Event.Done(r)))

  /** `data: {chunk}` lines, ending with `data: [DONE]`; the last chunk carries the usage. */
  private def serverSentEvents(rsp: StandaloneWSResponse): Source[Event, ?] =
    rsp.bodyAsSource
      .via(Framing.delimiter(ByteString("\n"), maximumFrameLength = 1 << 20, allowTruncation = true))
      .map(_.utf8String.trim)
      .collect { case line if line.startsWith("data:") => line.drop(5).trim }
      .takeWhile(_ != "[DONE]")
      .statefulMap(() => Chunks())(
        (chunks, data) =>
          val json = Json.parse(data)
          (json \ "error").toOption.foreach: e =>
            throw Exception(s"API error ${(e \ "message").asOpt[String] | e.toString.take(200)}")
          val delta = (json \ "choices" \ 0 \ "delta" \ "content").asOpt[String]
          delta.foreach(chunks.text.append)
          (json \ "model").asOpt[String].foreach(m => chunks.model = m)
          (json \ "usage").asOpt[JsObject].foreach(u => chunks.usage = usageOf(u))
          (chunks, delta.map(Event.Delta(_)))
        ,
        chunks => Event.Done(Reply(chunks.text.toString, chunks.model, chunks.usage)).some.some
      )
      .mapConcat(_.toList)

  private class Chunks:
    val text = StringBuilder()
    var model = config.model
    var usage = Usage(0, 0, 0, 0)

  private def bodyText(rsp: StandaloneWSResponse): Fu[String] =
    rsp.bodyAsSource.runFold(ByteString.empty)(_ ++ _).map(_.utf8String)

  private def readOpenAi(json: JsValue): Either[String, Reply] =
    (json \ "choices" \ 0 \ "message" \ "content")
      .asOpt[String]
      .toRight("No content")
      .map: content =>
        Reply(
          text = content,
          model = (json \ "model").asOpt[String] | config.model,
          usage = (json \ "usage").asOpt[JsObject].fold(Usage(0, 0, 0, 0))(usageOf)
        )

object CoachLlm:

  // a whole answer, written while the browser gets keep-alive lines, so the HTTP idle timeout never applies
  private val timeoutSeconds = 120

  private val bufferSize = 4096 // text deltas waiting for a slow browser

  enum Event:
    case Delta(text: String)
    case Done(reply: Reply)

  private def usageOf(usage: JsObject) =
    val prompt = (usage \ "prompt_tokens").asOpt[Int] | 0
    val cached = (usage \ "prompt_tokens_details" \ "cached_tokens").asOpt[Int] | 0
    Usage(
      input = prompt - cached,
      output = (usage \ "completion_tokens").asOpt[Int] | 0,
      cacheRead = cached,
      cacheWrite = 0
    )

  private def firstLine(text: String) =
    text.linesIterator.find(_.exists(_.isLetter)).getOrElse("-").take(300)

  /** Drops reasoning blocks and markup tags (ChatGPT web, for one, adds UI tags like <box>), keeping their
    * text.
    */
  private[aiCoach] def clean(text: String): String =
    text
      .replaceAll("(?s)<think>.*?</think>", "")
      .replaceAll("""</?[a-zA-Z][\w-]*(\s[^<>]*)?/?>""", "")
      .replaceAll("\n[ \t]*(\n[ \t]*)+", "\n\n")
      .trim

  /** @param url
    *   chat completions URL for "openai"; optional base URL override for "anthropic"
    * @param effort
    *   Claude effort (low, medium, high, ...); empty to leave the model default
    */
  case class Config(
      provider: String,
      url: String,
      model: String,
      apiKey: Secret,
      effort: String,
      maxTokens: Int
  )
  given ConfigLoader[Config] = AutoConfig.loader[Config]

  /** Token counts. `input` excludes cached prompt tokens, which are in `cacheRead`. */
  case class Usage(input: Int, output: Int, cacheRead: Int, cacheWrite: Int)

  /** `millis` until the whole answer, `firstMillis` until its first text. */
  case class Reply(text: String, model: String, usage: Usage, millis: Int = 0, firstMillis: Int = 0)
