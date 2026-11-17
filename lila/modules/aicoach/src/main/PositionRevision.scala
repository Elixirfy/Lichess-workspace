package lila.aicoach

import java.nio.charset.StandardCharsets.UTF_8
import java.security.MessageDigest

import chess.{ Move, Position }
import chess.format.Fen
import chess.format.pgn.SanStr
import chess.variant.Standard

/** Server-only replay. The worker independently repeats this validation.
  *
  * See services/coach/CONTRACT.md for the shared byte encoding and fixtures.
  */
object PositionRevision:

  case class Snapshot(
      initialFen: Fen.Full,
      uciHistory: List[String],
      fen: Fen.Full,
      ply: Int,
      revision: String
  )

  def replay(initialFen: Fen.Full, sans: List[SanStr]): Either[String, Snapshot] =
    if sans.size > 2000 then Left("history too long")
    else if initialFen.value.split(' ').length != 6 then Left("expected full FEN")
    else
      Fen
        .readWithMoveNumber(Standard, initialFen)
        .filter(p => Standard.valid(p.position, strict = true))
        .toRight("invalid initial position")
        .flatMap: initial =>
          val canonicalInitial = Fen.write(initial)
          sans
            .foldLeft[Either[String, (Position.AndFullMoveNumber, List[String])]](Right(initial -> Nil)):
              case (acc, san) =>
                acc.flatMap: (state, ucis) =>
                  if state.position.end then Left("history continues after terminal position")
                  else
                    state
                      .play(san)
                      .left
                      .map(_.toString)
                      .flatMap:
                        case (next, move: Move) if move.toSanStr == san =>
                          // scalachess normalizes castle destinations to the rook;
                          // contract v1 uses standard king-destination UCI.
                          val uci = move.castle.fold(move.toUci.uci): castle =>
                            s"${move.orig.key}${castle.kingTo.key}"
                          Right(next -> (uci :: ucis))
                        case _ => Left("expected canonical standard SAN")
            .map: (state, reversedUcis) =>
              val ucis = reversedUcis.reverse
              Snapshot(
                canonicalInitial,
                ucis,
                Fen.write(state),
                state.ply.value,
                hash(canonicalInitial, ucis)
              )

  private def hash(initialFen: Fen.Full, ucis: List[String]): String =
    val bytes = s"coach-position-v1\nstandard\n${initialFen.value}\n${ucis.mkString(" ")}".getBytes(UTF_8)
    java.util.HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes))
