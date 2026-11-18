import concurrent.futures
import threading

import numpy as np
from fastapi.testclient import TestClient

from app.main import create_app


class RecordingRecognizer:
    def __init__(self):
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def transcribe(self, samples, sample_rate, context="general"):
        self.calls.append((samples.copy(), sample_rate, context))
        self.entered.set()
        assert self.release.wait(5)
        return {"text": "ép hai ép bốn", "speech": True}


HEADERS = {
    "Origin": "http://localhost:8080",
    "X-Voice-ASR": "1",
    "Content-Type": "application/octet-stream",
    "X-Sample-Rate": "16000",
}
AUDIO = np.full(16000, 0.1, dtype="<f4").tobytes()


def test_audio_reaches_recognizer_and_text_is_returned_without_persisting_audio():
    rec = RecordingRecognizer()
    with TestClient(create_app(rec)) as client:
        result = client.post("/transcribe", content=AUDIO, headers=HEADERS)
    assert result.status_code == 200
    assert result.json()["text"] == "ép hai ép bốn"
    assert len(rec.calls) == 1
    assert rec.calls[0][1] == 16000
    np.testing.assert_array_equal(rec.calls[0][0], np.full(16000, 0.1, dtype="<f4"))
    assert result.headers["cache-control"] == "no-store"


def test_cross_origin_and_missing_intent_header_do_not_reach_model():
    rec = RecordingRecognizer()
    with TestClient(create_app(rec)) as client:
        for headers in [
            {**HEADERS, "Origin": "https://example.com"},
            {k: v for k, v in HEADERS.items() if k != "X-Voice-ASR"},
            {k: v for k, v in HEADERS.items() if k != "Origin"},
        ]:
            assert (
                client.post("/transcribe", content=AUDIO, headers=headers).status_code
                == 403
            )
    assert not rec.calls


def test_only_fixed_recognition_contexts_are_forwarded_to_model():
    rec = RecordingRecognizer()
    with TestClient(create_app(rec)) as client:
        for context in [None, "general", "promotion", "coordinates"]:
            headers = dict(HEADERS)
            if context is not None:
                headers["X-Voice-Context"] = context
            result = client.post("/transcribe", content=AUDIO, headers=headers)
            assert result.status_code == 200
            assert rec.calls[-1][2] == (context or "general")
        for context in ["", "e7e8q", "arbitrary prompt"]:
            result = client.post(
                "/transcribe",
                content=AUDIO,
                headers={**HEADERS, "X-Voice-Context": context},
            )
            assert result.status_code == 400
    assert len(rec.calls) == 4


def test_malformed_or_overlong_pcm_is_rejected_before_inference():
    rec = RecordingRecognizer()
    with TestClient(create_app(rec)) as client:
        for data, headers, status in [
            (b"abc", HEADERS, 400),
            (np.array([float("nan")] * 1600, dtype="<f4").tobytes(), HEADERS, 400),
            (np.array([2.0] * 1600, dtype="<f4").tobytes(), HEADERS, 400),
            (b"\0" * (16000 * 4 * 12 + 4), HEADERS, 413),
            (AUDIO, {**HEADERS, "X-Sample-Rate": "garbage"}, 400),
            (AUDIO, {**HEADERS, "Content-Type": "text/plain"}, 415),
        ]:
            assert (
                client.post("/transcribe", content=data, headers=headers).status_code
                == status
            )
    assert not rec.calls


def test_busy_service_rejects_extra_inference_instead_of_building_a_queue():
    rec = RecordingRecognizer()
    rec.release.clear()
    with (
        TestClient(create_app(rec)) as client,
        concurrent.futures.ThreadPoolExecutor() as pool,
    ):
        first = pool.submit(client.post, "/transcribe", content=AUDIO, headers=HEADERS)
        try:
            assert rec.entered.wait(3)
            second = client.post("/transcribe", content=AUDIO, headers=HEADERS)
            assert second.status_code == 429
        finally:
            rec.release.set()
        assert first.result().status_code == 200
    assert len(rec.calls) == 1
