"""Build command regression WAVs by joining documented CC0 human word recordings.

These fixtures exercise the complete audio pipeline, but are not recordings of
natural connected speech. No speech synthesis, denoising or gain fitting is used.
"""

import array
import hashlib
import json
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "scripts/fixtures/voice"
RATE = 48000

CASES = [
    ("f2f4", ["ep", "hai", "ep", "bon"], "ép hai ép bốn", "f2f4"),
    ("f2f4-second-speaker", ["ep", "hai", "ep", "bon2"], "ép hai ép bốn", "f2f4"),
    ("f2f3", ["ep", "hai", "ep", "ba"], "ép hai ép ba", "f2f3"),
    ("knight-f3", ["ma", "ep", "ba"], "mã ép ba", "g1f3"),
    ("illegal-f3f2", ["ep", "ba", "ep", "hai"], "ép ba ép hai", None),
    ("knight-f4", ["ma", "ep", "bon"], "mã ép bốn", "g2f4"),
    ("knight-f4-second-speaker", ["ma", "ep", "bon2"], "mã ép bốn", "g2f4"),
    ("knight-f2", ["ma", "ep", "hai"], "mã ép hai", "g4f2"),
    ("f4f3", ["ep", "bon", "ep", "ba"], "ép bốn ép ba", "f4f3"),
    ("square-f4", ["ep", "bon"], "ép bốn", "f2f4"),
    ("square-f3", ["ep", "ba"], "ép ba", "f2f3"),
    ("illegal-f4f2", ["ep", "bon", "ep", "hai"], "ép bốn ép hai", None),
    ("nonsense-ranks", ["ba", "bon", "hai"], "ba bốn hai", None),
]


def recorded_word(name: str) -> bytes:
    with wave.open(str(FIXTURES / f"{name}.wav")) as audio:
        assert audio.getparams()[:3] == (1, 2, RATE), "Expected mono 16-bit 48kHz source"
        samples = array.array("h", audio.readframes(audio.getnframes()))
    # Preserve 80ms either side of speech; shorten only the word recording's
    # surrounding silence to keep the joined command in a single utterance.
    threshold = max(abs(value) for value in samples) * 0.02
    active = [i for i, value in enumerate(samples) if abs(value) > threshold]
    margin = round(RATE * 0.08)
    return samples[max(0, active[0] - margin):min(len(samples), active[-1] + margin)].tobytes()


def main() -> None:
    output = FIXTURES / "commands"
    output.mkdir(exist_ok=True)
    cases = []
    for name, words, text, uci in CASES:
        destination = output / f"{name}.wav"
        with wave.open(str(destination), "wb") as audio:
            audio.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
            audio.writeframes(b"\0\0" * (RATE // 2))
            for word in words:
                audio.writeframes(recorded_word(word))
            audio.writeframes(b"\0\0" * (RATE * 2))
        cases.append({"file": f"commands/{name}.wav", "words": words,
                      "text": text, "uci": uci,
                      "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()})
    metadata = {
        "kind": "concatenated human CC0 word recordings; not natural connected speech",
        "sample_rate": RATE, "cases": cases,
    }
    (FIXTURES / "matrix-commands.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # The original browser acceptance uses its original five starting-position cases.
    metadata["cases"] = cases[:5]
    (FIXTURES / "commands.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Built {len(cases)} command recordings in {output}")


if __name__ == "__main__":
    main()
