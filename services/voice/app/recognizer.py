import hashlib
import json
import math
import os
import re
import time
import unicodedata
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.utils import get_assets_path
from faster_whisper.vad import get_speech_timestamps
from scipy.signal import resample_poly

VOCABULARY = (
    "Cờ vua. vua, hậu, xe, tượng, mã, tốt. "
    "a, b, c, d, e, ép, g, h. "
    "một, hai, ba, bốn, năm, sáu, bảy, tám. "
    "đi, ăn, nhập thành, phong, xác nhận, huỷ bỏ."
)
# Use the extended terms only after primary ASR hears a promotion keyword.
# A global prompt change can degrade short confirmation utterances. Neither
# prompt contains the position, target move or a recording's expected answer.
PROMOTION_VOCABULARY = (
    "Cờ vua. Quân tốt, mã, tượng, xe, hậu, vua. "
    "Cột a, bê, xê, đê, e, ép, gờ, hát. "
    "Hàng một, hai, ba, bốn, năm, sáu, bảy, tám. "
    "Di chuyển, từ, tới, đến, ăn, nhập thành ngắn, nhập thành dài. "
    "Phong cấp thành hậu, phong cấp thành xe, phong cấp thành tượng, phong cấp thành mã. "
    "Xác nhận, đồng ý, hủy nước đi."
)
# Fixed domain terms, selected only for unhandled speech containing a column
# label. Every file/rank is represented; no position or expected move is sent.
COORDINATE_VOCABULARY = (
    "Cờ vua. Quân tốt, mã, tượng, xe, hậu, vua. "
    "Tên cột: a, bê, bờ, bi, xê, đê, dê, dờ, đờ, đi, e, ép, gờ, giê, hát. "
    "Hàng một, hai, ba, bốn, năm, sáu, bảy, tám. "
    "Cột một, cột hai, cột ba, cột bốn, cột năm, cột sáu, cột bảy, cột tám. "
    "Từ ô xuất phát tới ô đích. Đi, tới, đến, sang, lên, ăn."
)


def normalize(text):
    text = unicodedata.normalize("NFC", text).lower()
    text = "".join(" " if unicodedata.category(c).startswith("P") else c for c in text)
    text = re.sub(r"(?<=[^\W\d_])(?=\d)|(?<=\d)(?=[^\W\d_])", " ", text)
    aliases = dict(zip("012345678", "không một hai ba bốn năm sáu bảy tám".split()))
    aliases["f"] = "ép"
    aliases["bẩy"] = "bảy"
    return " ".join(aliases.get(word, word) for word in text.split())


class Recognizer:
    def __init__(self):
        directory = Path(os.environ.get("VOICE_MODEL_PATH", "/models/PhoWhisper-small"))
        lock = json.loads(
            (Path(__file__).parent.parent / "model-lock.json").read_text()
        )
        for name, expected in lock["files_sha256"].items():
            with (directory / name).open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                    raise RuntimeError(f"Model checksum mismatch: {name}")
        vad = Path(get_assets_path()) / "silero_vad_v6.onnx"
        if hashlib.sha256(vad.read_bytes()).hexdigest() != lock["vad_sha256"]:
            raise RuntimeError("VAD checksum mismatch")
        self.model = WhisperModel(
            str(directory),
            device="cpu",
            compute_type="int8",
            cpu_threads=4,
            num_workers=1,
            local_files_only=True,
        )
        get_speech_timestamps(np.zeros(16000, dtype=np.float32))

    def transcribe(self, samples, sample_rate, context="general"):
        started = time.perf_counter()
        if sample_rate != 16000:
            divisor = math.gcd(16000, sample_rate)
            samples = resample_poly(
                samples, 16000 // divisor, sample_rate // divisor
            ).astype(np.float32)
        # Gate whole utterances, preserving the PCM used for ASR. Do not trim short words.
        speech = bool(get_speech_timestamps(samples))
        text = ""
        if speech:
            segments, _ = self.model.transcribe(
                samples,
                language="vi",
                task="transcribe",
                temperature=0.0,
                beam_size=5,
                best_of=1,
                initial_prompt={
                    "promotion": PROMOTION_VOCABULARY,
                    "coordinates": COORDINATE_VOCABULARY,
                }.get(context, VOCABULARY),
                condition_on_previous_text=False,
                vad_filter=False,
                compression_ratio_threshold=None,
                log_prob_threshold=None,
                no_speech_threshold=None,
                without_timestamps=True,
                max_new_tokens=64,
            )
            text = normalize(" ".join(s.text.strip() for s in segments))
        return {
            "text": text,
            "speech": speech,
            "processing_ms": round((time.perf_counter() - started) * 1000),
        }
