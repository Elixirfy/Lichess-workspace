import hashlib
import io
import json
import wave

import numpy as np
from fastapi.testclient import TestClient

from app.main import create_app


HEADERS = {
    "Origin": "http://localhost:8080",
    "X-Voice-Recording": "1",
    "Content-Type": "application/octet-stream",
    "X-Sample-Rate": "16000",
    "X-Voice-Phrase": "pawn_plain",
}
PCM = np.linspace(-0.4, 0.4, 16000, dtype="<f4").tobytes()


class NoInference:
    def transcribe(self, *args):
        raise AssertionError("Recording must not run ASR or submit a chess move")


def test_recorder_is_disabled_without_an_explicit_storage_directory():
    with TestClient(create_app(NoInference())) as client:
        assert client.get("/record").status_code == 404
        assert client.get("/recordings", headers=HEADERS).status_code == 404


def test_explicit_save_persists_complete_audio_and_provenance_for_replay(tmp_path):
    with TestClient(create_app(NoInference(), recordings_dir=tmp_path)) as client:
        page = client.get("/record")
        assert page.status_code == 200
        assert 'id="record"' in page.text
        assert 'id="save"' in page.text
        saved = client.post("/recordings", content=PCM, headers=HEADERS)
        assert saved.status_code == 201
        item = saved.json()
        assert item["phrase_id"] == "pawn_plain"
        assert item["source"] == "browser-microphone"
        assert item["sample_rate"] == 16000
        assert item["duration_seconds"] == 1.0
        listing = client.get("/recordings", headers=HEADERS).json()
        assert item in listing["recordings"]
        assert any(p["id"] == "confirm" for p in listing["phrases"])
        audio = client.get(f"/recordings/{item['id']}/audio", headers=HEADERS)
        assert audio.status_code == 200
        assert audio.headers["cache-control"] == "no-store"
        assert hashlib.sha256(audio.content).hexdigest() == item["sha256"]
        with wave.open(io.BytesIO(audio.content)) as recorded:
            assert recorded.getparams()[:4] == (1, 2, 16000, 16000)
            actual = np.frombuffer(recorded.readframes(16000), dtype="<i2")
            expected = (np.frombuffer(PCM, dtype="<f4") * 32767).astype("<i2")
            np.testing.assert_array_equal(actual, expected)
        stored = json.loads(
            (tmp_path / f"{item['id']}.json").read_text(encoding="utf-8")
        )
        assert stored == item
        assert len(list(tmp_path.glob("*.wav"))) == 1


def test_file_name_minimal_pairs_are_available_and_saved_under_distinct_prompts(
    tmp_path,
):
    with TestClient(create_app(NoInference(), recordings_dir=tmp_path)) as client:
        phrases = {
            p["id"]: p["text"]
            for p in client.get("/recordings", headers=HEADERS).json()["phrases"]
        }
        expected = {
            "file_b_short": "Tốt bê hai tới bê bốn",
            "file_d_short": "Tốt đê hai tới đê bốn",
            "file_b_clear": "Tốt từ cột bê hàng hai đến cột bê hàng bốn",
            "file_d_clear": "Tốt từ cột đê hàng hai đến cột đê hàng bốn",
            "file_b_numbered": "Tốt từ cột hai hàng hai đến cột hai hàng bốn",
            "file_d_numbered": "Tốt từ cột bốn hàng hai đến cột bốn hàng bốn",
            "file_b_sound": "Tốt bờ hai tới bờ bốn",
            "file_d_sound": "Tốt dờ hai tới dờ bốn",
            "file_b_english": "Tốt từ cột bi hàng hai đến cột bi hàng bốn",
            "file_d_english": "Tốt từ cột đi hàng hai đến cột đi hàng bốn",
        }
        saved_ids = []
        for phrase_id, text in expected.items():
            assert phrases.get(phrase_id) == text
            response = client.post(
                "/recordings",
                content=PCM,
                headers={**HEADERS, "X-Voice-Phrase": phrase_id},
            )
            assert response.status_code == 201
            item = response.json()
            assert item["phrase_id"] == phrase_id and item["text"] == text
            saved_ids.append(item["id"])
        assert len(set(saved_ids)) == 10


def test_recordings_reject_other_origins_unmarked_requests_and_path_names(tmp_path):
    with TestClient(create_app(NoInference(), recordings_dir=tmp_path)) as client:
        for headers in [
            {**HEADERS, "Origin": "https://example.com"},
            {k: v for k, v in HEADERS.items() if k != "X-Voice-Recording"},
            {k: v for k, v in HEADERS.items() if k != "Origin"},
        ]:
            assert (
                client.post("/recordings", content=PCM, headers=headers).status_code
                == 403
            )
        assert client.get("/recordings").status_code == 403
        assert (
            client.get("/recordings/not-an-id/audio", headers=HEADERS).status_code
            == 404
        )
        assert (
            client.post(
                "/recordings",
                content=PCM,
                headers={**HEADERS, "X-Voice-Phrase": "../../outside"},
            ).status_code
            == 400
        )
    assert not list(tmp_path.iterdir())


def test_invalid_or_overlong_audio_never_creates_a_recording(tmp_path):
    with TestClient(create_app(NoInference(), recordings_dir=tmp_path)) as client:
        for data, headers, status in [
            (b"abc", HEADERS, 400),
            (b"\0" * (16000 * 4 * 12 + 4), HEADERS, 413),
            (np.full(16000, float("nan"), dtype="<f4").tobytes(), HEADERS, 400),
            (PCM, {**HEADERS, "X-Sample-Rate": "999999"}, 400),
            (PCM, {**HEADERS, "Content-Type": "audio/wav"}, 415),
        ]:
            assert (
                client.post("/recordings", content=data, headers=headers).status_code
                == status
            )
    assert not list(tmp_path.iterdir())


def test_retakes_keep_original_audio_and_test_fixtures_are_distinguished(tmp_path):
    with TestClient(create_app(NoInference(), recordings_dir=tmp_path)) as client:
        first = client.post("/recordings", content=PCM, headers=HEADERS).json()
        second = client.post("/recordings", content=PCM, headers=HEADERS).json()
        fixture = client.post(
            "/recordings",
            content=PCM,
            headers={**HEADERS, "X-Voice-Capture": "fixture"},
        ).json()
        assert len({first["id"], second["id"], fixture["id"]}) == 3
        assert fixture["source"] == "test-fixture"
        assert first["source"] == second["source"] == "browser-microphone"
        assert len(list(tmp_path.glob("*.wav"))) == 3
