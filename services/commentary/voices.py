"""Named commentators, shared by the worker, Scala whitelist and round UI.

Nano provides the named voices. Piper retains a basic male offline fallback.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Voice:
    id: str
    # Piper model file name, without ".onnx".
    model: str
    speaker: int | None = None
    # Below 1 the audio is replayed slower: a lower, darker voice. The synthesis is sped up by the same
    # factor, so the sentence keeps its length. Above 1 the opposite.
    pitch: float = 1.0
    # Piper's length scale on top of the model's own: below 1 speaks faster.
    length: float = 1.0
    nano_rate: float = 1.0


VAIS1000 = "vi_VN-vais1000-medium"
VIVOS = "vi_VN-vivos-x_low"
CATALOGUE = (
    Voice("vieneu-manh-dung", VIVOS, speaker=45, length=0.75),
    Voice("vieneu-huu-quan", VIVOS, speaker=45, length=0.75),
    Voice("vieneu-anh-khoi", VIVOS, speaker=45, length=0.75, nano_rate=1.15),
)
VOICES = {voice.id: voice for voice in CATALOGUE}
DEFAULT = CATALOGUE[0].id
NANO_VOICES = {
    "vieneu-huu-quan": "Hữu Quân",
    "vieneu-anh-khoi": "Anh Khôi",
    "vieneu-manh-dung": "Mạnh Dũng",
}


def greeting(voice):
    return f"Xin chào, tôi là {NANO_VOICES[voice]}, sẽ cùng bạn tận hưởng ván cờ này."


def nano_speed(voice, base):
    return min(2.0, base * VOICES[voice].nano_rate)
