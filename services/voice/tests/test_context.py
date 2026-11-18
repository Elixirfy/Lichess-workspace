from types import SimpleNamespace

import numpy as np

from app import recognizer


def test_coordinate_vocabulary_is_bounded_to_its_request_and_preserves_pcm(monkeypatch):
    calls = []

    class AcousticModel:
        def transcribe(self, samples, **options):
            calls.append((samples.copy(), options))
            return iter([SimpleNamespace(text="Hàng vốn.")]), None

    monkeypatch.setattr(recognizer, "get_speech_timestamps", lambda samples: [True])
    rec = recognizer.Recognizer.__new__(recognizer.Recognizer)
    rec.model = AcousticModel()
    audio = np.full(16000, 0.1, dtype=np.float32)
    for context in ["coordinates", "general", "promotion", "general"]:
        result = rec.transcribe(audio, 16000, context=context)
        assert result["text"] == "hàng vốn", "Do not repair an acoustic error as text"
    prompt = calls[0][1]["initial_prompt"]
    assert (
        "Cột một, cột hai, cột ba, cột bốn, cột năm, cột sáu, cột bảy, cột tám."
        in prompt
    )
    assert "Hàng một, hai, ba, bốn, năm, sáu, bảy, tám." in prompt
    assert calls[1][1]["initial_prompt"] == recognizer.VOCABULARY
    assert calls[2][1]["initial_prompt"] == recognizer.PROMOTION_VOCABULARY
    assert calls[3][1]["initial_prompt"] == recognizer.VOCABULARY
    for samples, _ in calls:
        np.testing.assert_array_equal(samples, audio)
